import copy
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/mac-storage-audit/scripts/render_report.py'
spec = importlib.util.spec_from_file_location('renderer', SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
GIB = 1024**3


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, data):
        self.text.append(data)


def fixture():
    return {'title': 'Synthetic storage example',
            'accounting': {'scope': 'Example data volume', 'volume_used_bytes': 10*GIB},
            'roots': [{'path': '/workspace/builds', 'allocated_bytes': 6*GIB,
                       'status': 'complete', 'children': [
                           {'path': '/workspace/builds/cache', 'allocated_bytes': 2*GIB,
                            'status': 'complete'}]}]}


class ReportTests(unittest.TestCase):
    def render(self, data):
        return renderer.render_html(renderer._parse_input(data))

    def test_accounting_does_not_add_children(self):
        output = self.render(fixture())
        self.assertIn('6,442,450,944 bytes', output)
        self.assertIn('4,294,967,296 bytes', output)
        self.assertNotIn('8,589,934,592 bytes', output)

    def test_negative_gap_preserved(self):
        data = fixture(); data['accounting']['volume_used_bytes'] = GIB
        output = self.render(data)
        self.assertIn('-5,368,709,120 bytes', output)
        self.assertIn('−5.00 GiB', output)
        self.assertIn('accounting mismatch', output)

    def test_unknown_and_partial_coverage(self):
        data = fixture(); data['accounting']['volume_used_bytes'] = None
        self.assertIn('Unknown (volume used unavailable)', self.render(data))
        data = fixture(); data['roots'] = []
        self.assertIn('Unknown (no measured root allocations)', self.render(data))
        data = fixture(); data['roots'][0]['status'] = 'partial'
        self.assertIn('incomplete coverage; difference from observed allocations', self.render(data))

    def test_input_is_escaped_and_no_external_resources(self):
        payload = '<script src="https://invalid.example/track">alert(1)</script>'
        data = fixture(); data['title'] = payload
        data['roots'][0]['label'] = payload
        data['coverage'] = [payload]
        data['images'] = [{'reference': payload, 'note': payload}]
        data['roots'][0]['children'][0]['path'] += '<img src=x>'
        parser = Elements(); parser.feed(self.render(data))
        self.assertFalse(any(tag in ('script', 'img', 'iframe', 'link') for tag, attrs in parser.tags))
        self.assertIn(payload, ''.join(parser.text))
        self.assertTrue(any(tag == 'details' for tag, attrs in parser.tags))

    def test_reject_overlap_duplicate_and_invalid_numbers(self):
        for value in (-1, 1.5, True, float('nan')):
            data = fixture(); data['roots'][0]['allocated_bytes'] = value
            with self.assertRaises(renderer.InputError): self.render(data)
        for path in ('/workspace/builds', '//workspace/builds', '/workspace/builds/nested'):
            data = fixture(); data['roots'].append({'path': path, 'allocated_bytes': 1, 'status': 'complete'})
            with self.assertRaises(renderer.InputError): self.render(data)
        data = fixture(); data['roots'][0]['children'].append(
            {'path': '/workspace/builds/cache/nested', 'allocated_bytes': 1, 'status': 'complete'})
        with self.assertRaises(renderer.InputError): self.render(data)

    def test_child_over_parent_warns(self):
        data = fixture(); data['roots'][0]['children'][0]['allocated_bytes'] = 7*GIB
        self.assertIn('Child values were retained as a warning', self.render(data))

    def test_large_integer_and_no_overwrite(self):
        data = fixture(); data['accounting']['volume_used_bytes'] = 10**400
        self.assertIn('Unreconciled', self.render(data))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp); source = path/'input.json'; output = path/'report.html'
            source.write_text(json.dumps(fixture()))
            renderer.write_report(source, output)
            original = output.read_bytes()
            with self.assertRaises(renderer.InputError): renderer.write_report(source, output)
            self.assertEqual(original, output.read_bytes())


if __name__ == '__main__':
    unittest.main()

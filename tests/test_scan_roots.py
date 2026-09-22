import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/mac-storage-audit/scripts/scan_roots.py'
spec = importlib.util.spec_from_file_location('scanner', SCRIPT)
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'input'
        self.root.mkdir()

    def test_metadata_and_missing(self):
        item = self.root / 'file with spaces'
        item.write_bytes(b'x' * 8192)
        os.link(item, self.root / 'hardlink')
        os.symlink(item, self.root / 'symlink')
        result = scanner.scan([str(item), str(self.root / 'hardlink'),
                               str(self.root / 'symlink'), str(self.root / 'missing')], self.base / 'evidence')
        self.assertEqual([x['status'] for x in result],
                         ['complete', 'duplicate_hardlink', 'skipped_symlink', 'missing'])
        self.assertEqual(result[0]['allocated_kib'], item.stat().st_blocks / 2)
        self.assertIsNone(result[1]['allocated_kib'])

    def test_reject_self_counting(self):
        with self.assertRaises(ValueError):
            scanner.scan([str(self.root)], self.root / 'evidence')
        self.assertFalse((self.root / 'evidence').exists())

    def test_partial_rows_keep_uncertainty(self):
        def partial(command, stdout, stderr, **kwargs):
            stdout.write(('4\t' + str(self.root) + '\n').encode())
            stderr.write(b'denied descendant\n')
            return subprocess.CompletedProcess(command, 1)
        with patch.object(scanner.subprocess, 'run', side_effect=partial):
            result = scanner.scan([str(self.root)], self.base / 'evidence')
        self.assertEqual(result[0]['status'], 'partial')
        self.assertTrue(all(row['status'] == 'partial' for row in result[0]['rows']))

    def test_timeout_has_no_invented_total(self):
        with patch.object(scanner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('du', .01)):
            result = scanner.scan([str(self.root)], self.base / 'evidence', timeout=.01)
        self.assertEqual(result[0]['status'], 'timed_out')
        self.assertIsNone(result[0]['allocated_kib'])
        self.assertEqual(result[0]['timeout_seconds'], .01)

    @unittest.skipUnless(sys.platform == 'darwin', 'Uses macOS du flags')
    def test_real_directory_total(self):
        (self.root / 'file').write_bytes(b'x' * 4096)
        result = scanner.scan([str(self.root)], self.base / 'evidence')
        expected = int(subprocess.check_output(['/usr/bin/du', '-k', '-s', str(self.root)]).split()[0])
        self.assertEqual(result[0]['allocated_kib'], expected)
        self.assertEqual(result[0]['status'], 'complete')


if __name__ == '__main__':
    unittest.main()

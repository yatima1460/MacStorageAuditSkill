# HTML report input

`skills/mac-storage-audit/scripts/render_report.py` turns one JSON document into
a self-contained, accessible HTML report. It uses only the Python standard
library and does not inspect the machine or load image references. The command
does not replace an existing output unless `--force` is supplied:

```sh
python3 skills/mac-storage-audit/scripts/render_report.py \
  --input /workspace/report-input.json \
  --output /workspace/report.html
```

The top-level object has these fields:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `title` | string | no | Report heading. Defaults to `Mac Storage Audit`. |
| `accounting` | object | yes | One accounting scope shared by all roots. |
| `roots` | array | yes | Disjoint top-level root nodes. May be empty. |
| `coverage` | array of strings | no | Scan boundaries, exclusions, or other coverage notes. |
| `images` | array of objects | no | Separately reported image metadata. |

`accounting` requires a non-empty `scope` string and
`volume_used_bytes` (an integer or `null`). `capacity_bytes` and `free_bytes`
are optional integers and may be `null`. All byte values must be non-negative
finite integers. The producer must measure every root and the accounting fields
against the same scope; the renderer cannot infer or repair a scope mismatch.

Each root node has an absolute `path`, `allocated_bytes` (an integer or
`null`), `status` (`complete`, `partial`, or `unknown`), and optional `label`.
`children` is an optional array that defaults to empty. Child paths must be
descendants of their parent, and every path in the document must be unique.
Top-level roots and siblings must not overlap; a nested path belongs beneath its parent. A partial allocation is displayed as a lower
bound; an unknown allocation is displayed as missing coverage. Child values
are displayed for attribution and are already included in their parent, so the
renderer never adds child values to root values.

The measured total is the sum of known `allocated_bytes` values on disjoint
top-level roots only. When `volume_used_bytes` is available, the report shows
the signed value `volume_used_bytes - measured`; negative values are retained
and labeled as an accounting mismatch. When volume used is `null`, or no root has a measured allocation, reconciliation is shown as unknown. For partial coverage, the numeric difference is explicitly labeled as a difference from observed allocations, not a complete attribution or cleanup estimate. If known immediate child values exceed a
known parent value, the report emits a warning and continues; clone or scan
changes can make those values overlap.

Image objects require a `reference` string. `reported_bytes` is an optional
integer or `null`, and `note` is an optional string. References remain text in
the report, so the generated file performs no network or local image fetch.

Example (synthetic paths only):

```json
{
  "title": "Example project volume",
  "accounting": {
    "scope": "/workspace/project volume",
    "volume_used_bytes": 21474836480,
    "capacity_bytes": 107374182400,
    "free_bytes": 85899345920
  },
  "roots": [
    {
      "path": "/workspace/project/builds",
      "label": "Builds",
      "allocated_bytes": 12884901888,
      "status": "complete",
      "children": [
        {
          "path": "/workspace/project/builds/cache",
          "allocated_bytes": 4294967296,
          "status": "partial",
          "children": []
        }
      ]
    },
    {
      "path": "/workspace/project/assets",
      "allocated_bytes": null,
      "status": "unknown",
      "children": []
    }
  ],
  "coverage": ["The assets subtree was not readable during this run."],
  "images": [
    {
      "reference": "synthetic-image:demo",
      "reported_bytes": 536870912,
      "note": "Reported image size; separate from the filesystem tree."
    }
  ]
}
```

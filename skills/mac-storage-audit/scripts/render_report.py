#!/usr/bin/env python3
"""Render a self-contained HTML report from a macOS storage-audit JSON input.

The renderer is deliberately stdlib-only and does not inspect the filesystem.
It treats top-level roots as the accounting boundary: child values are shown
for attribution and are never added to their parent or to the measured total.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, localcontext
import html
import json
from pathlib import Path
import posixpath
import sys
from typing import Any, Iterable, List, Optional, Tuple


STATUSES = {"complete", "partial", "unknown"}
MISSING = object()


class InputError(ValueError):
    """Raised when the report input does not satisfy the documented schema."""


def _reject_constant(value: str) -> Any:
    raise InputError(f"non-finite JSON number is not allowed: {value}")


def _expect_object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{where} must be an object")
    return value


def _expect_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise InputError(f"{where} must be an array")
    return value


def _expect_string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise InputError(f"{where} must be a string")
    return value


def _expect_nonnegative_integer(value: Any, where: str, *, nullable: bool) -> Optional[int]:
    if value is None and nullable:
        return None
    # bool is an int subclass, but is not a JSON integer for this schema.
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{where} must be a non-negative finite integer or null")
    if value < 0:
        raise InputError(f"{where} must be non-negative")
    return value


def _normal_path(value: Any, where: str) -> Tuple[str, str]:
    path = _expect_string(value, where)
    if "\x00" in path or not posixpath.isabs(path):
        raise InputError(f"{where} must be an absolute POSIX path")
    normalized = "/" + posixpath.normpath(path).lstrip("/")
    if not normalized.startswith("/"):
        raise InputError(f"{where} must be an absolute POSIX path")
    return path, normalized


def _is_descendant(path: str, parent: str) -> bool:
    return path != parent and path.startswith(parent.rstrip("/") + "/")


def _get_optional_string(obj: dict[str, Any], key: str, where: str) -> Optional[str]:
    value = obj.get(key, MISSING)
    if value is MISSING or value is None:
        return None
    return _expect_string(value, f"{where}.{key}")


def _parse_node(value: Any, where: str, parent_path: Optional[str],
                seen: dict[str, str]) -> dict[str, Any]:
    obj = _expect_object(value, where)
    if "path" not in obj:
        raise InputError(f"{where}.path is required")
    display_path, normalized_path = _normal_path(obj["path"], f"{where}.path")
    previous = seen.get(normalized_path)
    if previous is not None:
        raise InputError(f"duplicate path {display_path!r}; already used at {previous}")
    seen[normalized_path] = f"{where}.path"
    if parent_path is not None and not _is_descendant(normalized_path, parent_path):
        raise InputError(f"{where}.path must be a descendant of its parent path")

    if "allocated_bytes" not in obj:
        raise InputError(f"{where}.allocated_bytes is required")
    allocated = _expect_nonnegative_integer(
        obj["allocated_bytes"], f"{where}.allocated_bytes", nullable=True
    )
    status = _expect_string(obj.get("status"), f"{where}.status")
    if status not in STATUSES:
        allowed = ", ".join(sorted(STATUSES))
        raise InputError(f"{where}.status must be one of: {allowed}")
    label = _get_optional_string(obj, "label", where)
    raw_children = obj.get("children", [])
    children = [
        _parse_node(child, f"{where}.children[{index}]", normalized_path, seen)
        for index, child in enumerate(_expect_list(raw_children, f"{where}.children"))
    ]
    child_paths = sorted(child["normalized_path"] for child in children)
    for first, second in zip(child_paths, child_paths[1:]):
        if _is_descendant(second, first):
            raise InputError(f"{where}.children must be disjoint siblings; nest overlapping paths")
    return {
        "path": display_path,
        "normalized_path": normalized_path,
        "label": label,
        "allocated_bytes": allocated,
        "status": status,
        "children": children,
    }


def _parse_input(raw: Any) -> dict[str, Any]:
    obj = _expect_object(raw, "input")
    title = _get_optional_string(obj, "title", "input") or "Mac Storage Audit"

    if "accounting" not in obj:
        raise InputError("input.accounting is required")
    accounting_obj = _expect_object(obj["accounting"], "input.accounting")
    if "scope" not in accounting_obj:
        raise InputError("input.accounting.scope is required")
    scope = _expect_string(accounting_obj["scope"], "input.accounting.scope")
    if not scope.strip():
        raise InputError("input.accounting.scope must not be empty")
    if "volume_used_bytes" not in accounting_obj:
        raise InputError("input.accounting.volume_used_bytes is required (it may be null)")
    accounting = {
        "scope": scope,
        "volume_used_bytes": _expect_nonnegative_integer(
            accounting_obj["volume_used_bytes"],
            "input.accounting.volume_used_bytes",
            nullable=True,
        ),
        "capacity_bytes": _expect_nonnegative_integer(
            accounting_obj.get("capacity_bytes"),
            "input.accounting.capacity_bytes",
            nullable=True,
        ),
        "free_bytes": _expect_nonnegative_integer(
            accounting_obj.get("free_bytes"),
            "input.accounting.free_bytes",
            nullable=True,
        ),
    }

    if "roots" not in obj:
        raise InputError("input.roots is required")
    seen: dict[str, str] = {}
    roots = [
        _parse_node(root, f"input.roots[{index}]", None, seen)
        for index, root in enumerate(_expect_list(obj["roots"], "input.roots"))
    ]
    normalized_roots = [root["normalized_path"] for root in roots]
    for index, path in enumerate(normalized_roots):
        for other_index, other in enumerate(normalized_roots):
            if index != other_index and (_is_descendant(path, other) or _is_descendant(other, path)):
                raise InputError(
                    "top-level roots must be disjoint; "
                    f"input.roots[{index}] overlaps input.roots[{other_index}]"
                )

    coverage_value = obj.get("coverage", [])
    coverage = [
        _expect_string(item, f"input.coverage[{index}]")
        for index, item in enumerate(_expect_list(coverage_value, "input.coverage"))
    ]
    images_value = obj.get("images", [])
    images: list[dict[str, Any]] = []
    for index, item in enumerate(_expect_list(images_value, "input.images")):
        where = f"input.images[{index}]"
        image = _expect_object(item, where)
        if "reference" not in image:
            raise InputError(f"{where}.reference is required")
        images.append({
            "reference": _expect_string(image["reference"], f"{where}.reference"),
            "reported_bytes": _expect_nonnegative_integer(
                image.get("reported_bytes"),
                f"{where}.reported_bytes",
                nullable=True,
            ),
            "note": _get_optional_string(image, "note", where),
        })

    return {
        "title": title,
        "accounting": accounting,
        "roots": roots,
        "coverage": coverage,
        "images": images,
    }


def load_input(path: Path) -> dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise InputError(f"could not read input {path}: {error}") from error
    try:
        raw = json.loads(raw_text, parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        raise InputError(f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}") from error
    return _parse_input(raw)


def _format_bytes(value: Optional[int]) -> str:
    if value is None:
        return "Unknown"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    # Decimal keeps very large, valid JSON integers renderable without a
    # float overflow or silently losing the exact byte count.
    with localcontext() as context:
        context.prec = 32
        amount = abs(Decimal(value))
        unit_index = 0
        while amount >= 1024 and unit_index < len(units) - 1:
            amount /= 1024
            unit_index += 1
        if unit_index == 0:
            human = f"{value:,}"
        elif amount >= 100:
            human = f"{amount:,.0f}"
        elif amount >= 10:
            human = f"{amount:,.1f}"
        else:
            human = f"{amount:,.2f}"
    if value < 0 and unit_index > 0:
        human = "−" + human
    return f"{human} {units[unit_index]} ({value:,} bytes)"


def _display_size(value: Optional[int], *, lower_bound: bool = False) -> str:
    if value is None:
        return "Unknown"
    prefix = "≥ " if lower_bound else ""
    return prefix + _format_bytes(value)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _sort_nodes(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        nodes,
        key=lambda node: (
            node["allocated_bytes"] is None,
            -(node["allocated_bytes"] or 0),
            node["normalized_path"],
        ),
    )


def _node_warnings(node: dict[str, Any]) -> list[dict[str, Any]]:
    parent_value = node["allocated_bytes"]
    child_values = [
        child["allocated_bytes"]
        for child in node["children"]
        if child["allocated_bytes"] is not None
    ]
    if parent_value is None or not child_values:
        return []
    child_sum = sum(child_values)
    if child_sum <= parent_value:
        return []
    return [{
        "path": node["path"],
        "parent": parent_value,
        "children": child_sum,
    }]


def _collect_warnings(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for node in nodes:
        warnings.extend(_node_warnings(node))
        warnings.extend(_collect_warnings(node["children"]))
    return warnings


def _render_node(node: dict[str, Any]) -> str:
    children = _sort_nodes(node["children"])
    allocation = _display_size(
        node["allocated_bytes"],
        lower_bound=node["status"] != "complete" and node["allocated_bytes"] is not None,
    )
    label = node["label"]
    label_html = f'<span class="node-label">{_esc(label)}</span>' if label else ""
    status_text = node["status"]
    if node["status"] != "complete":
        status_text += "; lower bound or incomplete"
    row = (
        '<span class="node-row">'
        f'<code class="node-path">{_esc(node["path"])}</code>'
        f'{label_html}'
        f'<span class="node-size">{_esc(allocation)}</span>'
        f'<span class="node-status status-{_esc(node["status"])}">{_esc(status_text)}</span>'
        '</span>'
    )
    if not children:
        return f'<div class="tree-leaf">{row}</div>'
    nested = "".join(_render_node(child) for child in children)
    return f'<details class="tree-node" open><summary>{row}</summary><div class="tree-children">{nested}</div></details>'


def _summary_card(label: str, value: str, class_name: str = "", element_id: Optional[str] = None) -> str:
    id_attribute = f' id="{element_id}"' if element_id else ""
    return (
        f'<div{id_attribute} class="summary-card {class_name}">'
        f'<h3>{_esc(label)}</h3><p>{_esc(value)}</p></div>'
    )


def _render_coverage(coverage: list[str], roots: list[dict[str, Any]]) -> str:
    detected: list[str] = []
    for root in roots:
        if root["allocated_bytes"] is None or root["status"] != "complete":
            qualifier = "missing allocation" if root["allocated_bytes"] is None else "partial allocation"
            detected.append(f'{root["path"]}: {qualifier}')
    items = coverage + detected
    if not items:
        return '<p class="muted">No coverage notes supplied.</p>'
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _render_images(images: list[dict[str, Any]]) -> str:
    if not images:
        return '<p class="muted">No image references supplied.</p>'
    rows = []
    for image in images:
        note = image["note"] or ""
        rows.append(
            "<tr>"
            f'<th scope="row"><code>{_esc(image["reference"])}</code></th>'
            f'<td>{_esc(_format_bytes(image["reported_bytes"]))}</td>'
            f'<td>{_esc(note)}</td>'
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th scope="col">Reference</th>'
        '<th scope="col">Reported size</th><th scope="col">Note</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def render_html(report: dict[str, Any]) -> str:
    accounting = report["accounting"]
    roots = report["roots"]
    volume_used = accounting["volume_used_bytes"]
    measured = sum(
        root["allocated_bytes"]
        for root in roots
        if root["allocated_bytes"] is not None
    )
    known_root_count = sum(root["allocated_bytes"] is not None for root in roots)
    lower_bound = any(
        root["allocated_bytes"] is None or root["status"] != "complete"
        for root in roots
    )
    unreconciled = None if volume_used is None or known_root_count == 0 else volume_used - measured
    mismatch = unreconciled is not None and unreconciled < 0
    unknown_roots = sum(root["allocated_bytes"] is None for root in roots)
    warning_items = _collect_warnings(roots)

    if known_root_count == 0:
        measured_text = "Unknown (no known root allocations)"
    else:
        measured_text = _display_size(measured, lower_bound=lower_bound)
    if known_root_count == 0:
        unreconciled_text = "Unknown (no measured root allocations)"
    elif volume_used is None:
        unreconciled_text = "Unknown (volume used unavailable)"
    else:
        unreconciled_text = _display_size(unreconciled)
        if mismatch:
            unreconciled_text += " — accounting mismatch"
        elif lower_bound:
            unreconciled_text += " — incomplete coverage; difference from observed allocations"

    root_markup = "".join(_render_node(root) for root in _sort_nodes(roots))
    if not root_markup:
        root_markup = '<p class="muted">No roots supplied.</p>'

    warning_markup = ""
    if warning_items:
        warning_rows = "".join(
            f'<li><code>{_esc(item["path"])}</code> lists {_esc(_format_bytes(item["children"]))} '
            f'of immediate children against {_esc(_format_bytes(item["parent"]))} for the parent. '
            "Child values were retained as a warning because clone or scan changes can make them overlap.</li>"
            for item in warning_items
        )
        warning_markup = f'<section class="warning" aria-labelledby="warnings-heading"><h2 id="warnings-heading">Warnings</h2><ul>{warning_rows}</ul></section>'

    if unknown_roots:
        missing_note = f" {unknown_roots} root(s) have no allocation value."
    else:
        missing_note = ""
    accounting_note = (
        "The measured total is the sum of known top-level root allocations only."
        " Partial or unknown roots make it a lower bound, and missing roots remain outside the total."
        " Unreconciled space is the signed difference against these observations, not guaranteed reclaimable space."
        + missing_note
    )

    css = """
:root { color-scheme: light dark; --bg: #f7f8fa; --panel: #ffffff; --text: #1e2430; --muted: #596273; --line: #d5dae3; --accent: #174ea6; --warn-bg: #fff4d6; --warn-line: #9a6700; --code-bg: #eef1f5; }
* { box-sizing: border-box; }
html { overflow-x: hidden; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; overflow-x: hidden; }
main { width: min(1120px, 100%); margin: 0 auto; padding: 2rem clamp(1rem, 3vw, 2.5rem) 4rem; }
h1, h2, h3 { line-height: 1.2; }
h1 { margin: 0 0 .35rem; font-size: clamp(1.7rem, 4vw, 2.5rem); overflow-wrap: anywhere; }
h2 { margin: 2.2rem 0 .75rem; font-size: 1.35rem; }
h3 { margin: 0 0 .4rem; font-size: .82rem; letter-spacing: .02em; text-transform: uppercase; }
p { margin: .55rem 0; }
.scope, .muted { color: var(--muted); }
code { background: var(--code-bg); border-radius: .25rem; font: .92em ui-monospace, SFMono-Regular, Menlo, monospace; padding: .08rem .3rem; overflow-wrap: anywhere; word-break: break-word; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(210px, 100%), 1fr)); gap: .75rem; margin: 1.5rem 0; }
.summary-card { background: var(--panel); border: 1px solid var(--line); border-radius: .6rem; min-width: 0; padding: .9rem 1rem; }
.summary-card p { font-size: 1.05rem; font-weight: 650; overflow-wrap: anywhere; }
#unreconciled-space { grid-column: 1 / -1; border-left: .25rem solid var(--accent); }
.summary-card.mismatch { border-color: var(--warn-line); background: var(--warn-bg); }
.note { border-left: .25rem solid var(--accent); color: var(--muted); padding: .35rem .8rem; }
.tree { background: var(--panel); border: 1px solid var(--line); border-radius: .6rem; padding: .5rem; }
.tree details { min-width: 0; }
.tree summary { cursor: pointer; list-style-position: outside; padding: .35rem .25rem; }
.tree summary:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.tree summary::marker { color: var(--accent); }
.tree-children { border-left: 1px solid var(--line); margin-left: .7rem; padding-left: clamp(.25rem, 1.2vw, .9rem); min-width: 0; }
.tree-leaf { padding: .35rem .25rem .35rem 1.5rem; min-width: 0; }
.node-row { align-items: baseline; display: grid; gap: .2rem .8rem; grid-template-columns: minmax(0, 1fr) minmax(10rem, auto); min-width: 0; }
.node-path { min-width: 0; grid-column: 1; grid-row: 1; }
.node-label { grid-column: 1; grid-row: 2; color: var(--muted); font-size: .9em; overflow-wrap: anywhere; }
.node-size { grid-column: 2; grid-row: 1; text-align: right; white-space: normal; }
.node-status { grid-column: 2; grid-row: 2; text-align: right; color: var(--muted); font-size: .84em; }
.status-partial, .status-unknown { color: var(--warn-line); }
.warning { background: var(--warn-bg); border: 1px solid var(--warn-line); border-radius: .6rem; margin-top: 1.5rem; padding: .2rem 1rem .8rem; }
.warning code { background: transparent; padding: 0; }
.table-wrap { max-width: 100%; overflow-x: auto; }
table { border-collapse: collapse; min-width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: .6rem .5rem; text-align: left; vertical-align: top; }
th[scope="row"] { font-weight: 600; }
@media (max-width: 680px) {
  main { padding-top: 1.2rem; }
  .node-row { display: block; }
  .node-size, .node-status, .node-label { display: block; margin-top: .12rem; text-align: left; }
  .tree-children { margin-left: .35rem; padding-left: .35rem; }
  .tree-leaf { padding-left: .8rem; }
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #15171a; --panel: #1d2025; --text: #edf0f4; --muted: #b0b8c5; --line: #3a424e; --accent: #8ab4f8; --warn-bg: #332b18; --warn-line: #f1c75b; --code-bg: #2a3038; }
}
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{_esc(report["title"])}</title>
<style>{css}</style>
</head>
<body>
<main>
<header>
<h1>{_esc(report["title"])}</h1>
<p class="scope">Accounting scope: <code>{_esc(accounting["scope"])}</code></p>
</header>
<section aria-labelledby="summary-heading">
<h2 id="summary-heading">Storage summary</h2>
<div class="summary-grid">
{_summary_card("Capacity", _format_bytes(accounting["capacity_bytes"]), element_id="capacity-space")}
{_summary_card("Free", _format_bytes(accounting["free_bytes"]), element_id="free-space")}
{_summary_card("Volume used", _format_bytes(volume_used), element_id="used-space")}
{_summary_card("Measured roots", measured_text, element_id="measured-space")}
{_summary_card("Unreconciled", unreconciled_text, "mismatch" if mismatch else "", "unreconciled-space")}
</div>
<p class="note">{_esc(accounting_note)} Children are already included in their parent allocations and are shown for attribution; they are not added again.</p>
</section>
{warning_markup}
<section aria-labelledby="tree-heading">
<h2 id="tree-heading">Measured roots and attribution</h2>
<div class="tree">{root_markup}</div>
</section>
<section aria-labelledby="coverage-heading">
<h2 id="coverage-heading">Coverage</h2>
{_render_coverage(report["coverage"], roots)}
</section>
<section aria-labelledby="images-heading">
<h2 id="images-heading">Image references</h2>
<p class="muted">References are displayed as reported metadata; image sizes are separate from the filesystem tree and are not added to it.</p>
{_render_images(report["images"])}
</section>
</main>
</body>
</html>
"""


def write_report(input_path: Path, output_path: Path, *, force: bool = False) -> None:
    report = load_input(input_path)
    rendered = render_html(report)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if force:
            output_path.write_text(rendered, encoding="utf-8")
        else:
            with output_path.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
    except FileExistsError as error:
        raise InputError(f"output already exists: {output_path} (use --force to replace it)") from error
    except OSError as error:
        raise InputError(f"could not write output {output_path}: {error}") from error


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON report input")
    parser.add_argument("--output", required=True, type=Path, help="HTML report output")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args(argv)
    try:
        write_report(args.input, args.output, force=args.force)
    except InputError as error:
        print(f"render_report.py: error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

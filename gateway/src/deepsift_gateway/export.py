"""Investigation reports: JSON, CSV and a self-contained HTML page."""

from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import re
from collections import defaultdict
from typing import Any

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

STYLE = """
:root { color-scheme: light dark; font: 15px/1.5 system-ui, sans-serif; }
body { max-width: 72rem; margin: 2rem auto; padding: 0 1rem; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: start; padding: .35rem .6rem; border-bottom: 1px solid #8884; }
td.value { overflow-wrap: anywhere; }
caption { text-align: start; font-weight: 600; padding: .5rem 0; }
"""


def safe_cell(value: Any) -> str:
    """Neutralise spreadsheet formulas (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(entities: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["id", "type", "value", "score", "level", "sources", "avatar_group", "first_seen"]
    )
    for entity in entities:
        writer.writerow(
            [
                safe_cell(entity["id"]),
                safe_cell(entity["type"]),
                safe_cell(entity["value"]),
                entity["score"],
                entity["level"],
                safe_cell(" ".join(s["service"] for s in entity["sources"])),
                safe_cell(entity["avatar_group"] or ""),
                entity["first_seen"],
            ]
        )
    return buffer.getvalue()


def style_hash() -> str:
    digest = hashlib.sha256(STYLE.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def html_csp() -> str:
    """The report runs no script and loads nothing: only its own inline style."""
    return f"default-src 'none'; style-src '{style_hash()}'; base-uri 'none'; form-action 'none'"


def to_html(report: dict[str, Any]) -> str:
    """Every value is escaped; links are plain text so the report fetches nothing."""
    esc = html.escape
    investigation = report["investigation"]
    rows = []
    for entity in report["entities"]:
        sources = ", ".join(s["service"] for s in entity["sources"])
        rows.append(
            "<tr>"
            f"<td>{esc(entity['type'])}</td>"
            f"<td class=value>{esc(entity['value'])}</td>"
            f"<td>{entity['score']:.2f}</td>"
            f"<td>{esc(entity['level'])}</td>"
            f"<td>{esc(sources)}</td>"
            f"<td>{esc(entity['avatar_group'] or '')}</td>"
            "</tr>"
        )
    groups: dict[str, list[str]] = defaultdict(list)
    for entity in report["entities"]:
        if entity["avatar_group"]:
            groups[entity["avatar_group"]].append(entity["value"])
    group_items = "".join(
        f"<li>{esc(name)}: {esc(', '.join(values))}</li>" for name, values in sorted(groups.items())
    )
    runs = "".join(
        f"<li>{esc(run['type'])} {esc(run['selector'])} ({esc(run['status'])})</li>"
        for run in report["runs"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>DeepSift report: {esc(investigation["name"])}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>{esc(investigation["name"])}</h1>
<p>Exported {esc(report["exported_at"])} from DeepSift.
Public sources only; verify before acting.</p>
<h2>Runs</h2>
<ul>{runs}</ul>
<h2>Avatar groups</h2>
<ul>{group_items or "<li>None</li>"}</ul>
<table>
<caption>Findings ({len(report["entities"])})</caption>
<thead><tr><th scope=col>Type</th><th scope=col>Value</th><th scope=col>Score</th>
<th scope=col>Level</th><th scope=col>Sources</th><th scope=col>Avatar group</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</body>
</html>
"""


def filename(name: str, extension: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:60] or "investigation"
    return f"deepsift-{stem}.{extension}"

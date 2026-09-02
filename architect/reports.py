from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from architect.models import AnalysisGraph


def json_report(graph: AnalysisGraph) -> str:
    return json.dumps(graph.to_dict(), indent=2, sort_keys=True)


def sarif_report(graph: AnalysisGraph) -> str:
    active = [finding for finding in graph.findings if not finding.suppressed]
    rules = sorted({finding.rule for finding in active})
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "Vinyas", "version": "1.0.0", "rules": [
                {"id": rule, "shortDescription": {"text": rule.replace("-", " ").title()}}
                for rule in rules
            ]}},
            "results": [_sarif_result(finding) for finding in active],
        }],
    }
    return json.dumps(payload, indent=2)


def _sarif_result(finding: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": finding.rule,
        "level": "error" if finding.severity == "error" else "warning",
        "message": {"text": finding.message},
        "partialFingerprints": {"vinyasFingerprint": finding.fingerprint},
    }
    if finding.path:
        result["locations"] = [{"physicalLocation": {
            "artifactLocation": {"uri": finding.path},
            "region": {"startLine": max(1, finding.line)},
        }}]
    return result


def html_report(graph: AnalysisGraph) -> str:
    payload = graph.to_dict()
    summary = payload["summary"]
    rows = "".join(
        f"<tr><td><span class='sev {html.escape(item.severity)}'>{html.escape(item.severity)}</span></td>"
        f"<td>{html.escape(item.rule)}</td><td><code>{html.escape(item.path)}:{item.line}</code></td>"
        f"<td>{html.escape(item.message)}</td><td><code>{html.escape(item.evidence)}</code></td></tr>"
        for item in graph.findings if not item.suppressed
    ) or "<tr><td colspan='5' class='empty'>No active findings</td></tr>"
    metrics = "".join(
        f"<tr><td><code>{html.escape(file.path)}</code></td><td>{file.metrics.fan_in}</td>"
        f"<td>{file.metrics.fan_out}</td><td>{file.metrics.symbol_count}</td>"
        f"<td>{file.metrics.dependency_depth}</td><td>{file.metrics.cycle_participation}</td></tr>"
        for file in sorted(graph.files, key=lambda item: (-item.metrics.fan_out, item.path))
    )
    labels = [('files','Files'),('dependencies','Edges'),('findings','Findings'),('cycles','Cycles'),('unresolved','Unresolved'),('external','External')]
    cards = "".join(f'<div class="card"><span class="muted">{label}</span><strong>{summary[key]}</strong></div>' for key, label in labels)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Vinyas Report</title><style>
:root{{--bg:#08111f;--panel:#101d2d;--line:#28405a;--text:#e9f2fb;--muted:#94abc1;--blue:#4db8ff;--red:#ff747d;--amber:#ffc56b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px Inter,system-ui,sans-serif}}main{{max-width:1400px;margin:auto;padding:32px}}h1{{margin:0;font-size:28px}}.muted{{color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:24px 0}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}.card strong{{display:block;font-size:25px;color:var(--blue)}}section{{margin-top:30px}}table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line)}}th,td{{padding:11px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--muted)}}code{{font:12px ui-monospace,monospace;white-space:pre-wrap}}.sev{{padding:3px 7px;border-radius:8px}}.error{{color:var(--red)}}.warning{{color:var(--amber)}}.empty{{text-align:center;color:var(--muted)}}@media(max-width:900px){{.cards{{grid-template-columns:repeat(2,1fr)}}main{{padding:18px}}.scroll{{overflow:auto}}}}</style></head><body><main><p class="muted">VINYAS · DETERMINISTIC REPORT</p><h1>{html.escape(Path(graph.root).name)}</h1><p class="muted">{html.escape(graph.root)}</p><div class="cards">{cards}</div><section><h2>Findings</h2><div class="scroll"><table><thead><tr><th>Severity</th><th>Rule</th><th>Location</th><th>Message</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></div></section><section><h2>Explainable metrics</h2><div class="scroll"><table><thead><tr><th>File</th><th>Fan-in</th><th>Fan-out</th><th>Symbols</th><th>Depth</th><th>Cycles</th></tr></thead><tbody>{metrics}</tbody></table></div></section></main></body></html>"""


def render_report(graph: AnalysisGraph, format_name: str) -> str:
    renderers = {"json": json_report, "sarif": sarif_report, "html": html_report}
    if format_name not in renderers:
        raise ValueError(f"unsupported report format: {format_name}")
    return renderers[format_name](graph)

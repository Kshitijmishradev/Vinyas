from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from architect.baseline import active_fingerprints, load_baseline
from architect.engine import analyze_repository
from architect.reports import render_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vinyas",
        description="Deterministic architecture analysis and governance",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    analyze = subcommands.add_parser("analyze", help="Analyze a repository and print JSON")
    _path_arguments(analyze)
    analyze.add_argument("--output", "-o", type=Path)

    report = subcommands.add_parser("report", help="Generate a portable report")
    _path_arguments(report)
    report.add_argument("--format", choices=("html", "json", "sarif"), default="html")
    report.add_argument("--output", "-o", type=Path, required=True)

    check = subcommands.add_parser(
        "check",
        help="Fail only for findings new relative to a baseline",
    )
    _path_arguments(check)
    check.add_argument("--baseline", required=True)
    check.add_argument("--sarif", type=Path)
    check.add_argument("--html", type=Path)

    serve = subcommands.add_parser(
        "serve",
        help="Start the repository-restricted local explorer",
    )
    serve.add_argument("path", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    return parser


def _path_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path)
    parser.add_argument("--config", type=Path)


def _write(text: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(f"Wrote {output}", file=sys.stderr)
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.path.expanduser().resolve()
    if args.command == "serve":
        if not root.is_dir():
            raise SystemExit(f"Repository does not exist: {root}")
        os.environ["VINYAS_ROOT"] = str(root)
        import uvicorn

        uvicorn.run("architect.api_server:app", host=args.host, port=args.port)
        return 0

    graph = analyze_repository(root, args.config)
    if args.command == "analyze":
        _write(render_report(graph, "json"), args.output)
        return 0
    if args.command == "report":
        _write(render_report(graph, args.format), args.output)
        return 0
    if args.command == "check":
        baseline = load_baseline(root, args.baseline)
        new = active_fingerprints(graph) - active_fingerprints(baseline)
        if args.sarif:
            _write(render_report(graph, "sarif"), args.sarif)
        if args.html:
            _write(render_report(graph, "html"), args.html)
        active = [item for item in graph.findings if item.fingerprint in new]
        for finding in active:
            print(
                f"{finding.severity.upper()} {finding.rule} "
                f"{finding.path}:{finding.line} {finding.message}"
            )
        print(json.dumps({"new_findings": len(active), "baseline": args.baseline}))
        return 1 if active else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

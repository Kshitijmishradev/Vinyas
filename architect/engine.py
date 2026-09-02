from __future__ import annotations

import hashlib
import os
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import date
from pathlib import Path

from architect.analyzers import (
    ParsedFile,
    analyzer_for,
    load_tsconfig_aliases,
    python_module_index,
    resolve_javascript,
    resolve_python,
)
from architect.config import ArchitectConfig, _matches, load_config
from architect.models import AnalysisGraph, DependencyEdge, FileMetrics, FileNode, Finding


class AnalysisCancelled(RuntimeError):
    pass


Progress = Callable[[int, str], None]
Cancelled = Callable[[], bool]


def analyze_repository(
    root: str | Path,
    config_path: str | Path | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> AnalysisGraph:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"repository does not exist: {root_path}")
    config = load_config(root_path, Path(config_path).resolve() if config_path else None)
    notify = progress or (lambda _value, _message: None)
    is_cancelled = cancelled or (lambda: False)

    paths = _discover(root_path, config)
    notify(5, f"Discovered {len(paths)} source files")
    parsed: dict[str, ParsedFile] = {}
    parse_findings: list[Finding] = []
    for index, absolute_path in enumerate(paths):
        if is_cancelled():
            raise AnalysisCancelled("analysis cancelled")
        relative = absolute_path.relative_to(root_path).as_posix()
        analyzer = analyzer_for(absolute_path)
        if not analyzer:
            continue
        try:
            source_text = absolute_path.read_text(encoding="utf-8", errors="replace")
            parsed[relative] = analyzer.parse(relative, source_text)
        except (OSError, SyntaxError) as exc:
            parse_findings.append(
                _finding("parse-error", "error", f"Could not parse {relative}: {exc}", relative)
            )
        notify(5 + int(35 * (index + 1) / max(len(paths), 1)), f"Parsed {relative}")

    python_index = python_module_index(parsed)
    known_paths = set(parsed)
    alias_base, aliases = load_tsconfig_aliases(root_path)
    edges: list[DependencyEdge] = []
    findings = list(parse_findings)
    unresolved = 0
    external = 0

    for index, parsed_file in enumerate(parsed.values()):
        if is_cancelled():
            raise AnalysisCancelled("analysis cancelled")
        for reference in parsed_file.imports:
            if parsed_file.language == "python":
                status, target, candidates = resolve_python(
                    parsed_file.path,
                    reference,
                    python_index,
                )
            else:
                status, target, candidates = resolve_javascript(
                    root_path,
                    parsed_file.path,
                    reference.specifier,
                    known_paths,
                    alias_base,
                    aliases,
                )
            if status == "resolved" and target and target != parsed_file.path:
                edges.append(
                    DependencyEdge(
                        parsed_file.path,
                        target,
                        reference.line,
                        reference.evidence[:300],
                        "python-module" if parsed_file.language == "python" else "js-module",
                    )
                )
            elif status in {"unresolved", "ambiguous"}:
                unresolved += 1
                suffix = f"; candidates: {', '.join(candidates)}" if candidates else ""
                findings.append(
                    _finding(
                        "ambiguous-import" if status == "ambiguous" else "unresolved-import",
                        "warning",
                        f"{status.title()} local import '{reference.specifier}'{suffix}",
                        parsed_file.path,
                        reference.line,
                        reference.evidence,
                    )
                )
            else:
                external += 1
        notify(
            40 + int(35 * (index + 1) / max(len(parsed), 1)),
            f"Resolved {parsed_file.path}",
        )

    edges = _dedupe_edges(edges)
    cycles = strongly_connected_cycles(list(parsed), edges)
    findings.extend(_governance_findings(parsed, edges, cycles, unresolved, config))
    _apply_suppressions(findings, config)
    metrics = _compute_metrics(parsed, edges, cycles)
    files = [
        FileNode(item.path, item.language, item.content_hash, item.symbols, metrics[item.path])
        for item in sorted(parsed.values(), key=lambda value: value.path)
    ]
    findings.sort(key=lambda item: (item.suppressed, item.severity, item.path, item.line, item.rule))
    notify(100, "Analysis complete")
    return AnalysisGraph(str(root_path), files, edges, findings, cycles, unresolved, external)


def _discover(root: Path, config: ArchitectConfig) -> list[Path]:
    result: list[Path] = []
    for current, directories, filenames in os.walk(root):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if not config.excluded((current_path / name).relative_to(root).as_posix())
        ]
        for name in filenames:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if analyzer_for(path) and config.included(relative):
                result.append(path)
    return sorted(result)


def _dedupe_edges(edges: list[DependencyEdge]) -> list[DependencyEdge]:
    unique = {edge.key: edge for edge in edges}
    return sorted(unique.values(), key=lambda item: (item.source, item.target, item.line))


def strongly_connected_cycles(nodes: list[str], edges: list[DependencyEdge]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    self_edges: set[str] = set()
    for edge in edges:
        adjacency[edge.source].append(edge.target)
        if edge.source == edge.target:
            self_edges.add(edge.source)

    index = 0
    stack: list[str] = []
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in adjacency[node]:
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component = []
            while stack:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in self_edges:
                components.append(sorted(component))

    for node in nodes:
        if node not in indices:
            visit(node)
    return sorted(components, key=lambda item: item[0])


def _governance_findings(
    parsed: dict[str, ParsedFile],
    edges: list[DependencyEdge],
    cycles: list[list[str]],
    unresolved: int,
    config: ArchitectConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    allowed_cycles = config.thresholds.get("cycles", 0)
    for cycle in cycles[allowed_cycles:]:
        findings.append(
            _finding("dependency-cycle", "error", f"Dependency cycle: {' → '.join(cycle)}", cycle[0])
        )

    fan_out: dict[str, set[str]] = defaultdict(set)
    cross_boundary = 0
    for edge in edges:
        fan_out[edge.source].add(edge.target)
        source_layer = config.layer_for(edge.source)
        target_layer = config.layer_for(edge.target)
        if source_layer and target_layer and source_layer != target_layer:
            cross_boundary += 1
            pair = (source_layer, target_layer)
            denied = pair in config.forbidden_dependencies
            not_allowed = bool(config.allowed_dependencies) and pair not in config.allowed_dependencies
            if denied or not_allowed:
                findings.append(
                    _finding(
                        "forbidden-dependency",
                        "error",
                        f"Layer '{source_layer}' must not depend on '{target_layer}'",
                        edge.source,
                        edge.line,
                        edge.evidence,
                    )
                )

    limit = config.thresholds.get("fan_out", 20)
    for path, targets in fan_out.items():
        if len(targets) > limit:
            findings.append(
                _finding("fan-out", "warning", f"Fan-out {len(targets)} exceeds limit {limit}", path)
            )

    unresolved_limit = config.thresholds.get("unresolved_imports", 0)
    if unresolved > unresolved_limit:
        findings.append(
            _finding(
                "unresolved-budget",
                "warning",
                f"Unresolved imports {unresolved} exceed limit {unresolved_limit}",
            )
        )
    cross_limit = config.thresholds.get("cross_boundary", 0)
    if config.layers and cross_boundary > cross_limit:
        findings.append(
            _finding(
                "cross-boundary-budget",
                "warning",
                f"Cross-boundary dependencies {cross_boundary} exceed limit {cross_limit}",
            )
        )
    return findings


def _compute_metrics(
    parsed: dict[str, ParsedFile], edges: list[DependencyEdge], cycles: list[list[str]]
) -> dict[str, FileMetrics]:
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        outgoing[edge.source].add(edge.target)
        incoming[edge.target].add(edge.source)
        adjacency[edge.source].add(edge.target)
    cycle_count: dict[str, int] = defaultdict(int)
    for cycle in cycles:
        for path in cycle:
            cycle_count[path] += 1

    def depth(start: str) -> int:
        queue = deque([(start, 0)])
        best = 0
        seen = {start}
        while queue:
            node, level = queue.popleft()
            best = max(best, level)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, level + 1))
        return best

    return {
        path: FileMetrics(
            fan_in=len(incoming[path]),
            fan_out=len(outgoing[path]),
            symbol_count=len(item.symbols),
            dependency_depth=depth(path),
            cycle_participation=cycle_count[path],
        )
        for path, item in parsed.items()
    }


def _apply_suppressions(findings: list[Finding], config: ArchitectConfig) -> None:
    today = date.today()
    for finding in findings:
        for suppression in config.suppressions:
            if suppression.rule != finding.rule or not _matches(finding.path, suppression.path):
                continue
            if suppression.expires and suppression.expires < today:
                continue
            finding.suppressed = True
            finding.suppression_reason = suppression.reason
            break


def _finding(
    rule: str,
    severity: str,
    message: str,
    path: str = "",
    line: int = 1,
    evidence: str = "",
) -> Finding:
    stable_message = message.split("; candidates:", 1)[0]
    raw = f"{rule}\0{path}\0{line}\0{stable_message}"
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:20]
    return Finding(fingerprint, rule, severity, message, path, line, evidence)

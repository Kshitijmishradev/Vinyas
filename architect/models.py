from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Symbol:
    name: str
    kind: str
    line: int


@dataclass(slots=True)
class FileMetrics:
    fan_in: int = 0
    fan_out: int = 0
    symbol_count: int = 0
    dependency_depth: int = 0
    cycle_participation: int = 0


@dataclass(slots=True)
class FileNode:
    path: str
    language: str
    content_hash: str
    symbols: list[Symbol] = field(default_factory=list)
    metrics: FileMetrics = field(default_factory=FileMetrics)


@dataclass(slots=True)
class DependencyEdge:
    source: str
    target: str
    line: int
    evidence: str
    resolution: str
    confidence: str = "exact"

    @property
    def key(self) -> str:
        return f"{self.source}:{self.line}->{self.target}"


@dataclass(slots=True)
class Finding:
    fingerprint: str
    rule: str
    severity: str
    message: str
    path: str = ""
    line: int = 1
    evidence: str = ""
    suppressed: bool = False
    suppression_reason: str = ""


@dataclass(slots=True)
class AnalysisGraph:
    root: str
    files: list[FileNode]
    edges: list[DependencyEdge]
    findings: list[Finding]
    cycles: list[list[str]]
    unresolved_count: int
    external_count: int
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = {
            "files": len(self.files),
            "dependencies": len(self.edges),
            "findings": sum(not finding.suppressed for finding in self.findings),
            "suppressed": sum(finding.suppressed for finding in self.findings),
            "cycles": len(self.cycles),
            "unresolved": self.unresolved_count,
            "external": self.external_count,
        }
        return payload


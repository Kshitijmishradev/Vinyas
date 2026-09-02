from __future__ import annotations

import json
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from architect.engine import analyze_repository
from architect.models import AnalysisGraph


def active_fingerprints(graph_or_payload: AnalysisGraph | dict[str, Any]) -> set[str]:
    findings = graph_or_payload.findings if isinstance(graph_or_payload, AnalysisGraph) else graph_or_payload.get("findings", [])
    result = set()
    for finding in findings:
        if isinstance(finding, dict):
            if not finding.get("suppressed"):
                result.add(str(finding["fingerprint"]))
        elif not finding.suppressed:
            result.add(finding.fingerprint)
    return result


def load_baseline(root: Path, baseline: str) -> dict[str, Any]:
    candidate = Path(baseline)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="architect-baseline-") as directory:
        archive = Path(directory) / "repo.tar"
        completed = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", "-o", str(archive), baseline], capture_output=True, text=True, check=False)
        if completed.returncode:
            raise ValueError(f"cannot read baseline '{baseline}'; fetch it or provide a report file: {completed.stderr.strip()}")
        checkout = Path(directory) / "checkout"
        checkout.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(checkout, filter="data")
        return analyze_repository(checkout).to_dict()

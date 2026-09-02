from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from architect.baseline import active_fingerprints
from architect.engine import analyze_repository
from architect.reports import html_report, sarif_report


class GovernanceAndReportTests(unittest.TestCase):
    def test_governance_suppression_and_explicit_metrics(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed in the lightweight development environment")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "api/handler.py", "from core import domain\n")
            self.write(root, "core/domain.py", "VALUE = 1\n")
            self.write(root, "architect.yaml", """
layers:
  - name: api
    match: ["api/**"]
  - name: core
    match: ["core/**"]
forbidden_dependencies:
  - from: api
    to: core
thresholds:
  cross_boundary: 5
suppressions:
  - rule: forbidden-dependency
    path: "api/**"
    reason: "Approved adapter"
    expires: 2099-01-01
""")
            graph = analyze_repository(root)
            finding = next(item for item in graph.findings if item.rule == "forbidden-dependency")
            self.assertTrue(finding.suppressed)
            self.assertEqual("Approved adapter", finding.suppression_reason)

    def test_dependency_allow_list_denies_unlisted_layer_edges(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed in the lightweight development environment")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "api/handler.py", "from core import domain\n")
            self.write(root, "core/domain.py", "VALUE = 1\n")
            self.write(
                root,
                "architect.yaml",
                """
layers:
  - { name: api, match: ["api/**"] }
  - { name: core, match: ["core/**"] }
allowed_dependencies:
  - { from: core, to: api }
thresholds: { cross_boundary: 5 }
""",
            )
            graph = analyze_repository(root)
            self.assertTrue(
                any(item.rule == "forbidden-dependency" for item in graph.findings)
            )

    def test_json_sarif_html_and_baseline_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "pkg.py", "from . import missing\n")
            graph = analyze_repository(root)
            sarif = json.loads(sarif_report(graph))
            self.assertEqual("2.1.0", sarif["version"])
            self.assertIn("Architect Pro", html_report(graph))
            current = active_fingerprints(graph)
            payload = graph.to_dict()
            payload["findings"] = []
            self.assertEqual(current, current - active_fingerprints(payload))

    @staticmethod
    def write(root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

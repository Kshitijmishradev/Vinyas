from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from architect.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_vinyas_is_the_primary_cli_name(self) -> None:
        self.assertEqual("vinyas", build_parser().prog)

    def test_baseline_gate_fails_only_for_new_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            baseline = root / "baseline.json"
            self.assertEqual(0, main(["analyze", str(root), "--output", str(baseline)]))
            source.write_text("from . import missing\n", encoding="utf-8")
            self.assertEqual(1, main(["check", str(root), "--baseline", str(baseline)]))

            current = root / "current.json"
            self.assertEqual(0, main(["analyze", str(root), "--output", str(current)]))
            self.assertEqual(0, main(["check", str(root), "--baseline", str(current)]))
            self.assertGreater(len(json.loads(current.read_text())["findings"]), 0)


if __name__ == "__main__":
    unittest.main()

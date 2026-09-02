from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from architect.engine import analyze_repository, strongly_connected_cycles
from architect.models import DependencyEdge


class EngineTests(unittest.TestCase):
    def test_python_resolution_cycles_and_isolated_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "pkg/__init__.py", "from . import service\n")
            self.write(root, "pkg/service.py", "from . import model\n\ndef run(): pass\n")
            self.write(root, "pkg/model.py", "from . import service\n\nclass Model: pass\n")
            self.write(root, "isolated.py", "VALUE = 1\n")
            graph = analyze_repository(root)

            self.assertEqual(4, len(graph.files), "isolated files must remain in the graph")
            edge_pairs = {(edge.source, edge.target) for edge in graph.edges}
            self.assertIn(("pkg/service.py", "pkg/model.py"), edge_pairs)
            self.assertIn(("pkg/model.py", "pkg/service.py"), edge_pairs)
            self.assertEqual([["pkg/model.py", "pkg/service.py"]], graph.cycles)
            service = next(item for item in graph.files if item.path == "pkg/service.py")
            self.assertEqual(1, service.metrics.cycle_participation)
            self.assertEqual(1, service.metrics.symbol_count)

    def test_js_ts_tsx_and_tsconfig_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "tsconfig.json", '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}')
            self.write(root, "src/App.tsx", "import { util } from '@/lib/util'\nexport const App = () => util()\n")
            self.write(root, "src/lib/util.ts", "export function util() { return 1 }\n")
            self.write(root, "src/style.css", "body {}\n")
            self.write(root, "src/main.ts", "import './style.css'\nimport { App } from './App'\nApp()\n")
            graph = analyze_repository(root)

            pairs = {(edge.source, edge.target) for edge in graph.edges}
            self.assertIn(("src/App.tsx", "src/lib/util.ts"), pairs)
            self.assertIn(("src/main.ts", "src/App.tsx"), pairs)
            self.assertFalse(any("style.css" in finding.message for finding in graph.findings))

    def test_ambiguous_import_never_creates_guessed_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "thing.py", "VALUE = 1\n")
            self.write(root, "thing/__init__.py", "VALUE = 2\n")
            self.write(root, "consumer.py", "import thing\n")
            graph = analyze_repository(root)

            self.assertFalse(any(edge.source == "consumer.py" for edge in graph.edges))
            ambiguous = [item for item in graph.findings if item.rule == "ambiguous-import"]
            self.assertEqual(1, len(ambiguous))
            self.assertIn("thing.py", ambiguous[0].message)
            self.assertIn("thing/__init__.py", ambiguous[0].message)

    def test_nested_dependency_and_build_directories_are_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, "src/app.ts", "export const app = 1\n")
            self.write(root, "frontend/node_modules/pkg/index.ts", "export const vendor = 1\n")
            self.write(root, "frontend/dist/bundle.js", "export const built = 1\n")
            graph = analyze_repository(root)
            self.assertEqual(["src/app.ts"], [item.path for item in graph.files])

    def test_tarjan_returns_every_cycle(self) -> None:
        def edge(source: str, target: str) -> DependencyEdge:
            return DependencyEdge(source, target, 1, "", "test")
        cycles = strongly_connected_cycles(
            ["a", "b", "c", "d", "e"],
            [edge("a", "b"), edge("b", "a"), edge("c", "d"), edge("d", "c")],
        )
        self.assertEqual([["a", "b"], ["c", "d"]], cycles)

    @staticmethod
    def write(root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

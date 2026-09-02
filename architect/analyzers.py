from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from architect.models import Symbol

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


@dataclass(slots=True)
class ImportReference:
    specifier: str
    line: int
    evidence: str
    language: str
    relative_level: int = 0
    imported_names: tuple[str, ...] = ()


@dataclass(slots=True)
class ParsedFile:
    path: str
    language: str
    content_hash: str
    symbols: list[Symbol]
    imports: list[ImportReference]


class PythonAnalyzer:
    language = "python"

    def parse(self, relative_path: str, source: str) -> ParsedFile:
        tree = ast.parse(source, filename=relative_path)
        lines = source.splitlines()
        symbols: list[Symbol] = []
        imports: list[ImportReference] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                symbols.append(Symbol(node.name, kind, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportReference(
                            alias.name,
                            node.lineno,
                            _line(lines, node.lineno),
                            self.language,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                imports.append(
                    ImportReference(
                        node.module or "",
                        node.lineno,
                        _line(lines, node.lineno),
                        self.language,
                        node.level,
                        tuple(alias.name for alias in node.names if alias.name != "*"),
                    )
                )
        return ParsedFile(
            path=relative_path,
            language=self.language,
            content_hash=_hash(source),
            symbols=sorted(symbols, key=lambda item: (item.line, item.name)),
            imports=sorted(imports, key=lambda item: item.line),
        )


JS_IMPORT_PATTERNS = [
    re.compile(r"(?:import|export)\s+(?:[^;]*?\s+from\s+)?[\"']([^\"']+)[\"']"),
    re.compile(r"(?:require|import)\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
]
JS_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:(class)\s+([A-Za-z_$][\w$]*)|"
    r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|"
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)"
)


class JavaScriptAnalyzer:
    language = "typescript"

    def parse(self, relative_path: str, source: str) -> ParsedFile:
        suffix = Path(relative_path).suffix
        language = "typescript" if suffix in {".ts", ".tsx"} else "javascript"
        imports: list[ImportReference] = []
        symbols: list[Symbol] = []
        for number, line in enumerate(source.splitlines(), start=1):
            for pattern in JS_IMPORT_PATTERNS:
                for match in pattern.finditer(line):
                    imports.append(ImportReference(match.group(1), number, line.strip(), language))
            symbol_match = JS_SYMBOL_PATTERN.match(line)
            if symbol_match:
                if symbol_match.group(1):
                    symbols.append(Symbol(symbol_match.group(2), "class", number))
                else:
                    symbols.append(Symbol(symbol_match.group(3) or symbol_match.group(4), "function", number))
        unique = {(item.specifier, item.line): item for item in imports}
        return ParsedFile(
            path=relative_path,
            language=language,
            content_hash=_hash(source),
            symbols=symbols,
            imports=sorted(unique.values(), key=lambda item: item.line),
        )


def analyzer_for(path: Path) -> PythonAnalyzer | JavaScriptAnalyzer | None:
    if path.suffix == ".py":
        return PythonAnalyzer()
    if path.suffix in JS_EXTENSIONS:
        return JavaScriptAnalyzer()
    return None


def python_module_index(paths: Iterable[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in paths:
        file_path = Path(path)
        if file_path.suffix != ".py":
            continue
        parts = list(file_path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        if module:
            index.setdefault(module, []).append(path)
    return index


def resolve_python(
    source_path: str,
    reference: ImportReference,
    index: dict[str, list[str]],
) -> tuple[str, str | None, list[str]]:
    source_parts = list(Path(source_path).with_suffix("").parts)
    package = source_parts[:-1]
    if Path(source_path).name == "__init__.py":
        package = source_parts[:-1]

    prefix: list[str] = []
    if reference.relative_level:
        remove = max(reference.relative_level - 1, 0)
        prefix = package[: max(0, len(package) - remove)]

    module_parts = [part for part in reference.specifier.split(".") if part]
    base = ".".join(prefix + module_parts) if reference.relative_level else reference.specifier
    primary = index.get(base, []) if reference.specifier else []
    if len(primary) == 1:
        return "resolved", primary[0], list(primary)
    if len(primary) > 1:
        return "ambiguous", None, sorted(primary)

    child_candidates = [
        f"{base}.{name}" if base else ".".join(prefix + [name])
        for name in reference.imported_names
    ]
    matches: list[str] = []
    for candidate in child_candidates:
        matches.extend(index.get(candidate, []))
    matches = sorted(set(matches))
    if len(matches) == 1:
        return "resolved", matches[0], matches
    if len(matches) > 1:
        return "ambiguous", None, matches

    top = (base or reference.specifier).split(".", 1)[0]
    is_local = bool(reference.relative_level) or any(key.split(".", 1)[0] == top for key in index)
    return ("unresolved" if is_local else "external"), None, []


def load_tsconfig_aliases(root: Path) -> tuple[Path, dict[str, list[str]]]:
    path = root / "tsconfig.json"
    if not path.exists():
        return root, {}
    try:
        raw = re.sub(r"//.*?$|/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.M | re.S)
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return root, {}
    options = data.get("compilerOptions", {})
    base = (root / options.get("baseUrl", ".")).resolve()
    aliases = {str(key): [str(item) for item in value] for key, value in options.get("paths", {}).items()}
    return base, aliases


def resolve_javascript(
    root: Path,
    source_path: str,
    specifier: str,
    known_paths: set[str],
    alias_base: Path,
    aliases: dict[str, list[str]],
) -> tuple[str, str | None, list[str]]:
    bases: list[Path] = []
    source_absolute = root / source_path
    if specifier.startswith("."):
        bases.append((source_absolute.parent / specifier).resolve())
    else:
        for pattern, replacements in aliases.items():
            wildcard = "*" in pattern
            prefix, _, suffix = pattern.partition("*")
            if (wildcard and specifier.startswith(prefix) and specifier.endswith(suffix)) or specifier == pattern:
                middle = specifier[len(prefix) : len(specifier) - len(suffix) if suffix else None]
                for replacement in replacements:
                    bases.append((alias_base / replacement.replace("*", middle)).resolve())

    matches: set[str] = set()
    for base in bases:
        candidates = [base]
        if not base.suffix:
            candidates.extend(base.with_suffix(extension) for extension in JS_EXTENSIONS)
            candidates.extend(base / f"index{extension}" for extension in JS_EXTENSIONS)
        for candidate in candidates:
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            if relative in known_paths:
                matches.add(relative)

    ordered = sorted(matches)
    if len(ordered) == 1:
        return "resolved", ordered[0], ordered
    if len(ordered) > 1:
        return "ambiguous", None, ordered
    if specifier.startswith("."):
        asset = (source_absolute.parent / specifier).resolve()
        if asset.is_file() and asset.suffix not in JS_EXTENSIONS:
            return "external", None, []
    return ("unresolved" if bases else "external"), None, []


def _line(lines: list[str], number: int) -> str:
    return lines[number - 1].strip() if 0 < number <= len(lines) else ""


def _hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()

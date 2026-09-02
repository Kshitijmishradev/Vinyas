from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDES = [
    "**/.git/**",
    "**/.venv/**",
    "**/venv/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
]


@dataclass(slots=True)
class Layer:
    name: str
    match: list[str]


@dataclass(slots=True)
class Suppression:
    rule: str
    path: str
    reason: str
    expires: date | None = None


@dataclass(slots=True)
class ArchitectConfig:
    include: list[str] = field(default_factory=lambda: ["**/*"])
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    layers: list[Layer] = field(default_factory=list)
    allowed_dependencies: list[tuple[str, str]] = field(default_factory=list)
    forbidden_dependencies: list[tuple[str, str]] = field(default_factory=list)
    thresholds: dict[str, int] = field(
        default_factory=lambda: {
            "cycles": 0,
            "fan_out": 20,
            "unresolved_imports": 0,
            "cross_boundary": 0,
        }
    )
    suppressions: list[Suppression] = field(default_factory=list)

    def included(self, relative_path: str) -> bool:
        path = relative_path.replace("\\", "/")
        included = any(_matches(path, pattern) for pattern in self.include)
        excluded = any(_matches(path, pattern) for pattern in self.exclude)
        return included and not excluded

    def excluded(self, relative_path: str) -> bool:
        path = relative_path.replace("\\", "/")
        return any(_matches(path, pattern) for pattern in self.exclude)

    def layer_for(self, path: str) -> str | None:
        for layer in self.layers:
            if any(_matches(path, pattern) for pattern in layer.match):
                return layer.name
        return None


def _matches(path: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/")
    patterns = {normalized, normalized.removeprefix("**/")}
    for candidate in patterns:
        if fnmatch.fnmatch(path, candidate):
            return True
        if candidate.endswith("/**") and fnmatch.fnmatch(path, candidate[:-3].rstrip("/")):
            return True
    return False


def _as_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("include/exclude values must be lists of strings")
    return value


def load_config(root: Path, config_path: Path | None = None) -> ArchitectConfig:
    path = config_path or root / "vinyas.yaml"
    legacy_path = root / "architect.yaml"
    if config_path is None and not path.exists() and legacy_path.exists():
        path = legacy_path
    if not path.exists():
        return ArchitectConfig()
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(f"PyYAML is required when {path.name} is present; install vinyas") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a mapping")

    layers = []
    for item in data.get("layers", []):
        layers.append(Layer(name=str(item["name"]), match=_as_list(item.get("match"), [])))

    def dependency_pairs(key: str) -> list[tuple[str, str]]:
        return [(str(item["from"]), str(item["to"])) for item in data.get(key, [])]

    suppressions = []
    for item in data.get("suppressions", []):
        expires = date.fromisoformat(str(item["expires"])) if item.get("expires") else None
        suppressions.append(
            Suppression(
                rule=str(item["rule"]),
                path=str(item.get("path", "**/*")),
                reason=str(item["reason"]),
                expires=expires,
            )
        )

    thresholds = ArchitectConfig().thresholds
    thresholds.update({key: int(value) for key, value in data.get("thresholds", {}).items()})
    return ArchitectConfig(
        include=_as_list(data.get("include"), ["**/*"]),
        exclude=_as_list(data.get("exclude"), DEFAULT_EXCLUDES),
        layers=layers,
        allowed_dependencies=dependency_pairs("allowed_dependencies"),
        forbidden_dependencies=dependency_pairs("forbidden_dependencies"),
        thresholds=thresholds,
        suppressions=suppressions,
    )

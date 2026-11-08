"""Modules activables : chaque module déclare un manifeste TOML, chargé
uniquement s'il figure dans `[modules] enabled` de `deedbook.toml`."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    permissions: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    menu: list[str] = field(default_factory=list)


def load_manifest(path: Path) -> ModuleManifest:
    """Charge et valide un manifeste de module (fichier TOML)."""
    with path.open("rb") as f:
        data = tomllib.load(f)

    module = data.get("module")
    if not isinstance(module, dict) or not module.get("name"):
        raise ValueError(f"Manifeste invalide : {path} (section [module] avec name requise)")

    return ModuleManifest(
        name=str(module["name"]),
        permissions=[str(p) for p in module.get("permissions", [])],
        functions=[str(fn) for fn in module.get("functions", [])],
        menu=[str(m) for m in module.get("menu", [])],
    )


def load_modules(directory: Path, enabled: list[str]) -> list[ModuleManifest]:
    """Charge uniquement les modules listés dans `enabled`."""
    manifests = []
    for name in enabled:
        path = directory / name / "module.toml"
        if not path.exists():
            raise FileNotFoundError(f"Module activé mais introuvable : {path}")
        manifests.append(load_manifest(path))
    return manifests

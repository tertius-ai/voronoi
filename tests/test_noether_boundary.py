"""Keep Voronoi on Noether's public typed domain surface."""

from __future__ import annotations

import ast
from pathlib import Path


def test_voronoi_never_imports_private_or_legacy_noether_namespaces() -> None:
    source_root = Path(__file__).parent.parent / "src" / "voronoi"
    forbidden: list[tuple[Path, int, str]] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "noether.api" or name.startswith(
                    ("noether.api.", "noether._")
                ):
                    forbidden.append((path, node.lineno, name))

    assert forbidden == []

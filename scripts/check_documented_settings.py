from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import BaseModel

from hansard.config import Settings

ENVIRONMENT_PATTERN = re.compile(r"HANSARD_[A-Z0-9_]*[A-Z0-9]")
PREFIX = "HANSARD_"
NESTING = "__"


def known_variables(model: type[BaseModel], prefix: str = PREFIX) -> set[str]:
    names: set[str] = set()
    for field, info in model.model_fields.items():
        annotation = info.annotation
        variable = f"{prefix}{field.upper()}"
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            names |= known_variables(annotation, f"{variable}{NESTING}")
        else:
            names.add(variable)
    return names


def documented_variables(paths: list[Path]) -> dict[str, set[Path]]:
    found: dict[str, set[Path]] = {}
    for path in paths:
        for match in ENVIRONMENT_PATTERN.findall(path.read_text(encoding="utf-8")):
            found.setdefault(match, set()).add(path)
    return found


def main(roots: list[str]) -> int:
    known = known_variables(Settings)
    sources: list[Path] = []
    for root in roots:
        candidate = Path(root)
        sources.extend(sorted(candidate.rglob("*.md")) if candidate.is_dir() else [candidate])
    documented = documented_variables(sources)
    prefixes = {name.rsplit(NESTING, index)[0] for name in known for index in (1, 2) if NESTING in name}
    prefixes |= {name.split(NESTING)[0] for name in known}
    unknown = {
        name: places for name, places in documented.items() if name not in known and name not in prefixes
    }
    if unknown:
        print("Documentation refers to settings that do not exist in hansard.config:\n")
        for name, places in sorted(unknown.items()):
            locations = ", ".join(sorted(str(place) for place in places))
            print(f"  {name}  ({locations})")
        print(f"\n{len(unknown)} undocumented-but-referenced settings")
        return 1
    undocumented = sorted(known - set(documented))
    print(f"{len(documented)} documented settings, all real")
    if undocumented:
        print(f"{len(undocumented)} settings carry no documentation yet:")
        for name in undocumented[:40]:
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["docs", ".env.example", "README.md"]))

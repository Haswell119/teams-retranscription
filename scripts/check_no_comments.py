from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

ALLOWED_PREFIXES = ("#!/", "# -*- coding")


def comment_lines(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        text = token.string.strip()
        if text.startswith(ALLOWED_PREFIXES) or text.startswith("# noqa") or text.startswith("# type:"):
            continue
        found.append((token.start[0], text))
    return found


def docstring_lines(source: str) -> list[int]:
    tree = ast.parse(source)
    found: list[int] = []
    for node in ast.walk(tree):
        documented = isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        if documented and ast.get_docstring(node) is not None and node.body:
            found.append(node.body[0].lineno)
    return found


def main(roots: list[str]) -> int:
    failures: list[str] = []
    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for line, text in comment_lines(source):
                failures.append(f"{path}:{line}: comment: {text[:70]}")
            for line in docstring_lines(source):
                failures.append(f"{path}:{line}: docstring")
    if failures:
        print("This project keeps explanation in docs/, not in the code.")
        print("Remove these, or move what they say into the documentation:\n")
        for failure in failures[:80]:
            print(f"  {failure}")
        print(f"\n{len(failures)} violations")
        return 1
    print("no comments, no docstrings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["src/hansard"]))

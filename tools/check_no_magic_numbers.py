#!/usr/bin/env python3
"""Fail if a bare numeric literal appears in the tuned layers.

`app/arbitration/` and `app/decision/points/` are the two places where a number is a *decision*:
a velocity threshold, a dwell window, a confidence gate. Those belong in config/default.toml and
config/judgment/points.yaml, where a human reviews them and where per-user calibration and Jev
point F's threshold tuning can rewrite them.

A literal that sneaks into code is a threshold nobody can see and calibration cannot reach. This
check is what makes "no magic numbers" a property of the build rather than a habit.

Allowed: 0, 1, -1 (identity, empty, last-index).

A line may also carry `# tuning-exempt: <reason>` for a number that genuinely is not a tuning
constant — a cache size, a rounding precision. The pragma requires a reason so the exemption is
visible at the site and in review, rather than being a silent hole in the rule.

Run: python tools/check_no_magic_numbers.py [paths...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ("app/arbitration", "app/decision/points")
ALLOWED = {0, 1, -1}


EXEMPT_PRAGMA = "# tuning-exempt:"


class Checker(ast.NodeVisitor):
    def __init__(self, path: Path, exempt_lines: frozenset[int] = frozenset()) -> None:
        self.path = path
        self.exempt_lines = exempt_lines
        self.violations: list[tuple[int, str]] = []
        self._exempt: set[int] = set()  # id() of Constant nodes covered by a unary minus

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
            value = node.operand.value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self._exempt.add(id(node.operand))
                if -value not in ALLOWED and node.lineno not in self.exempt_lines:
                    self.violations.append((node.lineno, repr(-value)))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if id(node) in self._exempt:
            return
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        if value in ALLOWED or node.lineno in self.exempt_lines:
            return
        self.violations.append((node.lineno, repr(value)))


def check_file(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [f"{path}:{e.lineno}: syntax error: {e.msg}"]
    exempt = frozenset(
        i for i, line in enumerate(source.splitlines(), 1) if EXEMPT_PRAGMA in line
    )
    c = Checker(path, exempt)
    c.visit(tree)
    try:
        rel = path.relative_to(REPO_ROOT)
    except ValueError:
        rel = path  # a path outside the repo (tests pass tmp_path); report it verbatim
    return [
        f"{rel}:{line}: bare numeric literal {value} — move it to config/"
        for line, value in sorted(c.violations)
    ]


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv[1:]] or [REPO_ROOT / t for t in DEFAULT_TARGETS]
    problems: list[str] = []
    checked = 0
    for target in targets:
        files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
        for f in files:
            if f.name == "__init__.py" and f.stat().st_size == 0:
                continue
            checked += 1
            problems.extend(check_file(f))

    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"\n{len(problems)} magic number(s) in {checked} file(s)", file=sys.stderr)
        return 1
    print(f"no magic numbers in {checked} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Parse engine solution (.SOL) files: XML with a history of <val> per <var>."""
from __future__ import annotations

import re

_VAR_RE = re.compile(r"<var>\s*<name>\s*(.*?)\s*</name>(.*?)</var>", re.S)
_VAL_RE = re.compile(r"<val>\s*([-\d.eE+]+)\s*</val>")


def parse_sol(path: str, names: set[str] | None = None,
              last_only: bool = True) -> dict[str, float | list[float]]:
    """Read a .SOL file. names filters by exact (case-insensitive) variable names;
    last_only returns the current value, otherwise the full history."""
    text = open(path, "r", errors="replace").read()
    out: dict[str, float | list[float]] = {}
    for m in _VAR_RE.finditer(text):
        name = m.group(1)
        if names is not None and name.lower() not in names:
            continue
        vals = [float(v) for v in _VAL_RE.findall(m.group(2))]
        if vals:
            out[name] = vals[-1] if last_only else vals
    return out

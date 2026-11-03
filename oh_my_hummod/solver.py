"""Parse engine data exports: HumMod .SOL (XML) and QCP .ICS (text key-value)."""
from __future__ import annotations

import re

_VAR_RE = re.compile(r"<var>\s*<name>\s*(.*?)\s*</name>(.*?)</var>", re.S)
_VAL_RE = re.compile(r"<val>\s*([-\d.eE+]+)\s*</val>")
_ICS_RE = re.compile(r'\{\s*VAR\s+"([^"]+)"\s+([-\d.eE+]+)\s*\}')


def parse_sol(path: str, names: set[str] | None = None,
              last_only: bool = True) -> dict[str, float | list[float]]:
    """Read a HumMod .SOL file. names filters by exact (case-insensitive) variable
    names; last_only returns the current value, otherwise the full history."""
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


def parse_ics(path: str, names: set[str] | None = None) -> dict[str, float]:
    """Read a QCP .ICS file ({ VAR "Name" value } lines)."""
    text = open(path, "r", errors="replace").read()
    out: dict[str, float] = {}
    for m in _ICS_RE.finditer(text):
        name = m.group(1)
        if names is not None and name.lower() not in names:
            continue
        out[name] = float(m.group(2))
    return out


def parse_export(path: str, names: set[str] | None = None) -> dict[str, float]:
    """Auto-detect SOL vs ICS by file head."""
    head = open(path, "rb").read(256)
    up = head.upper()
    if head.lstrip().startswith(b"{") or b"{ VAR" in up or b"{ NOTE" in up:
        return parse_ics(path, names)
    return parse_sol(path, names)

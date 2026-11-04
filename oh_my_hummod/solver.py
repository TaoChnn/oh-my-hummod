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


def parse_sol_history(path: str, names: set[str], max_points: int = 500) -> dict:
    """Time series from a .SOL export.

    The time axis is the history of System.X (simulation minutes). Every
    requested variable is returned as a series sampled at those times,
    uniformly downsampled to at most `max_points` points.

    Returns {"points", "stride", "t": [...], "series": {name: [...]}}.
    """
    text = open(path, "r", errors="replace").read()
    series: dict[str, list[float]] = {}
    want = {n.lower() for n in names} | {"system.x"}
    for m in _VAR_RE.finditer(text):
        name = m.group(1)
        if name.lower() not in want:
            continue
        vals = [float(v) for v in _VAL_RE.findall(m.group(2))]
        if vals:
            series[name] = vals

    t_key = next((k for k in series if k.lower() == "system.x"), None)
    if t_key is None:
        raise KeyError("System.X not found in SOL - no time axis")
    t = series.pop(t_key)

    n = min([len(t)] + [len(v) for v in series.values()])
    t, dropped = t[:n], {k: v[:n] for k, v in series.items()}
    stride = max(1, -(-n // max(1, max_points)))
    keep = list(range(0, n, stride))
    if keep and keep[-1] != n - 1:
        keep.append(n - 1)  # always include the latest sample
        if len(keep) > max(1, max_points):
            del keep[-2]     # drop a middle sample to honour the cap

    # The time axis is popped out of `dropped` above, but a caller that asked
    # for it (System.X) did get its data back - as `t`. Do not report it missing.
    missing = [w for w in names
               if w.lower() not in {k.lower() for k in dropped}
               and w.lower() != t_key.lower()]
    return {"points": len(keep), "stride": stride,
            "t": [t[i] for i in keep],
            "series": {k: [v[i] for i in keep] for k, v in dropped.items()},
            "missing": missing}

# Regression tests for profile detection.
#
# Field bug (R1, HumMod 1.6.1 exercise trial): hummod_start misdetected the
# 1.6.1 engine as hummod_3.0.4. Root cause: during process startup the 1.6.1
# menu tree populates progressively and the detection loop caught a partial
# menu that matched the 3.0.4 branch ("Trauma"/"Sizing" check) - neither label
# exists anywhere in the bound 1.6.1 model - and the wrong profile stayed
# cached for the process lifetime.
# Fix: _profile_from_engine_dir() reads the engine folder's VERSION file
# (shipped by the 1.6.1 standalone; absent in engine304/QCP/AVP/BAT dirs) and
# takes precedence over live-menu detection.
import asyncio
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

from oh_my_hummod.profile import Profile            # noqa: E402
from oh_my_hummod.server import _detect_profile, _profile_from_engine_dir  # noqa: E402


def test_version_file_wins_over_menu():
    """A VERSION file pins the profile even when the menu is wrong/partial."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "VERSION"), "w") as f:
            f.write('VERSION="1.6.1"\n')

        class FakeBridge:
            engine_dir = d

            def menu_tree(self):  # would mislead: pretend a partial 3.0.4-like menu
                raise AssertionError("menu_tree must not be consulted when VERSION matches a profile")

        p = _detect_profile(FakeBridge())
    assert p.name == "hummod_1.6.1", f"expected hummod_1.6.1 from VERSION, got {p.name}"
    assert p.bind_marker == "Startup"
    print("  OK  VERSION file pins hummod_1.6.1 without touching the menu")


def test_version_parsing(tmpdir):
    d = str(tmpdir)
    # 1.6.1 ships VERSION="1.6.1" (with quotes)
    with open(os.path.join(d, "VERSION"), "w") as f:
        f.write('VERSION="1.6.1"\n')
    p = _profile_from_engine_dir(d)
    assert p is not None and p.name == "hummod_1.6.1", "quoted VERSION not parsed"
    print("  OK  quoted VERSION parsed ->", p.name)

    # no VERSION file -> None (menu detection takes over; engine304 has none)
    empty = os.path.join(d, "empty")
    os.mkdir(empty)
    assert _profile_from_engine_dir(empty) is None, "missing VERSION must yield None"
    print("  OK  missing VERSION -> None (menu fallback)")

    # VERSION with an unknown build -> None, not a crash
    unk = os.path.join(d, "unknown")
    os.mkdir(unk)
    with open(os.path.join(unk, "VERSION"), "w") as f:
        f.write('VERSION="9.9.9"\n')
    assert _profile_from_engine_dir(unk) is None, "unknown version must yield None"
    print("  OK  unknown VERSION -> None (menu fallback)")


def test_builtin_profiles_load():
    for name in ("hummod_1.6.1", "hummod_3.0.4", "qcp_2005"):
        p = Profile.load(name)
        assert p.name == name
    print("  OK  builtin profiles load")


def test_e2e_engine_copy():
    """Live check against a disposable copy of the 1.6.1 engine (if present):
    hummod_start must report profile hummod_1.6.1, and an Exercise page must
    respond - the exact field scenario that used to misdetect."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    copy_dir = r"C:/path/to\engine_test_copies\r1_161"
    if not os.path.isdir(copy_dir):
        print("  SKIP  no engine copy at", copy_dir)
        return

    server = os.path.join(ROOT, "oh_my_hummod", "server.py")
    outdir = r"C:/path/to/out\profile_detection"
    os.makedirs(outdir, exist_ok=True)

    async def run():
        env = dict(os.environ)
        env["HUMMOD_ENGINE_DIR"] = copy_dir
        env["HUMMOD_OUTDIR"] = outdir
        async with stdio_client(StdioServerParameters(command=sys.executable, args=[server], env=env)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                async def call(name, args=None):
                    res = await s.call_tool(name, args or {})
                    return " | ".join(c.text for c in res.content if getattr(c, "text", None))

                out = await call("hummod_start")
                print("   [start]", out[:160])
                assert "hummod_1.6.1" in out, "engine copy still misdetected: " + out
                import json as _json
                pid = _json.loads(out[out.index("{"):])["pid"]
                out = await call("hummod_navigate", {"panel_path": "Lifestyle/Exercise/Control"})
                assert '"ok": true' in out, "Exercise Control page unreachable: " + out
                out = await call("hummod_snapshot", {"name": "profile_detect_probe",
                                                     "vars": ["Exercise-Control.Request"]})
                assert '"Exercise-Control.Request"' in out, "model vars unreadable: " + out
                print("  OK  engine copy starts as hummod_1.6.1 and answers on Exercise pages")
                # cleanup: the engine copy is disposable, don't leave it running
                os.system(f"taskkill /PID {pid} /F >nul 2>&1")

    asyncio.run(run())


if __name__ == "__main__":
    test_version_file_wins_over_menu()
    with tempfile.TemporaryDirectory() as td:
        test_version_parsing(td)
    test_builtin_profiles_load()
    test_e2e_engine_copy()
    print("PROFILE_DETECTION_OK")

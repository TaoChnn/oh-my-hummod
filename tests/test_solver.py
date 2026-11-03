# Unit tests for oh_my_hummod.solver - run: python -m pytest tests/test_solver.py
# (also runnable standalone: python tests/test_solver.py)
import os

sys_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
import sys  # noqa: E402
sys.path.insert(0, sys_path)

from oh_my_hummod.solver import parse_ics, parse_export, parse_sol, parse_sol_history  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
SOL = os.path.join(FIX, "sample.SOL")
ICS = os.path.join(FIX, "sample.ICS")


def test_parse_sol_current_values():
    vals = parse_sol(SOL, {"hemorrhage.switch", "bloodvol.vol", "system.x"})
    assert vals["Hemorrhage.Switch"] in (0.0, 1.0)
    assert 4000 < vals["BloodVol.Vol"] < 6500
    assert vals["System.X"] >= 0


def test_parse_sol_history():
    hist = parse_sol_history(SOL, {"Hemorrhage.Switch", "BloodVol.Vol"})
    assert hist["points"] >= 1
    assert len(hist["t"]) == hist["points"]
    assert set(hist["series"]) == {"Hemorrhage.Switch", "BloodVol.Vol"}
    for series in hist["series"].values():
        assert len(series) == hist["points"]
    # latest sample matches the current-value parser
    cur = parse_sol(SOL, {"bloodvol.vol", "system.x"})
    assert hist["series"]["BloodVol.Vol"][-1] == cur["BloodVol.Vol"]
    assert hist["t"][-1] == cur["System.X"]


def test_parse_sol_history_max_points():
    hist = parse_sol_history(SOL, {"BloodVol.Vol"}, max_points=2)
    assert hist["points"] <= 2
    assert hist["stride"] >= 1


def test_parse_sol_history_missing():
    hist = parse_sol_history(SOL, {"NoSuch.Var", "BloodVol.Vol"})
    assert "NoSuch.Var" in hist["missing"]
    assert "BloodVol.Vol" in hist["series"]


def test_parse_sol_missing_var_returns_empty():
    assert parse_sol(SOL, {"does.not.exist"}) == {}


def test_parse_ics():
    vals = parse_ics(ICS)
    assert "X" in vals and vals["X"] >= 0
    assert any(v > 0 for v in vals.values())


def test_parse_ics_filter():
    vals = parse_ics(ICS, {"x"})
    assert list(vals) == ["X"]


def test_parse_export_autodetect():
    assert "BloodVol.Vol" in parse_export(SOL, {"bloodvol.vol"})
    assert "X" in parse_export(ICS, {"x"})


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"ALL {len(fns)} TESTS PASSED")

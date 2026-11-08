"""Quick checks of the optimizer building blocks.   python -m pytest -q"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smbsim import Simulator, case_1, case_2, run  # noqa: E402
from smbopt import BatchSimulator, Problem, problem_preset, PROBLEMS, Optimizer  # noqa: E402
from smbopt.window import flows_from_m, apply_m, henry_constants, is_classic  # noqa: E402


def test_presets_valid_and_roundtrip():
    for key in PROBLEMS:
        p = problem_preset(key)
        assert p.validate() == [], key
        q = Problem.from_dict(p.to_dict())
        assert q.to_dict() == p.to_dict()


def test_validation_messages():
    p = problem_preset("case2_feed")
    for v in p.variables:
        v.optimize = False
    assert any("at least one decision variable" in e for e in p.validate())
    p = problem_preset("case2_feed")
    p.variables[0].lower = p.variables[0].upper + 1
    assert any("lower bound" in e for e in p.validate())
    p = problem_preset("case2_feed")
    for v in p.variables:
        if v.key == "port:2":
            v.optimize = False
    assert any("feed flow must be a decision variable" in e for e in p.validate())


def test_config_mapping():
    p = problem_preset("case2_feed")
    cfg = p.config_at({"Q1": 6.5, "port:2": 0.3, "step_time": 2.0})
    assert cfg.Q1 == 6.5 and cfg.ports[2].flow == 0.3 and cfg.step_time == 2.0
    assert cfg.ports[0].flow == 2.14  # untouched variables keep their start value


def test_batch_matches_engine_bitwise():
    for scheme in ("original", "conservative"):
        for fm in ("constant", "volume_change"):
            cfg = case_2(scheme=scheme, flow_model=fm)
            sim = Simulator(cfg)
            C, Q = sim.initial_state()
            C1, Q1, out, qb, _, _ = sim.advance(C, Q)
            b = BatchSimulator([cfg])
            Cb, Qb = b.initial_state()
            Cb1, Qb1, outb, qbb = b.advance(Cb, Qb)
            assert np.array_equal(Cb1[:, 0], C1) and np.array_equal(outb[0], out)


def test_batch_members_are_independent():
    cfgs = [case_2(), case_2(QF=0.3, step_time=1.95), case_2(Q1=6.7)]
    big = BatchSimulator(cfgs)
    Cb, Qb = big.initial_state()
    Cb, Qb, out, qb = big.advance(Cb, Qb)
    for k, c in enumerate(cfgs):
        one = BatchSimulator([c])
        one.nsub = big.nsub
        one.dt = one.T / one.nsub
        C1, Q1 = one.initial_state()
        C1, Q1, o1, q1 = one.advance(C1, Q1)
        assert np.array_equal(Cb[:, k], C1[:, 0]) and np.array_equal(out[k], o1[0])


def test_accelerated_css_matches_engine():
    cfg = case_2()
    r = BatchSimulator([cfg]).css(tol=1e-8)
    assert r["converged"]
    cfg.css_tol = 1e-8
    cfg.max_cycles = 400
    ref = run(cfg)["metrics"]
    for k in ("extract_purity", "extract_recovery", "raffinate_purity", "raffinate_recovery"):
        assert abs(r["metrics"][0][k] - ref[k]) < 1e-3


def test_m_value_mapping_roundtrip():
    cfg = case_2()
    assert is_classic(cfg)
    m = cfg.derived()["m_values"]
    back = apply_m(cfg, m, cfg.step_time)
    assert np.allclose(back.derived()["m_values"], m)
    f = flows_from_m(cfg, m, cfg.step_time)
    assert abs(f["QF"] - 0.24) < 1e-9 and abs(f["QD"] - 2.14) < 1e-9
    H = henry_constants(cfg)
    assert len(H) == 6 and all(h["H"] > 0 for h in H)
    assert not is_classic(case_2(open_loop=True))


def test_short_optimization_improves_feed():
    p = problem_preset("case2_feed")
    p.process["flow_model"] = "constant"
    for v in p.variables:
        v.optimize = v.key in ("port:2", "port:0")
    p.max_iterations = 3
    p.workers = 1
    res = Optimizer(p).run()
    assert res["optimum"]["feed"] >= res["start"]["feed"] - 1e-9
    assert res["evaluations"] > 0 and len(res["history"]) >= 2
    if res["feasible"]:
        m = res["optimum"]["metrics"]
        assert m["extract_purity"] >= 90 - 1e-2 and m["raffinate_purity"] >= 90 - 1e-2

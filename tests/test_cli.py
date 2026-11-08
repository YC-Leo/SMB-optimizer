"""Command-line interface and problem-file input/output.   python -m pytest -q tests/test_cli.py"""

import builtins
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smbopt import Problem, problem_preset  # noqa: E402
from smbopt.cli import EXAMPLES, main  # noqa: E402
from smbopt.io import load_problem, problem_from_setup, read_data, to_jsonable, write_data  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_example_files_are_valid(tmp_path, name, capsys):
    out = tmp_path / f"{name}.json"
    assert main(["example", name, "-o", str(out)]) == 0
    assert main(["validate", str(out)]) == 0
    assert "OK" in capsys.readouterr().out
    assert load_problem(out).to_dict() == problem_preset(EXAMPLES[name][0]).to_dict()


@pytest.mark.parametrize("name", ["case1_max_feed.json", "case2_max_feed.json", "case2_min_desorbent.json"])
def test_shipped_examples_match_presets(name):
    p = load_problem(ROOT / "examples" / name)
    assert p.validate() == []
    key = {"case1_max_feed.json": "case1_feed", "case2_max_feed.json": "case2_feed"}.get(name, "case2_desorbent")
    assert p.to_dict() == problem_preset(key).to_dict()


def test_yaml_roundtrip(tmp_path):
    pytest.importorskip("yaml")
    out = tmp_path / "case2.yaml"
    assert main(["example", "case2", "-o", str(out)]) == 0
    assert load_problem(out).to_dict() == problem_preset("case2_feed").to_dict()


def test_validate_reports_errors(tmp_path, capsys):
    p = problem_preset("case1_feed")
    p.variables[0].lower = p.variables[0].upper + 1
    f = tmp_path / "bad.json"
    write_data(f, p.to_dict())
    assert main(["validate", str(f)]) == 1
    assert "lower bound must be below the upper bound" in capsys.readouterr().out


def test_not_a_problem_file(tmp_path, capsys):
    f = tmp_path / "setup.json"
    f.write_text(json.dumps(problem_preset("case1_feed").process))
    assert main(["validate", str(f)]) == 1
    assert "from-setup" in capsys.readouterr().err
    assert main(["run", str(tmp_path / "missing.json")]) == 1


def test_from_setup(tmp_path):
    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps(problem_preset("case2_feed").process))
    out = tmp_path / "problem.json"
    assert main(["from-setup", str(setup), "-o", str(out)]) == 0
    p = load_problem(out)
    assert p.validate() == []
    assert p.process == problem_preset("case2_feed").process
    assert {v.key for v in p.variables} == {"Q1", "port:0", "port:1", "port:2", "step_time"}
    p2 = problem_from_setup(read_data(setup))
    assert p2.objective == "max_feed"


def test_missing_solver_message(monkeypatch, capsys):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "scipy":
            raise ImportError("No module named 'scipy'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as exc:
        main(["validate", "anything.json"])
    assert "pip install scipy" in str(exc.value)


def test_to_jsonable():
    d = to_jsonable({"a": np.array([1.0, np.nan]), "b": np.float64(np.inf), "_hidden": 1, "c": np.int64(3)})
    assert d == {"a": [1.0, None], "b": None, "c": 3}
    json.dumps(d)


def test_problem_dict_roundtrip_through_file(tmp_path):
    p = problem_preset("case2_desorbent")
    f = tmp_path / "p.json"
    write_data(f, p.to_dict())
    assert Problem.from_dict(read_data(f)).to_dict() == p.to_dict()


def test_run_writes_results(tmp_path, capsys):
    """A one-iteration run of a reduced problem: checks the output files, not the optimum."""
    p = problem_preset("case2_feed")
    p.process["flow_model"] = "constant"
    for v in p.variables:
        v.optimize = v.key in ("port:2", "port:0")
    p.max_iterations = 1
    f = tmp_path / "small.json"
    write_data(f, p.to_dict())
    out = tmp_path / "res"
    code = main(["run", str(f), "-o", str(out), "-w", "1", "-q"])
    assert code in (0, 2)
    s = read_data(out / "summary.json")
    assert s["objective"] == "max_feed" and s["iterations"] >= 1
    assert s["optimum"]["feed"] >= s["start"]["feed"] - 1e-9
    rows = list(csv.reader((out / "iterations.csv").open(encoding="utf-8")))
    assert rows[0][:2] == ["iteration", "objective"] and len(rows) == s["iterations"] + 2
    setup = read_data(out / "best_setup.json")
    assert "components" in setup and "ports" in setup

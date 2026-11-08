"""Local web server for the SMB Optimizer Suite (Python standard library only)."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from smbsim import ISOTHERMS
from smbopt import (
    Problem,
    PROBLEMS,
    OBJECTIVES,
    METRICS,
    METRIC_LABEL,
    Optimizer,
    BatchRunner,
    Cancelled,
    point_view,
    __version__,
)
from smbopt.optimizer import default_workers
from smbopt.io import problem_from_setup, to_jsonable
from smbopt.window import scan, henry_constants, is_classic

STATIC = Path(__file__).parent / "static"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".json": "application/json",
}


_clean = to_jsonable  # results are made JSON-safe the same way as by the command-line tool


class Runner:
    """One pool of worker processes shared by all jobs (rebuilt when the worker count changes)."""

    lock = threading.Lock()
    runner = None

    @classmethod
    def get(cls, workers):
        w = workers or default_workers()
        with cls.lock:
            if cls.runner is None or cls.runner.workers != w:
                if cls.runner is not None:
                    cls.runner.close()
                cls.runner = BatchRunner(w)
            return cls.runner


class Job:
    def __init__(self, kind, problem: Problem, extra=None):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.problem, self.extra = kind, problem, extra or {}
        self.status = "running"
        self.progress = None
        self.result = None
        self.error = None
        self.cancelled = False
        self.lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            runner = Runner.get(self.problem.workers)
            if self.kind == "optimize":
                opt = Optimizer(self.problem, progress=self._on_progress, cancel=lambda: self.cancelled, runner=runner)
                res = opt.run()
                pts = res.pop("_points")
                res["start_view"] = point_view(self.problem, res["start"]["values"], pts["start"])
                res["optimum_view"] = point_view(self.problem, res["optimum"]["values"], pts["optimum"])
                res["problem"] = self.problem.to_dict()
            else:
                res = scan(
                    self.problem,
                    self.extra["values"],
                    n=self.extra.get("n", 10),
                    runner=runner,
                    progress=self._on_progress,
                    cancel=lambda: self.cancelled,
                )
            with self.lock:
                self.result = _clean(res)
                self.status = "done"
        except (Cancelled, InterruptedError):
            with self.lock:
                self.status = "cancelled"
        except Exception as e:  # report any failure to the UI
            with self.lock:
                self.error = str(e)
                self.status = "error"

    def _on_progress(self, p):
        with self.lock:
            self.progress = _clean(p)

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "progress": self.progress,
                "result": self.result,
                "error": self.error,
            }


JOBS: dict[str, Job] = {}


def problem_info(p: Problem) -> dict:
    """Live summary of a problem for the setup panel."""
    cfg = p.config_at(p.start_values())
    flows = p.flows(cfg)
    d = cfg.derived()
    return {
        "derived": d,
        "flows": flows,
        "henry": henry_constants(cfg),
        "classic": is_classic(cfg),
        "labels": cfg.port_labels(),
        "n_columns": cfg.n_columns,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SMBOptimizer/" + __version__

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/defaults":
            return self._send(
                200,
                _clean(
                    {
                        "version": __version__,
                        "objectives": OBJECTIVES,
                        "metrics": METRIC_LABEL,
                        "workers": default_workers(),
                        "isotherms": {k: {kk: vv for kk, vv in v.items() if kk != "fn"} for k, v in ISOTHERMS.items()},
                        "problems": {
                            k: {"label": v[0], "summary": v[1], "problem": v[2]().to_dict()}
                            for k, v in PROBLEMS.items()
                        },
                    }
                ),
            )
        if path.startswith("/api/job/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            return self._send(200, job.snapshot()) if job else self._send(404, {"error": "unknown job"})
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (STATIC / rel).resolve()
        if STATIC.resolve() in f.parents and f.is_file():
            return self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON"})

        if path == "/api/from_setup":
            # an SMB Simulator setup -> problem with default decision variables, keeping the other settings
            try:
                base = Problem.from_dict(payload["problem"]) if payload.get("problem") else None
                base = problem_from_setup(payload["setup"], base)
                return self._send(200, {"problem": base.to_dict()})
            except Exception as e:
                return self._send(400, {"errors": [f"Could not read the setup: {e}"]})

        if path in ("/api/validate", "/api/optimize", "/api/scan"):
            try:
                prob = Problem.from_dict(payload["problem"] if "problem" in payload else payload)
            except Exception as e:
                return self._send(400, {"errors": [f"Could not read the problem: {e}"]})
            errs = prob.validate()
            if path == "/api/validate":
                info = None
                if not any(e.startswith("Process setup") for e in errs):
                    try:
                        info = _clean(problem_info(prob))
                    except Exception as e:  # noqa: BLE001
                        errs.append(str(e))
                return self._send(200, {"errors": errs, "info": info})
            if errs:
                return self._send(400, {"errors": errs})
            if any(j.status == "running" for j in JOBS.values()):
                return self._send(409, {"errors": ["Another optimization or scan is still running."]})
            for old in [k for k, j in JOBS.items() if j.status != "running"][:-10]:
                JOBS.pop(old, None)
            if path == "/api/optimize":
                job = Job("optimize", prob)
            else:
                values = payload.get("values") or prob.start_values()
                job = Job("scan", prob, {"values": values, "n": int(payload.get("n", 10))})
            JOBS[job.id] = job
            return self._send(200, {"id": job.id})

        if path.startswith("/api/job/") and path.endswith("/cancel"):
            job = JOBS.get(path.split("/")[3])
            if job:
                job.cancelled = True
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8051) -> ThreadingHTTPServer:
    """Create (but do not start) the local web server; call ``serve_forever()`` on the result."""
    return ThreadingHTTPServer((host, port), Handler)

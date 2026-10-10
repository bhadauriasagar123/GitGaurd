"""Agent execution trace: every autonomous step is recorded (agent, action, outcome, latency) and
returned with the response so judges (and auditors) can see exactly what the agents did."""
from __future__ import annotations

import time
from contextlib import contextmanager

from app.core.context import correlation_id_var


class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    @contextmanager
    def step(self, agent: str, action: str):
        rec = {"agent": agent, "action": action, "status": "ok", "detail": None}
        t0 = time.perf_counter()
        try:
            yield rec
        except Exception as e:
            rec["status"] = "failed"
            rec["detail"] = type(e).__name__
            raise
        finally:
            rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            self.steps.append(rec)

    def export(self) -> dict:
        return {"correlationId": correlation_id_var.get(), "steps": self.steps,
                "totalMs": round(sum(s["ms"] for s in self.steps), 1)}

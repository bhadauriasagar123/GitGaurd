"""Deploy Agent: deploys through a pluggable *target* (Strategy), then verifies with the black-box smoke suite and rolls
back / fails loudly if verification fails. Dry-run by default; pass --execute to act.

Targets:  azure-webapp (az CLI, zip deploy) | webhook (any host with a deploy hook: Render, Railway, Koyeb, ...) | noop
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx

from scripts.ci_agents.common import Report


def _env(name: str) -> str | None:
    """Env var value, or None when unset/empty/an UNEXPANDED pipeline macro like '$(NAME)' (Azure DevOps leaves undefined
    variables as literal text, which must never be treated as a URL)."""
    v = (os.environ.get(name) or "").strip()
    return None if not v or (v.startswith("$(") and v.endswith(")")) else v


class Target:
    name = "abstract"

    def deploy(self, execute: bool, log: list[str]) -> None: ...
    def rollback(self, execute: bool, log: list[str]) -> None: ...


def _run(cmd: list[str], execute: bool, log: list[str]) -> None:
    log.append(("RUN  " if execute else "PLAN ") + " ".join(cmd))
    if execute:
        subprocess.run(cmd, check=True)


class AzureWebApp(Target):
    name = "azure-webapp"

    def __init__(self):
        self.app, self.rg = os.environ.get("WEBAPP_NAME", "<app>"), os.environ.get("RESOURCE_GROUP", "<rg>")
        self.slot = os.environ.get("DEPLOY_SLOT")  # e.g. "staging" (needs Standard tier or higher; F1/B1 has no slots)

    def deploy(self, execute, log):
        cmd = ["az", "webapp", "deploy", "-g", self.rg, "-n", self.app, "--src-path", os.environ.get("PACKAGE", "regguard.zip"), "--type", "zip"]
        if self.slot:
            cmd += ["--slot", self.slot]
        _run(cmd, execute, log)

    def rollback(self, execute, log):
        if self.slot:
            _run(["az", "webapp", "deployment", "slot", "swap", "-g", self.rg, "-n", self.app, "--slot", self.slot, "--target-slot", "production"], execute, log)
        else:
            log.append("NOTE no slot configured: redeploy the previous successful pipeline artifact (Pipelines > Runs > previous > Redeploy)")


class Webhook(Target):
    name = "webhook"

    def _post(self, url_var: str, execute: bool, log: list[str]):
        url = _env(url_var)
        log.append(("POST " if execute else "PLAN POST ") + f"${url_var}" + ("" if url else " (NOT SET)"))
        if execute:
            if not url:
                raise RuntimeError(f"{url_var} is not set")
            httpx.post(url, timeout=60).raise_for_status()

    def deploy(self, execute, log):
        self._post("DEPLOY_HOOK_URL", execute, log)

    def rollback(self, execute, log):
        if _env("ROLLBACK_HOOK_URL"):
            self._post("ROLLBACK_HOOK_URL", execute, log)
        else:
            log.append("NOTE no ROLLBACK_HOOK_URL: roll back from the host's dashboard (previous deploy)")


class Noop(Target):
    name = "noop"

    def deploy(self, execute, log):
        log.append("noop target: nothing deployed")

    def rollback(self, execute, log):
        pass


TARGETS = {t.name: t for t in (AzureWebApp, Webhook, Noop)}


def wait_ready(base: str, timeout: int = 300) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(f"{base}/readyz", timeout=10).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(10)
    return False


def run(target_name: str, base: str | None, execute: bool, smoke: bool = True) -> Report:
    r = Report("Deploy Agent")
    log: list[str] = []
    target = TARGETS[target_name]()
    r.facts.update(target=target_name, mode="EXECUTE" if execute else "DRY-RUN")
    try:
        target.deploy(execute, log)
    except Exception as e:  # noqa: BLE001
        r.add("block", "deploy-failed", f"{type(e).__name__}: {e}")
        target.rollback(execute, log)
        r.facts["log"] = " | ".join(log)
        return r
    if execute and base and smoke:
        if not wait_ready(base):
            r.add("block", "not-ready", f"{base}/readyz never became healthy; rolling back.")
            target.rollback(execute, log)
        else:
            rc = subprocess.run([sys.executable, "-m", "scripts.prod_smoke"], env={**os.environ, "BASE": base}).returncode
            if rc != 0:
                r.add("block", "smoke-failed", "Post-deploy smoke suite failed; rolling back.")
                target.rollback(execute, log)
            else:
                r.add("info", "verified", "Post-deploy smoke suite passed.")
    elif not execute:
        r.add("info", "dry-run", "Nothing was changed. Re-run with --execute.")
    r.facts["log"] = " | ".join(log)
    return r

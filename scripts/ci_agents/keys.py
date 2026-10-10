"""Print `export ADMIN_KEY=... ANALYST_KEY=... VIEWER_KEY=...` from an API_KEYS value ("key:role:tenant,...") given in the
environment variable named by argv[1]. Used by pipeline steps:  eval "$(python -m scripts.ci_agents.keys STAGING_API_KEYS)"
Keys are never echoed to the build log by this script (pipelines mask secret variables; eval keeps them in the shell)."""
import os
import shlex
import sys

if __name__ == "__main__":
    raw = os.environ.get(sys.argv[1], "")
    seen = {}
    for entry in raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3 and parts[1] in ("admin", "analyst", "viewer"):
            seen.setdefault(parts[1], parts[0])
    for role, key in seen.items():
        print(f"export {role.upper()}_KEY={shlex.quote(key)}")

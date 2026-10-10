"""Delivery agents CLI:   python -m scripts.ci_agents <agent> [options]

  pr-review        --base origin/main [--llm] [--post]      review the PR diff (deterministic gates + optional advisory LLM)
  build-review     --junit junit.xml [--bandit b.json --audit a.json --coverage c.xml]
  pipeline-review  [--pipeline azure-pipelines.yml]
  release-gate     --target staging|production --build build.json --pipeline pipe.json [--pr pr.json] [--smoke-staging s.json]
  deploy           --target azure-webapp|webhook|noop [--base https://...] [--execute]

Exit code: 0 pass/review, 1 block (so a pipeline step fails exactly when an agent says NO)."""
import argparse
import os
import sys

os.environ.setdefault("ENV", "test")
from scripts.ci_agents import build_review, deploy_agent, pipeline_review, pr_review, release_gate  # noqa: E402
from scripts.ci_agents.common import post_pr_comment, write_report  # noqa: E402


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # build logs on Windows agents default to cp1252
    ap = argparse.ArgumentParser(prog="ci_agents")
    sub = ap.add_subparsers(dest="agent", required=True)
    p = sub.add_parser("pr-review"); p.add_argument("--base", default="origin/main"); p.add_argument("--diff-file"); p.add_argument("--llm", action="store_true"); p.add_argument("--post", action="store_true"); p.add_argument("--out")
    b = sub.add_parser("build-review"); b.add_argument("--junit"); b.add_argument("--bandit"); b.add_argument("--audit"); b.add_argument("--coverage"); b.add_argument("--out")
    q = sub.add_parser("pipeline-review"); q.add_argument("--pipeline", default="azure-pipelines.yml"); q.add_argument("--out")
    g = sub.add_parser("release-gate"); g.add_argument("--target", required=True, choices=["staging", "production"]); g.add_argument("--build"); g.add_argument("--pipeline"); g.add_argument("--pr"); g.add_argument("--smoke-staging"); g.add_argument("--out")
    d = sub.add_parser("deploy"); d.add_argument("--target", required=True, choices=list(deploy_agent.TARGETS)); d.add_argument("--base"); d.add_argument("--execute", action="store_true"); d.add_argument("--out")
    a = ap.parse_args(argv)

    if a.agent == "pr-review":
        diff = open(a.diff_file, encoding="utf8").read() if a.diff_file else pr_review.git_diff(a.base)
        rep = pr_review.review(diff)
        safe = pr_review.injection_scan(diff, rep)
        if a.llm and safe:
            pr_review.llm_review(diff, rep)
    elif a.agent == "build-review":
        rep = build_review.review(a.junit, a.bandit, a.audit, a.coverage)
    elif a.agent == "pipeline-review":
        rep = pipeline_review.review(a.pipeline)
    elif a.agent == "release-gate":
        rep = release_gate.decide(a.target, a.pr, a.build, a.pipeline, a.smoke_staging)
    else:
        rep = deploy_agent.run(a.target, a.base, a.execute)
    print(rep.markdown())
    write_report(rep, getattr(a, "out", None))
    if getattr(a, "post", False):
        print(post_pr_comment(rep.markdown()))
    return 1 if rep.verdict == "block" else 0


if __name__ == "__main__":
    sys.exit(main())

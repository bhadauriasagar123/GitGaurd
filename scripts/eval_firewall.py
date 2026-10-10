"""Reproducible firewall evaluation:  python -m scripts.eval_firewall"""
import asyncio
import os
import sys

os.environ.setdefault("ENV", "test")
from app.firewall.corpus import ATTACKS, BENIGN  # noqa: E402
from app.firewall.engine import PromptInjectionFirewall  # noqa: E402


async def main() -> int:
    fw = PromptInjectionFirewall()
    cats: dict[str, list[int]] = {}
    missed, cat_miss, lat = [], [], []
    for cat, src, text in ATTACKS:
        r = await fw.scan(content=text, source_type=src)
        lat.append(r["stats"]["latencyMs"])
        hit = r["verdict"] != "allow"
        cats.setdefault(cat, []).append(int(hit))
        if not hit:
            missed.append((cat, src, text[:70]))
        elif cat not in r["categoriesDetected"]:
            cat_miss.append((cat, r["categoriesDetected"], text[:60]))
    fp = []
    for src, text in BENIGN:
        r = await fw.scan(content=text, source_type=src)
        lat.append(r["stats"]["latencyMs"])
        if r["verdict"] != "allow":
            fp.append((src, r["verdict"], r["categoriesDetected"], text[:70]))
    total = len(ATTACKS)
    det = sum(sum(v) for v in cats.values())
    print(f"Attack samples: {total} | detected (sanitize/block): {det} ({det / total:.1%})")
    for c, v in cats.items():
        print(f"  {c:24s} {sum(v)}/{len(v)}")
    print(f"Benign samples: {len(BENIGN)} | false positives: {len(fp)} ({len(fp) / len(BENIGN):.1%})")
    print(f"Latency ms: avg {sum(lat) / len(lat):.1f}  max {max(lat):.1f}")
    for m in missed:
        print("MISSED:", m)
    for m in cat_miss:
        print("CATEGORY-MISMATCH:", m)
    for f in fp:
        print("FALSE-POSITIVE:", f)
    return 0 if not missed and not fp else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

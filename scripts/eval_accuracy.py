"""Measured accuracy on the gold sets:  python -m scripts.eval_accuracy [v1|v2|v3|v4|all] [--write]
v1/v2 were used to develop the rules, v3 to build the learned layer, v4 is the one-shot final estimate (see docs/ACCURACY.md)."""
import asyncio
import importlib
import os
import sys

os.environ.setdefault("ENV", "test")
from app.compliance import mapping  # noqa: E402
from app.compliance.controls import parse_controls  # noqa: E402
from app.compliance.obligations import extract_obligations  # noqa: E402
from app.firewall.engine import PromptInjectionFirewall  # noqa: E402

SETS = {"v1": "app.benchmark.gold", "v2": "app.benchmark.gold_v2", "v3": "app.benchmark.gold_v3", "v4": "app.benchmark.gold_v4"}


def load(name: str):
    return importlib.import_module(SETS[name])


def extraction(g):
    tp = fp = fn = attr_ok = attr_total = 0
    errors = []
    for text, exp in g.OBLIGATION_GOLD:
        got = extract_obligations("1.1 " + text, {"code": "G", "version": "1"})
        if exp is None:
            if got:
                fp += 1
                errors.append(("FALSE OBLIGATION", text[:80], got[0]["modality"]))
            continue
        if not got:
            fn += 1
            errors.append(("MISSED", text[:80], None))
            continue
        if got[0]["modality"] != exp["modality"]:
            fp += 1
            fn += 1
            errors.append(("WRONG MODALITY", text[:80], got[0]["modality"]))
            continue
        tp += 1
        for key, field in (("deadline", "deadlineHours"), ("freq", "frequencyDays")):
            if key in exp:
                attr_total += 1
                if got[0][field] is not None and abs(got[0][field] - exp[key]) < 0.5:
                    attr_ok += 1
                else:
                    errors.append((f"WRONG {key.upper()}", text[:80], got[0][field]))
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    return {"precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-9), "attr": attr_ok / max(attr_total, 1), "errors": errors, "n": len(g.OBLIGATION_GOLD)}


def mapping_acc(g):
    ctrl_text = "\n\n".join(f"Control ID: {k}\nTitle: {k}\nDescription: {v}\nOwner: X\nType: preventive\nFrequency: continuous\nAutomation: automated" for k, v in g.CONTROLS.items())
    controls = parse_controls(ctrl_text)
    obls, pairs, errors = [], [], []
    for i, (t, want) in enumerate(g.MAPPING_GOLD):
        o = extract_obligations(f"{i + 1}.1 {t}", {"code": "G", "version": "1"})
        if not o:
            errors.append((t[:70], want, "NOT EXTRACTED"))
            continue
        obls.append(o[0])
        pairs.append((o[0], t, want))
    maps = mapping.build_mappings(obls, controls, top_k=3)
    top1 = top3 = 0
    for o, t, want in pairs:
        ranked = [m["controlId"] for m in maps[o["id"]]]
        top1 += bool(ranked and ranked[0] == want)
        top3 += want in ranked
        if not ranked or ranked[0] != want:
            errors.append((t[:70], want, ranked[:3]))
    n = len(g.MAPPING_GOLD)
    return {"top1": top1 / n, "top3": top3 / n, "errors": errors, "n": n}


async def firewall(g):
    fw = PromptInjectionFirewall()
    tp = fn = fp = tn = 0
    errors = []
    for label, src, text in g.FIREWALL_GOLD:
        r = await fw.scan(content=text, source_type=src)
        flagged = r["verdict"] != "allow"
        if label == "ATTACK":
            tp += flagged
            fn += not flagged
            if not flagged:
                errors.append(("MISSED ATTACK", src, text[:90]))
        else:
            fp += flagged
            tn += not flagged
            if flagged:
                errors.append(("FALSE POSITIVE", src, text[:90], r["categoriesDetected"]))
    n = tp + fn + fp + tn
    return {"recall": tp / max(tp + fn, 1), "precision": tp / max(tp + fp, 1), "fpr": fp / max(fp + tn, 1), "accuracy": (tp + tn) / n, "errors": errors, "n": n}


def run(name: str):
    g = load(name)
    return extraction(g), mapping_acc(g), asyncio.run(firewall(g))


def fmt(name, e, m, f):
    return [f"[{name}] extraction ({e['n']} sentences incl. non-obligations): precision {e['precision']:.0%} recall {e['recall']:.0%} F1 {e['f1']:.0%} | deadline/cadence values {e['attr']:.0%}",
            f"[{name}] mapping ({m['n']} obligations): top-1 {m['top1']:.0%} top-3 {m['top3']:.0%}",
            f"[{name}] firewall ({f['n']} samples): accuracy {f['accuracy']:.0%} attack recall {f['recall']:.0%} false-positive rate {f['fpr']:.0%}"]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = list(SETS) if (not args or args == ["all"]) else args
    lines = []
    for n in names:
        e, m, f = run(n)
        lines += fmt(n, e, m, f)
        for title, errs in (("extraction", e["errors"]), ("mapping", m["errors"]), ("firewall", f["errors"])):
            for x in errs:
                lines.append(f"    ({n}/{title}) " + " | ".join(str(i) for i in x))
    print("\n".join(lines))
    if "--write" in sys.argv:
        with open("docs/ACCURACY_LATEST.txt", "w", encoding="utf8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

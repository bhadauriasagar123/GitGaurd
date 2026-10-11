"""Measured accuracy on the gold sets:  python -m scripts.eval_accuracy [v1|v2|v3|v4|real|all] [--write]
v1/v2 were used to develop the rules, v3 to build the learned layer, v4 is the one-shot final estimate, "real" is the
public-regulation pack in app/sample/dataset (CERT-In, RBI, DPDP, GDPR) scored end to end (see docs/ACCURACY.md)."""
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


def real_dataset() -> dict:
    """End-to-end accuracy on the public-regulation pack (app/sample/dataset): whole documents, gold labels in manifest.json."""
    from app.compliance import engine
    from app.compliance.controls import parse_evidence
    from app.sample import realworld as R

    man, gold = R.manifest(), R.manifest()["gold"]
    read = lambda f: (R.DIR / f).read_text(encoding="utf8")  # noqa: E731
    regs = {f"{d['regulation']['code']}@{d['regulation']['version']}": d for d in man["load_order"] if d.get("regulation")}
    errors = []

    tp = fp = fn = attr_ok = attr_total = 0
    for key, labels in gold.items():
        d = regs[key]
        by_clause: dict[str, list] = {}
        for o in extract_obligations(read(d["file"]), d["regulation"]):
            by_clause.setdefault(o["clause"], []).append(o)
        want = {lb["clause"]: lb for lb in labels}
        for c, os_ in by_clause.items():
            if c not in want:
                fp += len(os_)
                errors.append(("extraction", "FALSE OBLIGATION", key, c))
        for c, lb in want.items():
            got = by_clause.get(c)
            if not got:
                fn += 1
                errors.append(("extraction", "MISSED", key, c))
                continue
            if got[0]["modality"] != lb["modality"]:
                fp += 1
                fn += 1
                errors.append(("extraction", "WRONG MODALITY", key, c, got[0]["modality"]))
                continue
            tp += 1
            for field in ("deadlineHours", "frequencyDays", "retentionMinHours"):
                if field in lb:
                    attr_total += 1
                    v = got[0][field]
                    if v is not None and abs(v - lb[field]) < 0.5:
                        attr_ok += 1
                    else:
                        errors.append(("extraction", f"WRONG {field}", key, c, v))
    p, r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)

    latest = {d["regulation"]["code"]: d for d in man["load_order"] if d.get("regulation")}  # later versions supersede earlier ones
    ctrl = next(d for d in man["load_order"] if d["kind"] == "control")
    ev = next(d for d in man["load_order"] if d["kind"] == "evidence")
    state = {"profile": man["profile"], "regulations": [{"meta": d["regulation"], "text": read(d["file"])} for d in latest.values()],
             "controls": parse_controls(read(ctrl["file"])), "evidence": parse_evidence(read(ev["file"]))}
    a = engine.analyze(state, R.as_of())
    map_ok = map_n = st_ok = st_n = 0
    for code, d in latest.items():
        key = f"{code}@{d['regulation']['version']}"
        for lb in gold[key]:
            x = next((v for v in a["assessments"] if v["regCode"] == code and v["clause"] == lb["clause"]), None)
            if x is None:
                continue
            ranked = [m["controlId"] for m in x["mappedControls"]]
            ok = not any(m["strength"] == "strong" for m in x["mappedControls"]) if lb["control"] is None else bool(ranked) and ranked[0] == lb["control"]
            map_n += 1
            map_ok += ok
            if not ok:
                errors.append(("mapping", key, lb["clause"], f"want {lb['control']}", f"got {ranked[:3]}"))
            if "status" in lb:
                st_n += 1
                st_ok += x["status"] == lb["status"]
                if x["status"] != lb["status"]:
                    errors.append(("gap detection", key, lb["clause"], f"want {lb['status']}", f"got {x['status']}"))

    async def fw_eval():
        fw = PromptInjectionFirewall()
        ok = n = 0
        for d in man["load_order"] + man["attack_documents"]:
            res = await fw.scan(content=read(d["file"]), source_type=d["sourceType"])
            want_flag = d.get("expect", "allow") != "allow"
            n += 1
            ok += (res["verdict"] != "allow") == want_flag
            if (res["verdict"] != "allow") != want_flag:
                errors.append(("firewall", d["file"], f"want {d.get('expect', 'allow')}", f"got {res['verdict']}", res["categoriesDetected"]))
        return ok / n, n

    fw_acc, fw_n = asyncio.run(fw_eval())
    scores = {"extractionF1": 2 * p * r / max(p + r, 1e-9), "mappingTop1": map_ok / max(map_n, 1), "gapDetection": st_ok / max(st_n, 1), "firewall": fw_acc}
    return {**scores, "overall": sum(scores.values()) / len(scores), "precision": p, "recall": r, "attr": attr_ok / max(attr_total, 1),
            "nObligations": tp + fn, "nMapped": map_n, "nStatus": st_n, "nFirewall": fw_n, "errors": errors}


def fmt_real(x) -> list[str]:
    return [f"[real] extraction ({x['nObligations']} gold obligations in 6 public regulations): precision {x['precision']:.0%} recall {x['recall']:.0%} F1 {x['extractionF1']:.0%} | deadline/cadence/retention values {x['attr']:.0%}",
            f"[real] mapping ({x['nMapped']} obligations -> 23 bank controls): top-1 {x['mappingTop1']:.0%}",
            f"[real] gap detection ({x['nStatus']} obligations, compliant/partial/non-compliant/uncovered): {x['gapDetection']:.0%}",
            f"[real] firewall ({x['nFirewall']} documents, genuine + poisoned): accuracy {x['firewall']:.0%}",
            f"[real] OVERALL (mean of the four): {x['overall']:.1%}"]


def fmt(name, e, m, f):
    return [f"[{name}] extraction ({e['n']} sentences incl. non-obligations): precision {e['precision']:.0%} recall {e['recall']:.0%} F1 {e['f1']:.0%} | deadline/cadence values {e['attr']:.0%}",
            f"[{name}] mapping ({m['n']} obligations): top-1 {m['top1']:.0%} top-3 {m['top3']:.0%}",
            f"[{name}] firewall ({f['n']} samples): accuracy {f['accuracy']:.0%} attack recall {f['recall']:.0%} false-positive rate {f['fpr']:.0%}"]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = list(SETS) + ["real"] if (not args or args == ["all"]) else args
    lines = []
    for n in names:
        if n == "real":
            x = real_dataset()
            lines += fmt_real(x)
            lines += ["    (real/" + e[0] + ") " + " | ".join(str(i) for i in e[1:]) for e in x["errors"]]
            continue
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

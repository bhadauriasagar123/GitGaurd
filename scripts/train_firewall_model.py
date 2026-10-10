"""Train the firewall intent model:  python -m scripts.train_firewall_model
Training data = dev corpus + gold v1/v2 (+ pseudo-labelled categories) + synthetic templates + benign pools (regulatory
sentences, controls, questions). gold_v3 is NEVER used for training - it is the unbiased test set."""
import asyncio
import json
import os
import random
import sys

os.environ.setdefault("ENV", "test")
import numpy as np  # noqa: E402
from scipy.sparse import csr_matrix  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from app.benchmark import gold, gold_v2, gold_v3, training_data as td  # noqa: E402
from app.firewall import ml  # noqa: E402
from app.firewall.corpus import ATTACKS, BENIGN  # noqa: E402
from app.firewall.engine import PromptInjectionFirewall  # noqa: E402
from app.sample import data as sample  # noqa: E402

CLASSES = td.CATS + ["BENIGN"]


async def pseudo_label(items):
    fw = PromptInjectionFirewall()
    out = []
    for src, text in items:
        r = await fw.scan(content=text, source_type=src)
        out.append((r["categoriesDetected"][0] if r["categoriesDetected"] else "INSTRUCTION_OVERRIDE", text))
    return out


def build():
    pos, neg = [], []
    pos += [(c, t) for c, _, t in ATTACKS if c != "ENCODED_INSTRUCTIONS" or len(t) < 400]
    neg += [t for _, t in BENIGN]
    for g in (gold, gold_v2):
        pos += asyncio.run(pseudo_label([(s, t) for lab, s, t in g.FIREWALL_GOLD if lab == "ATTACK"]))
        neg += [t for lab, _, t in g.FIREWALL_GOLD if lab == "BENIGN"]
        neg += [t for t, _ in g.OBLIGATION_GOLD]
        neg += list(g.CONTROLS.values())
    for d in sample.build():
        if d["kind"] == "regulation":
            neg += [ln.split(" ", 1)[1] for ln in d["content"].splitlines() if ln[:1].isdigit() and " " in ln]
    for ln in sample.CONTROLS.splitlines():
        if ln.startswith("Description:"):
            neg.append(ln[12:].strip())
    pos += td.synthetic()
    neg += td.benign_pool()
    neg += td.benign_generated()
    neg += td.benign_policy()
    neg += td.benign_imperatives()
    # light augmentation of benign: wrap with polite frames so politeness alone is not a signal
    rng = random.Random(3)
    neg += [rng.choice(["Please ", "Could you ", "Hi, ", "Thanks. ", "Now "]) + t[0].lower() + t[1:] for t in list(neg) if t and rng.random() < 0.35]
    return pos, list(dict.fromkeys(neg))


def vec(texts):
    rows, cols, vals = [], [], []
    for r, t in enumerate(texts):
        for i, v in ml.features(t).items():
            rows.append(r); cols.append(i); vals.append(v)
    return csr_matrix((vals, (rows, cols)), shape=(len(texts), ml.DIM))


def main():
    pos, neg = build()
    texts = [t for _, t in pos] + neg
    y = [CLASSES.index(c) for c, _ in pos] + [CLASSES.index("BENIGN")] * len(neg)
    print(f"training samples: {len(pos)} attacks, {len(neg)} benign")
    X = vec(texts)
    clf = LogisticRegression(C=12.0, max_iter=400, class_weight="balanced")
    clf.fit(X, y)
    coef, bias = clf.coef_, clf.intercept_
    cls_idx = list(clf.classes_)
    weights = []
    for k in range(len(CLASSES)):
        row = coef[cls_idx.index(k)] if k in cls_idx else np.zeros(ml.DIM)
        nz = np.where(np.abs(row) > 0.05)[0]
        weights.append({str(int(i)): round(float(row[i]), 3) for i in nz})
    model = {"classes": CLASSES, "bias": [round(float(bias[cls_idx.index(k)]), 3) if k in cls_idx else -5.0 for k in range(len(CLASSES))], "weights": weights}
    with open(ml.MODEL_PATH, "w", encoding="utf8") as f:
        json.dump(model, f, separators=(",", ":"))
    ml.load_model.cache_clear()
    m = ml.load_model()
    tr_ok = sum((m.predict(t)[1] >= 0.5) == (c != "BENIGN") for c, t in zip([c for c, _ in pos] + ["BENIGN"] * len(neg), texts)) / len(texts)
    print(f"model.json: {os.path.getsize(ml.MODEL_PATH) / 1024:.0f} KB, nonzero weights {sum(len(w) for w in weights)}, train accuracy (attack vs benign) {tr_ok:.1%}")


if __name__ == "__main__":
    sys.exit(main())

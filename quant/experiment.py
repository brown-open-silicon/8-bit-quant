"""Experiment 1: how do int8 / int4 / ternary weights compare on
  (a) accuracy, (b) memory, (c) robustness to radiation-style bit flips?

Also exports golden test vectors so the RTL must match the Python bit-for-bit.

  uv run python quant/experiment.py            # full run
  uv run python quant/experiment.py --retrain  # ignore cached float model
"""
import argparse
import json
from pathlib import Path

import numpy as np

import mnist
import qlib

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "mlp_float.npz"
CACHE_QAT = ROOT / "data" / "mlp_ternary_qat.npz"
VECTORS = ROOT / "tb" / "vectors"

# GF180 SRAM macro gf180mcu_fd_ip_sram__sram512x8m8wm1: 512 bytes, 431.86 x 484.88 um
SRAM_BYTES, SRAM_MM2 = 512, 0.43186 * 0.48488


def build_quant_model(p, fmt, x_calib):
    q1, s1 = qlib.quantize(p["w1"], fmt)
    q2, s2 = qlib.quantize(p["w2"], fmt)
    h = np.maximum(0, x_calib @ p["w1"].T + p["b1"])
    return {
        "fmt": fmt, "q1": q1, "s1": s1, "q2": q2, "s2": s2,
        "b1": p["b1"], "b2": p["b2"],
        "sa1": 1.0 / 127,           # inputs are in [0, 1]
        "sa2": h.max() / 127,       # calibrated hidden-activation range
    }


def int_forward(m, x, q1=None, q2=None):
    """Integer inference -- the arithmetic the chip performs.
    Integer values are multiplied in float64, which is exact at these sizes and
    much faster than NumPy's integer matmul."""
    q1 = m["q1"] if q1 is None else q1
    q2 = m["q2"] if q2 is None else q2
    xq = qlib.quantize_activations(x, m["sa1"])
    acc1 = xq.astype(np.float64) @ q1.T.astype(np.float64)       # int32 MAC array
    h = np.maximum(0, acc1 * (m["sa1"] * m["s1"]) + m["b1"])
    hq = qlib.quantize_activations(h, m["sa2"])
    acc2 = hq.astype(np.float64) @ q2.T.astype(np.float64)
    return (acc2 * (m["sa2"] * m["s2"]) + m["b2"]).argmax(1)


def faulty_accuracy(m, x, y, p, trials, rng, detect=True):
    fmt, accs, caught = m["fmt"], [], 0
    for _ in range(trials):
        qs = []
        for key in ("q1", "q2"):
            codes = qlib.flip_bits(qlib.encode(m[key], fmt), fmt, p, rng)
            q, n = qlib.decode(codes, fmt, detect=detect)
            qs.append(q)
            caught += n
        accs.append((int_forward(m, x, *qs) == y).mean())
    return float(np.mean(accs)), caught / trials


def export_vectors(m_int8, m_tern, x):
    """Real dot products from layer 1: input image i . weight row j."""
    VECTORS.mkdir(parents=True, exist_ok=True)
    xq = qlib.quantize_activations(x[:8], m_int8["sa1"])
    for name, m in (("mac_int8", m_int8), ("pe_ternary", m_tern)):
        cases = []
        for i in range(len(xq)):
            for j in range(4):
                a, w = xq[i], m["q1"][j]
                stored = qlib.encode(w, m["fmt"]) if m["fmt"] == "ternary" else w
                cases.append({
                    "a": a.tolist(),
                    "w": stored.astype(int).tolist(),
                    "expected": int(np.dot(a.astype(np.int64), w.astype(np.int64))),
                })
        (VECTORS / f"{name}.json").write_text(json.dumps(cases))
        print(f"  wrote {len(cases)} golden dot products -> tb/vectors/{name}.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrain", action="store_true")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--n-test", type=int, default=2000)
    args = ap.parse_args()

    d = mnist.load()
    if CACHE.exists() and not args.retrain:
        p = dict(np.load(CACHE))
    else:
        print("training float MLP 784-128-10")
        p = mnist.train(d)
        np.savez(CACHE, **p)
    if CACHE_QAT.exists() and not args.retrain:
        p_qat = dict(np.load(CACHE_QAT))
    else:
        print("ternary quantization-aware fine-tune (BitNet-style)")
        p_qat = mnist.train(d, epochs=3, lr=0.05, init=p, ternary=True)
        np.savez(CACHE_QAT, **p_qat)

    x, y = d["x_test"][: args.n_test], d["y_test"][: args.n_test]
    n_w = p["w1"].size + p["w2"].size
    float_acc = (mnist.predict_float(p, x) == y).mean()
    print(f"\nfloat32 accuracy: {float_acc:.4f}   ({n_w:,} weights)\n")

    calib = d["x_train"][:2000]
    models = {f: build_quant_model(p, f, calib) for f in qlib.FORMATS}
    models["ternary-qat"] = build_quant_model(p_qat, "ternary", calib)

    print("format      | bits | weight mem | GF180 512B SRAMs (area) | clean acc")
    print("------------|------|------------|-------------------------|----------")
    for label, m in models.items():
        f = m["fmt"]
        mem = qlib.memory_bytes(n_w, f)
        n_sram = int(np.ceil(mem / SRAM_BYTES))
        acc = (int_forward(m, x) == y).mean()
        print(f"{label:11s} | {qlib.FORMATS[f]:4d} | {mem / 1024:7.1f} KB | "
              f"{n_sram:4d} ({n_sram * SRAM_MM2:5.1f} mm^2)       | {acc:.4f}")

    rates = [1e-4, 1e-3, 1e-2]
    rng = np.random.default_rng(0)
    print(f"\naccuracy under random bit flips (per stored bit, avg of {args.trials})")
    print("format                  | " + " | ".join(f"p={r:g}" for r in rates))
    print("------------------------|" + "|".join("-" * 10 for _ in rates))
    rows = [(label, m, True) for label, m in models.items()]
    rows.append(("ternary-qat (no detect)", models["ternary-qat"], False))
    for label, m, detect in rows:
        cells = []
        for r in rates:
            acc, caught = faulty_accuracy(m, x, y, r, args.trials, rng, detect)
            cells.append(f"{acc:.4f}" + (f" ({caught:.0f} caught)" if caught and detect else ""))
        print(f"{label:23s} | " + " | ".join(cells))

    print("\nexporting golden vectors for RTL")
    export_vectors(models["int8"], models["ternary-qat"], x)


if __name__ == "__main__":
    main()

"""MNIST download + a tiny 2-layer MLP (784 -> 128 -> 10) trained in NumPy.

MNIST is a placeholder workload so the pipeline works end to end. Swap in a
satellite-image dataset (e.g. 38-Cloud, CloudSEN12) once the team picks one.
"""
import gzip
import urllib.request
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parents[1] / "data" / "mnist"
URL = "https://storage.googleapis.com/cvdf-datasets/mnist/"
FILES = {
    "x_train": "train-images-idx3-ubyte.gz",
    "y_train": "train-labels-idx1-ubyte.gz",
    "x_test": "t10k-images-idx3-ubyte.gz",
    "y_test": "t10k-labels-idx1-ubyte.gz",
}


def load():
    DATA.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, name in FILES.items():
        path = DATA / name
        if not path.exists():
            print(f"downloading {name}")
            urllib.request.urlretrieve(URL + name, path)
        with gzip.open(path) as f:
            raw = np.frombuffer(f.read(), np.uint8)
        if key.startswith("x"):
            out[key] = raw[16:].reshape(-1, 784).astype(np.float32) / 255.0
        else:
            out[key] = raw[8:].astype(np.int64)
    return out


def ternarize(w):
    """BitNet b1.58 absmean: forward pass sees only scale * {-1, 0, +1}."""
    s = np.abs(w).mean()
    return np.clip(np.round(w / s), -1, 1) * s


def train(d, hidden=128, epochs=5, lr=0.1, batch=64, seed=0, init=None, ternary=False):
    """Plain SGD with momentum. Returns float weights dict.

    ternary=True is quantization-aware training (QAT): the forward pass uses
    ternarized weights, gradients update the hidden float weights
    ("straight-through estimator"). This is how BitNet keeps accuracy.
    """
    rng = np.random.default_rng(seed)
    if init is not None:
        p = {k: a.copy() for k, a in init.items()}
    else:
        p = {
            "w1": rng.normal(0, np.sqrt(2 / 784), (hidden, 784)).astype(np.float32),
            "b1": np.zeros(hidden, np.float32),
            "w2": rng.normal(0, np.sqrt(2 / hidden), (10, hidden)).astype(np.float32),
            "b2": np.zeros(10, np.float32),
        }
    q = ternarize if ternary else (lambda w: w)
    v = {k: np.zeros_like(a) for k, a in p.items()}
    x, y = d["x_train"], d["y_train"]
    for ep in range(epochs):
        order = rng.permutation(len(x))
        for i in range(0, len(x), batch):
            idx = order[i : i + batch]
            xb, yb = x[idx], y[idx]
            w1, w2 = q(p["w1"]), q(p["w2"])
            h = np.maximum(0, xb @ w1.T + p["b1"])
            logits = h @ w2.T + p["b2"]
            prob = np.exp(logits - logits.max(1, keepdims=True))
            prob /= prob.sum(1, keepdims=True)
            g = prob
            g[np.arange(len(yb)), yb] -= 1
            g /= len(yb)
            grads = {"w2": g.T @ h, "b2": g.sum(0)}
            gh = (g @ w2) * (h > 0)
            grads["w1"] = gh.T @ xb
            grads["b1"] = gh.sum(0)
            for k in p:
                v[k] = 0.9 * v[k] - lr * grads[k]
                p[k] += v[k]
        acc = (predict_float(p, d["x_test"], ternary) == d["y_test"]).mean()
        print(f"  epoch {ep + 1}: {'ternary' if ternary else 'float'} test acc {acc:.4f}")
    return p


def predict_float(p, x, ternary=False):
    q = ternarize if ternary else (lambda w: w)
    h = np.maximum(0, x @ q(p["w1"]).T + p["b1"])
    return (h @ q(p["w2"]).T + p["b2"]).argmax(1)

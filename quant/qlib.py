"""Quantization + bit-flip fault injection, in plain NumPy so every step is visible.

Formats (all symmetric, per-tensor -- simplest for hardware):
  int8    : weights in [-127, 127], stored as 8-bit two's complement
  int4    : weights in [-7, 7],     stored as 4-bit two's complement
  ternary : weights in {-1, 0, +1}, stored as 2 bits:
              00 -> 0, 01 -> +1, 10 -> -1, 11 -> INVALID (a bit flipped!)

real_value ~= integer * scale
"""
import numpy as np

FORMATS = {"int8": 8, "int4": 4, "ternary": 2}  # name -> stored bits per weight

TERNARY_ENCODE = {0: 0b00, 1: 0b01, -1: 0b10}
TERNARY_INVALID = 0b11


# ---------------------------------------------------------------- quantize
def quantize(w: np.ndarray, fmt: str):
    """Float weights -> (integer weights, scale)."""
    if fmt == "ternary":
        # BitNet b1.58 "absmean": scale by the mean magnitude, round to -1/0/+1
        scale = np.abs(w).mean()
        q = np.clip(np.round(w / scale), -1, 1)
    else:
        bits = FORMATS[fmt]
        qmax = 2 ** (bits - 1) - 1  # 127 for int8, 7 for int4
        scale = np.abs(w).max() / qmax
        q = np.clip(np.round(w / scale), -qmax, qmax)
    return q.astype(np.int32), float(scale)


def quantize_activations(x: np.ndarray, scale: float):
    """Activations are always int8 (the 'A8' in W8A8)."""
    return np.clip(np.round(x / scale), -127, 127).astype(np.int32)


# ---------------------------------------------------------------- storage
def encode(q: np.ndarray, fmt: str) -> np.ndarray:
    """Integer weights -> raw stored bit patterns (what sits in SRAM)."""
    if fmt == "ternary":
        codes = np.zeros_like(q, dtype=np.uint8)
        codes[q == 1] = TERNARY_ENCODE[1]
        codes[q == -1] = TERNARY_ENCODE[-1]
        return codes
    bits = FORMATS[fmt]
    return (q & ((1 << bits) - 1)).astype(np.uint8)  # two's complement


def decode(codes: np.ndarray, fmt: str, detect: bool = True):
    """Raw bit patterns -> integer weights. Returns (q, n_detected_errors).

    For ternary, the invalid code 11 is caught for free and zeroed out
    (a zero weight is the safest guess) when detect=True.
    """
    if fmt == "ternary":
        q = np.zeros(codes.shape, dtype=np.int32)
        q[codes == 0b01] = 1
        q[codes == 0b10] = -1
        bad = codes == TERNARY_INVALID
        if not detect:
            # without detection, hardware that only looks at the sign bit
            # would read 11 as -1
            q[bad] = -1
        return q, int(bad.sum())
    bits = FORMATS[fmt]
    q = codes.astype(np.int32)
    q[q >= (1 << (bits - 1))] -= 1 << bits  # sign-extend
    return q, 0


def flip_bits(codes: np.ndarray, fmt: str, p: float, rng) -> np.ndarray:
    """Flip every stored bit independently with probability p (radiation model)."""
    out = codes.copy()
    for b in range(FORMATS[fmt]):
        hit = rng.random(codes.shape) < p
        out[hit] ^= np.uint8(1 << b)
    return out


def memory_bytes(n_weights: int, fmt: str) -> float:
    return n_weights * FORMATS[fmt] / 8


# ---------------------------------------------------------------- requantize
# The chip has no floating point. After a layer, the int32 accumulator is
# turned back into an int8 activation with one multiply, one add, one shift:
#
#     y = (acc * m + b + 2^(sh-1)) >> sh        (>> = arithmetic shift, rounds)
#     out = clamp(y, 0 or -127, 127)            (ReLU = lower bound 0)
#
# m (signed 16-bit) and sh encode the float multiplier M ~= m / 2^sh;
# b (signed 48-bit) is the per-neuron bias already scaled by 2^sh.
M_BITS, B_BITS = 16, 48


def fixed_multiplier(M: float):
    """Float multiplier -> (m, sh) with m as many bits as fit in signed 16."""
    assert M > 0
    sh = 0
    while round(M * 2 ** (sh + 1)) < 2 ** (M_BITS - 1) and sh < 40:
        sh += 1
    return int(round(M * 2 ** sh)), sh


def requant(acc, m: int, b, sh: int, relu: bool):
    """Bit-exact model of rtl/postproc.sv. Returns (wide int32, int8)."""
    acc = np.asarray(acc, dtype=object)
    y = (acc * m + np.asarray(b, dtype=object) + (1 << (sh - 1))) >> sh
    wide = np.clip(y, -2 ** 31, 2 ** 31 - 1).astype(np.int64)
    q = np.clip(y, 0 if relu else -127, 127).astype(np.int32)
    return wide, q

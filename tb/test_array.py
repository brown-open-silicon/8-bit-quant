"""cocotb tests for the 16x16 ternary systolic array.

1. golden_layer1: computes real MNIST layer-1 outputs (16 neurons x 8 images)
   by streaming 49 weight tiles through the array; must match Python exactly.
2. random_tiles:  random weights/activations, checks every output + latency.
3. bitflip_flag:  a weight stored as 11 is treated as 0 and raises err.
Edge cases (issue #3):
4. zero_weights:      all-zero weights give 0 for any input (and no err).
5. extreme_sums:      all +1 / all -1 weights with -128 / +127 inputs hit the
                      largest |c| = 16*128 = 2048 without wrapping.
6. one_hot_mapping:   a single +1 at W[k][n] must route a[k] to c[n] only, for
                      every (k, n): catches swapped rows/columns or skew bugs.
7. gapped_stream:     inputs with idle cycles between them come out unchanged
                      and in order (no stale partial sums leak between vectors).
8. weight_reload:     load tile A, run, load tile B, run: no leftovers from A.
"""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N, PSUM_W = 16, 16
LAT = 2 * N - 1
DECODE = {0b00: 0, 0b01: 1, 0b10: -1, 0b11: 0}
VECTORS = Path(__file__).parent / "vectors"


def pack(values, width):
    word = 0
    for i, v in enumerate(values):
        word |= (v & ((1 << width) - 1)) << (width * i)
    return word


def unpack_signed(word, width, count):
    out = []
    for i in range(count):
        v = (word >> (width * i)) & ((1 << width) - 1)
        out.append(v - (1 << width) if v >> (width - 1) else v)
    return out


async def reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for sig in (dut.rst_n, dut.w_load, dut.w_row, dut.w_data,
                dut.in_valid, dut.a_vec, dut.err_clear):
        sig.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def load_weights(dut, w_codes):
    """w_codes[k][n] = 2-bit code for W[k][n]."""
    await FallingEdge(dut.clk)
    for k in range(N):
        dut.w_load.value = 1
        dut.w_row.value = k
        dut.w_data.value = pack(w_codes[k], 2)
        await FallingEdge(dut.clk)
    dut.w_load.value = 0


async def stream(dut, a_rows):
    """Feed one input vector per cycle; return outputs and observed latency."""
    outputs, start, first_out, cycle = [], None, None, 0
    pending = list(a_rows)
    while len(outputs) < len(a_rows):
        if pending:
            dut.in_valid.value = 1
            dut.a_vec.value = pack(pending.pop(0), 8)
            if start is None:
                start = cycle
        else:
            dut.in_valid.value = 0
        await FallingEdge(dut.clk)
        cycle += 1
        if dut.out_valid.value == 1:
            if first_out is None:
                first_out = cycle
            outputs.append(unpack_signed(int(dut.c_vec.value), PSUM_W, N))
        assert cycle < len(a_rows) + LAT + 5, "out_valid never arrived"
    dut.in_valid.value = 0
    return outputs, first_out - start


def ref_tile(a_rows, w_codes):
    return [[sum(a[k] * DECODE[w_codes[k][n]] for k in range(N)) for n in range(N)]
            for a in a_rows]


@cocotb.test()
async def golden_layer1(dut):
    await reset(dut)
    data = json.loads((VECTORS / "array_ternary.json").read_text())
    n_img = len(data["expected"])
    acc = [[0] * N for _ in range(n_img)]
    for t in data["tiles"]:
        await load_weights(dut, t["w"])
        out, _ = await stream(dut, t["a"])
        for i in range(n_img):
            for n in range(N):
                acc[i][n] += out[i][n]
    assert acc == data["expected"], "layer-1 outputs differ from Python golden model"
    assert dut.err.value == 0
    dut._log.info(f"{len(data['tiles'])} tiles -> {n_img}x{N} layer-1 outputs match Python")


@cocotb.test()
async def random_tiles(dut):
    await reset(dut)
    rng = random.Random(7)
    for trial in range(5):
        w = [[rng.choice([0b00, 0b01, 0b10]) for _ in range(N)] for _ in range(N)]
        a = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(20)]
        if trial == 0:  # worst case: every weight +1 or -1, every input -128
            w = [[0b01] * N for _ in range(N)]
            a = [[-128] * N, [127] * N]
        await load_weights(dut, w)
        out, lat = await stream(dut, a)
        assert lat == LAT, f"latency {lat}, expected {LAT}"
        assert out == ref_tile(a, w), f"trial {trial}: mismatch"
    dut._log.info(f"random tiles match, latency = {LAT} cycles")


@cocotb.test()
async def bitflip_flag(dut):
    await reset(dut)
    rng = random.Random(3)
    w = [[rng.choice([0b00, 0b01, 0b10]) for _ in range(N)] for _ in range(N)]
    await load_weights(dut, w)
    await FallingEdge(dut.clk)
    assert dut.err.value == 0
    w[5][9] = 0b11  # simulate a radiation-flipped weight
    await load_weights(dut, w)
    a = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(4)]
    out, _ = await stream(dut, a)
    assert out == ref_tile(a, w), "invalid weight not treated as zero"
    assert dut.err.value == 1, "bit flip not flagged"
    # repair the weight (e.g. reload from protected memory), then clear the flag
    w[5][9] = 0b00
    await load_weights(dut, w)
    dut.err_clear.value = 1
    await FallingEdge(dut.clk)
    dut.err_clear.value = 0
    await FallingEdge(dut.clk)
    assert dut.err.value == 0, "err did not clear"


async def stream_gapped(dut, a_rows, gaps):
    """Like stream(), but idle gaps[i] cycles after input i."""
    outputs, cycle = [], 0
    sched = []
    for a, g in zip(a_rows, gaps):
        sched.append(a)
        sched.extend([None] * g)
    limit = len(sched) + LAT + 5
    while len(outputs) < len(a_rows):
        item = sched.pop(0) if sched else None
        dut.in_valid.value = 0 if item is None else 1
        if item is not None:
            dut.a_vec.value = pack(item, 8)
        await FallingEdge(dut.clk)
        cycle += 1
        if dut.out_valid.value == 1:
            outputs.append(unpack_signed(int(dut.c_vec.value), PSUM_W, N))
        assert cycle < limit, "out_valid never arrived"
    dut.in_valid.value = 0
    return outputs


@cocotb.test()
async def zero_weights(dut):
    await reset(dut)
    rng = random.Random(11)
    await load_weights(dut, [[0b00] * N for _ in range(N)])
    a = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(8)] + [[-128] * N, [127] * N]
    out, _ = await stream(dut, a)
    assert out == [[0] * N] * len(a), "zero weights must give zero outputs"
    assert dut.err.value == 0


@cocotb.test()
async def extreme_sums(dut):
    await reset(dut)
    for code, sign in ((0b01, 1), (0b10, -1)):
        await load_weights(dut, [[code] * N for _ in range(N)])
        a = [[-128] * N, [127] * N, [-128, 127] * (N // 2)]
        out, _ = await stream(dut, a)
        exp = [[sign * -128 * N] * N, [sign * 127 * N] * N, [sign * (-128 + 127) * (N // 2)] * N]
        assert out == exp, f"weights {code:02b}: {out[:2]} != {exp[:2]}"
    dut._log.info(f"|c| max = {128 * N} reached for +1 and -1 weights, no wrap")


@cocotb.test()
async def one_hot_mapping(dut):
    await reset(dut)
    rng = random.Random(12)
    a = [[rng.choice([v for v in range(-128, 128) if v]) for _ in range(N)]]
    for k in range(N):
        for n in range(N):
            w = [[0b00] * N for _ in range(N)]
            w[k][n] = 0b01
            await load_weights(dut, w)
            out, _ = await stream(dut, a)
            exp = [0] * N
            exp[n] = a[0][k]
            assert out[0] == exp, f"W[{k}][{n}]=+1: got {out[0]}, expected a[{k}] at c[{n}]"
    dut._log.info(f"all {N * N} weight positions route to the right output")


@cocotb.test()
async def gapped_stream(dut):
    await reset(dut)
    rng = random.Random(13)
    w = [[rng.choice([0b00, 0b01, 0b10]) for _ in range(N)] for _ in range(N)]
    await load_weights(dut, w)
    a = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(12)]
    gaps = [rng.choice([0, 0, 1, 2, 5, LAT]) for _ in a]
    out = await stream_gapped(dut, a, gaps)
    assert out == ref_tile(a, w), "gaps between inputs changed the results"


@cocotb.test()
async def weight_reload(dut):
    await reset(dut)
    rng = random.Random(14)
    a = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(6)]
    for _ in range(3):
        w = [[rng.choice([0b00, 0b01, 0b10]) for _ in range(N)] for _ in range(N)]
        await load_weights(dut, w)
        out, _ = await stream(dut, a)
        assert out == ref_tile(a, w), "results depend on the previous weight tile"

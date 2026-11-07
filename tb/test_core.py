"""cocotb tests for core_ternary (16x16 array + int32 accumulator buffer).

1. golden_layer1_onchip: the full MNIST layer-1 dot products (784 inputs =
   49 K-tiles, 16 neurons x 8 images) are summed ON CHIP; reading the
   accumulator must match Python exactly.
2. random_multitile: random K-tile counts / vector counts / addresses.
(Overflow is tested on accum_buf alone with a narrow ACC_W: tb/test_accum.py.)
"""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N, PSUM_W, ACC_W, DEPTH = 16, 16, 32, 16
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
    for sig in (dut.rst_n, dut.w_load, dut.w_row, dut.w_data, dut.in_valid,
                dut.in_first, dut.in_addr, dut.a_vec, dut.rd_en, dut.rd_addr,
                dut.err_clear, dut.pp_m, dut.pp_sh, dut.pp_relu, dut.pp_bias):
        sig.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def load_weights(dut, w_codes):
    for k in range(N):
        dut.w_load.value = 1
        dut.w_row.value = k
        dut.w_data.value = pack(w_codes[k], 2)
        await FallingEdge(dut.clk)
    dut.w_load.value = 0


async def stream_tile(dut, a_rows, addrs, first):
    """Push one vector per cycle with its accumulator tag, then wait to drain."""
    for a, addr in zip(a_rows, addrs):
        dut.in_valid.value = 1
        dut.in_first.value = int(first)
        dut.in_addr.value = addr
        dut.a_vec.value = pack(a, 8)
        await FallingEdge(dut.clk)
    dut.in_valid.value = 0
    for _ in range(2 * N + 5):
        if dut.busy.value == 0:
            break
        await FallingEdge(dut.clk)
    assert dut.busy.value == 0, "pipeline did not drain"
    await FallingEdge(dut.clk)  # let the final accumulator write land


async def read_rows(dut, addrs):
    out = []
    for addr in addrs:
        dut.rd_en.value = 1
        dut.rd_addr.value = addr
        await FallingEdge(dut.clk)
        dut.rd_en.value = 0
        assert dut.rd_valid.value == 1
        out.append(unpack_signed(int(dut.rd_vec.value), ACC_W, N))
    return out


async def run_layer(dut, tiles, addrs):
    """tiles: list of (w_codes, a_rows). Returns accumulator rows for addrs."""
    for t, (w, a) in enumerate(tiles):
        await load_weights(dut, w)
        await stream_tile(dut, a, addrs, first=(t == 0))
    return await read_rows(dut, addrs)


def ref_layer(tiles, n_vec):
    acc = [[0] * N for _ in range(n_vec)]
    for w, a in tiles:
        for i in range(n_vec):
            for n in range(N):
                acc[i][n] += sum(a[i][k] * DECODE[w[k][n]] for k in range(N))
    return acc


@cocotb.test()
async def golden_layer1_onchip(dut):
    await reset(dut)
    data = json.loads((VECTORS / "array_ternary.json").read_text())
    tiles = [(t["w"], t["a"]) for t in data["tiles"]]
    n_img = len(data["expected"])
    got = await run_layer(dut, tiles, list(range(n_img)))
    assert got == data["expected"], "on-chip accumulation differs from Python"
    assert dut.err.value == 0 and dut.ovf.value == 0
    dut._log.info(f"{len(tiles)} K-tiles accumulated on chip -> "
                  f"{n_img}x{N} layer-1 outputs match Python")


@cocotb.test()
async def random_multitile(dut):
    await reset(dut)
    rng = random.Random(11)
    for trial in range(4):
        n_tiles = rng.randint(1, 6)
        n_vec = rng.randint(1, DEPTH)
        addrs = rng.sample(range(DEPTH), n_vec)  # scattered, non-contiguous rows
        tiles = []
        for _ in range(n_tiles):
            w = [[rng.choice([0b00, 0b01, 0b10]) for _ in range(N)] for _ in range(N)]
            a = [[rng.randint(-128, 127) for _ in range(N)] for _ in range(n_vec)]
            tiles.append((w, a))
        got = await run_layer(dut, tiles, addrs)
        assert got == ref_layer(tiles, n_vec), f"trial {trial} mismatch"
    dut._log.info("random multi-tile accumulation matches")


# ------------------------------------------------------------ full model
B_W = 48


async def read_requant(dut, addrs, m, sh, bias, relu):
    """Read accumulator rows through postproc; returns (int32 rows, int8 rows)."""
    dut.pp_m.value = m & 0xFFFF
    dut.pp_sh.value = sh
    dut.pp_relu.value = int(relu)
    dut.pp_bias.value = pack(bias, B_W)
    wide, q = [], []
    for addr in addrs:
        dut.rd_en.value = 1
        dut.rd_addr.value = addr
        await FallingEdge(dut.clk)
        dut.rd_en.value = 0
        for _ in range(N + 4):
            await FallingEdge(dut.clk)
            if dut.pp_valid.value == 1:
                break
        assert dut.pp_valid.value == 1, "postproc result never arrived"
        wide.append(unpack_signed(int(dut.wide_vec.value), 32, N))
        q.append(unpack_signed(int(dut.q_vec.value), 8, N))
    return wide, q


def weight_tile(w_codes, n0, k0):
    """W[k][n] tile from codes[neuron][input]; pads missing neurons with 00 (zero)."""
    return [[w_codes[n0 + n][k0 + k] if n0 + n < len(w_codes) else 0
             for n in range(N)] for k in range(N)]


async def run_dense(dut, x_rows, w_codes, m, sh, bias, relu):
    """One full layer: every 16-neuron group x every 16-input chunk."""
    n_vec, n_in, n_out = len(x_rows), len(x_rows[0]), len(w_codes)
    addrs = list(range(n_vec))
    out_w = [[] for _ in range(n_vec)]
    out_q = [[] for _ in range(n_vec)]
    for n0 in range(0, n_out, N):
        for t, k0 in enumerate(range(0, n_in, N)):
            await load_weights(dut, weight_tile(w_codes, n0, k0))
            await stream_tile(dut, [r[k0:k0 + N] for r in x_rows], addrs, first=(t == 0))
        b = [bias[n0 + n] if n0 + n < n_out else 0 for n in range(N)]
        wide, q = await read_requant(dut, addrs, m, sh, b, relu)
        keep = min(N, n_out - n0)
        for i in range(n_vec):
            out_w[i] += wide[i][:keep]
            out_q[i] += q[i][:keep]
    return out_w, out_q


@cocotb.test()
async def full_model_mnist(dut):
    """The whole 784-128-10 ternary network runs on the RTL:
    layer 1 (8 neuron groups x 49 chunks) -> requant+ReLU -> layer 2 (8 chunks)
    -> logits. Must match Python bit-for-bit, then we score the predictions."""
    await reset(dut)
    d = json.loads((VECTORS / "e2e_ternary.json").read_text())
    n_img = len(d["xq"])
    hq, preds = [], []
    for b0 in range(0, n_img, DEPTH):                      # 16 images per batch
        x = d["xq"][b0:b0 + DEPTH]
        _, h = await run_dense(dut, x, d["w1"], d["m1"], d["sh1"], d["b1"], relu=True)
        logits, _ = await run_dense(dut, h, d["w2"], d["m2"], d["sh2"], d["b2"], relu=False)
        assert h == d["hq"][b0:b0 + DEPTH], f"hidden layer mismatch in batch {b0 // DEPTH}"
        assert logits == d["logits"][b0:b0 + DEPTH], f"logits mismatch in batch {b0 // DEPTH}"
        hq += h
        preds += [max(range(10), key=lambda c: row[c]) for row in logits]
    assert preds == d["pred"]
    correct = sum(p == y for p, y in zip(preds, d["label"]))
    assert dut.err.value == 0 and dut.ovf.value == 0
    dut._log.info(f"full model on RTL: {n_img} images bit-exact vs Python, "
                  f"{correct}/{n_img} correct ({100 * correct / n_img:.1f}%)")

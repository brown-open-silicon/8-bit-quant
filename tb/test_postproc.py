"""postproc: int32 accumulator -> int8, bit-exact vs quant/qlib.py requant().

Cases (tb/vectors/postproc.json): real MNIST layer-1 accumulators with the real
fixed-point scale + bias + ReLU; random full-range int32 for saturation and
rounding; a negative multiplier with large biases.
"""
import json
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N, ACC_W, B_W = 16, 32, 48
VECTORS = Path(__file__).parent / "vectors"


def pack(values, width):
    return sum((v & ((1 << width) - 1)) << (width * i) for i, v in enumerate(values))


def unpack_signed(word, width, count):
    out = []
    for i in range(count):
        v = (word >> (width * i)) & ((1 << width) - 1)
        out.append(v - (1 << width) if v >> (width - 1) else v)
    return out


@cocotb.test()
async def golden_requant(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for s in (dut.rst_n, dut.in_valid, dut.in_vec, dut.m, dut.sh, dut.relu, dut.bias_vec):
        s.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    cases = json.loads((VECTORS / "postproc.json").read_text())
    for c in cases:
        dut.m.value = c["m"] & 0xFFFF
        dut.sh.value = c["sh"]
        dut.relu.value = int(c["relu"])
        dut.bias_vec.value = pack(c["b"], B_W)
        got_w, got_q = [], []
        for row in c["acc"]:
            # 2-cycle pipeline: push one row, read it 2 cycles later
            dut.in_valid.value = 1
            dut.in_vec.value = pack(row, ACC_W)
            await FallingEdge(dut.clk)
            dut.in_valid.value = 0
            await FallingEdge(dut.clk)
            assert dut.out_valid.value == 1
            got_w.append(unpack_signed(int(dut.wide_vec.value), 32, N))
            got_q.append(unpack_signed(int(dut.q_vec.value), 8, N))
        assert got_w == c["wide"], f"wide mismatch (m={c['m']}, sh={c['sh']})"
        assert got_q == c["q"], f"int8 mismatch (m={c['m']}, sh={c['sh']}, relu={c['relu']})"
    dut._log.info(f"{len(cases)} requant cases match Python bit-for-bit")

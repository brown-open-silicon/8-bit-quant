"""cocotb tests: the RTL must reproduce the Python golden dot products exactly.

Golden vectors come from quant/experiment.py (real MNIST layer-1 data).
Run via:  make sim   (inside the IIC-OSIC-TOOLS container)
"""
import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

VECTORS = Path(__file__).parent / "vectors"
TOP = os.environ.get("COCOTB_TOPLEVEL", "")


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.rst_n.value = 0
    dut.clear.value = 0
    dut.en.value = 0
    dut.a.value = 0
    dut.w.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def dot(dut, a, w):
    """Stream one dot product through the PE, return the accumulator."""
    await FallingEdge(dut.clk)
    dut.clear.value = 1
    await FallingEdge(dut.clk)
    dut.clear.value = 0
    dut.en.value = 1
    for ai, wi in zip(a, w):
        dut.a.value = ai
        dut.w.value = wi
        await FallingEdge(dut.clk)
    dut.en.value = 0
    return dut.acc.value.to_signed()


@cocotb.test(skip=TOP != "mac_int8")
async def mac_int8_golden(dut):
    await setup(dut)
    cases = json.loads((VECTORS / "mac_int8.json").read_text())
    for i, c in enumerate(cases):
        got = await dot(dut, c["a"], c["w"])
        assert got == c["expected"], f"case {i}: got {got}, expected {c['expected']}"
    dut._log.info(f"{len(cases)} golden dot products match")


@cocotb.test(skip=TOP != "mac_int8")
async def mac_int8_extremes(dut):
    await setup(dut)
    for a, w in [(-128, -128), (-128, 127), (127, 127), (-1, 1)]:
        got = await dot(dut, [a] * 1000, [w] * 1000)
        assert got == a * w * 1000, f"{a}*{w}*1000: got {got}"


@cocotb.test(skip=TOP != "pe_ternary")
async def pe_ternary_golden(dut):
    await setup(dut)
    cases = json.loads((VECTORS / "pe_ternary.json").read_text())
    for i, c in enumerate(cases):
        got = await dot(dut, c["a"], c["w"])
        assert got == c["expected"], f"case {i}: got {got}, expected {c['expected']}"
        assert dut.err.value == 0
    dut._log.info(f"{len(cases)} golden dot products match")


@cocotb.test(skip=TOP != "pe_ternary")
async def pe_ternary_detects_bitflip(dut):
    await setup(dut)
    rng = random.Random(1)
    a = [rng.randint(-128, 127) for _ in range(64)]
    w = [rng.choice([0b00, 0b01, 0b10]) for _ in range(64)]
    w[10] = 0b11  # simulate a radiation-flipped weight
    decoded = [{0b00: 0, 0b01: 1, 0b10: -1, 0b11: 0}[x] for x in w]
    got = await dot(dut, a, w)
    assert got == sum(x * y for x, y in zip(a, decoded))
    assert dut.err.value == 1, "invalid code 11 was not flagged"

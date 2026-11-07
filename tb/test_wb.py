"""wb_npu: the NPU driven only over Wishbone, like Caravel's CPU would.

1. registers:        ID, readback of config registers, bias packing.
2. full_model_bus:   the whole 784-128-10 MNIST network through the bus,
                     bit-exact vs Python; reports bus accesses per image.
3. bitflip_irq:      a weight stored as 11 raises STATUS.err and irq; CTRL clears it.
"""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

from npu_driver import BIAS, CTRL, ERR, ID, Npu, PP_CFG, STATUS, W_DATA

VECTORS = Path(__file__).parent / "vectors"


async def reset(dut):
    cocotb.start_soon(Clock(dut.wb_clk_i, 10, unit="ns").start())
    for s in (dut.wbs_stb_i, dut.wbs_cyc_i, dut.wbs_we_i, dut.wbs_sel_i,
              dut.wbs_dat_i, dut.wbs_adr_i):
        s.value = 0
    dut.wb_rst_i.value = 1
    await RisingEdge(dut.wb_clk_i)
    await FallingEdge(dut.wb_clk_i)
    dut.wb_rst_i.value = 0
    return Npu(dut)


@cocotb.test()
async def registers(dut):
    npu = await reset(dut)
    assert await npu.read(ID) == 0x4E505531
    await npu.write(W_DATA, 0xDEADBEEF)
    assert await npu.read(W_DATA) == 0xDEADBEEF
    await npu.write(PP_CFG, 0x0115ABCD)
    assert await npu.read(PP_CFG) == 0x0115ABCD
    b = -(1 << 40) + 12345                       # negative 48-bit bias, lane 7
    await npu.write(BIAS + 8 * 7, b & 0xFFFFFFFF)
    await npu.write(BIAS + 8 * 7 + 4, (b >> 32) & 0xFFFF)
    assert await npu.read(BIAS + 8 * 7) == b & 0xFFFFFFFF
    assert await npu.read(BIAS + 8 * 7 + 4) == (b >> 32) & 0xFFFF
    assert await npu.read(STATUS) == 0


@cocotb.test()
async def full_model_bus(dut):
    npu = await reset(dut)
    d = json.loads((VECTORS / "e2e_ternary.json").read_text())
    n_img = 16
    x = d["xq"][:n_img]
    h = await npu.dense(x, d["w1"], d["m1"], d["sh1"], d["b1"], relu=True)
    assert h == d["hq"][:n_img], "hidden layer mismatch over the bus"
    logits = await npu.dense(h, d["w2"], d["m2"], d["sh2"], d["b2"], relu=False, wide=True)
    assert logits == d["logits"][:n_img], "logits mismatch over the bus"
    preds = [max(range(10), key=lambda c: r[c]) for r in logits]
    correct = sum(p == y for p, y in zip(preds, d["label"][:n_img]))
    assert await npu.read(STATUS) & ERR == 0
    dut._log.info(f"full model over Wishbone: {n_img} images bit-exact, {correct}/{n_img} correct, "
                  f"{npu.n_access:,} bus accesses ({npu.n_access // n_img:,} per image)")


@cocotb.test()
async def bitflip_irq(dut):
    npu = await reset(dut)
    rng = random.Random(5)
    w = [[rng.choice([0, 1, 2]) for _ in range(16)] for _ in range(16)]
    w[3][11] = 0b11                              # radiation-flipped weight
    await npu.load_weights(w)
    await FallingEdge(dut.wb_clk_i)
    assert await npu.read(STATUS) & ERR, "bit flip not reported in STATUS"
    assert dut.irq.value == 1, "irq not raised"
    w[3][11] = 0
    await npu.load_weights(w)                    # repair from a good copy
    await npu.write(CTRL, 1)
    assert await npu.read(STATUS) & ERR == 0 and dut.irq.value == 0

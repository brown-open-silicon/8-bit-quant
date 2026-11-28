"""user_project_wrapper: the NPU as Caravel's CPU sees it (issue #4).

1. id_and_unmapped: ID at 0x3000_0000; unmapped and aliased addresses ack with 0
                    (no hang), and writes to them don't reach the NPU.
2. one_layer:       MNIST layer 2 (4 images) through the wrapper, bit-exact.
3. irq:             a flipped weight raises user_irq[0]; CTRL clears it.
"""
import json
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, with_timeout

from npu_driver import CTRL, ERR, ID, PP_CFG, STATUS, Npu

BASE = 0x3000_0000
VECTORS = Path(__file__).parent / "vectors"


async def reset(dut):
    cocotb.start_soon(Clock(dut.wb_clk_i, 10, unit="ns").start())
    for s in (dut.wbs_stb_i, dut.wbs_cyc_i, dut.wbs_we_i, dut.wbs_sel_i,
              dut.wbs_dat_i, dut.wbs_adr_i, dut.la_data_in, dut.la_oenb, dut.io_in,
              dut.user_clock2):
        s.value = 0
    dut.wb_rst_i.value = 1
    await RisingEdge(dut.wb_clk_i)
    await FallingEdge(dut.wb_clk_i)
    dut.wb_rst_i.value = 0
    return Npu(dut, base=BASE), Npu(dut, base=0)


@cocotb.test()
async def id_and_unmapped(dut):
    npu, raw = await reset(dut)
    assert await npu.read(ID) == 0x4E505531
    assert int(dut.io_oeb.value) == (1 << len(dut.io_oeb)) - 1, "all pads must be inputs"
    assert int(dut.io_out.value) == 0 and int(dut.la_data_out.value) == 0
    await npu.write(PP_CFG, 0x0102_0304)
    for addr in (0x3001_0000, 0x3002_0000, 0x3000_0800, 0x3000_0828, 0x30FF_0000):
        assert await with_timeout(raw.read(addr), 1000, "ns") == 0, f"{addr:#x} must read 0"
        await with_timeout(raw.write(addr, 0xFFFF_FFFF), 1000, "ns")
    assert await npu.read(PP_CFG) == 0x0102_0304, "an alias write leaked into the NPU"


@cocotb.test()
async def one_layer(dut):
    npu, _ = await reset(dut)
    d = json.loads((VECTORS / "e2e_ternary.json").read_text())
    out = await npu.dense(d["hq"][:4], d["w2"], d["m2"], d["sh2"], d["b2"],
                          relu=False, wide=True, wmem=True)
    assert out == d["logits"][:4], "layer 2 through the wrapper differs from Python"
    assert not await npu.read(STATUS) & ERR


@cocotb.test()
async def irq(dut):
    npu, _ = await reset(dut)
    rng = random.Random(4)
    w = [[rng.choice([0, 1, 2]) for _ in range(16)] for _ in range(16)]
    w[2][13] = 0b11                              # radiation-flipped weight
    await npu.load_weights(w)
    await FallingEdge(dut.wb_clk_i)
    assert dut.user_irq.value == 0b001, f"user_irq = {dut.user_irq.value}"
    w[2][13] = 0
    await npu.load_weights(w)
    await npu.write(CTRL, 1)
    assert dut.user_irq.value == 0

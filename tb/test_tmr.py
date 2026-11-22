"""cocotb tests for rtl/tmr_reg.sv: vote, self-repair, error flag."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

# always_ff @(posedge clk or negedge rst_n) begin

async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())  # clock: 10 ns period, runs forever
    dut.rst_n.value = 0          # hold reset
    dut.we.value = 0
    dut.d.value = 0
    await FallingEdge(dut.clk)   # wait for one clock
    dut.rst_n.value = 1          # release reset


async def write(dut, value):
    dut.d.value = value
    dut.we.value = 1
    await FallingEdge(dut.clk) # the rising edge in between stores it. is FallingEdge for negedge?
    dut.we.value = 0

@cocotb.test()
async def one_flip_is_repaired(dut):
    await setup(dut)
    value = 0x5A
    dut.d.value = value
    dut.we.value = 1
    await FallingEdge(dut.clk) # set dut.d into abc b/c we == 1
    dut.we.value = 0
    # dut.b.value = (value >> 1) -> this is not flipping the bit, it is shifiting it
    dut.a.value = (value ^ 0x01)
    await Timer(1, unit="ns") # let the changes go through
    assert dut.q.value == 0x5A, f"q = {dut.q.value}, expected 0x5A"

@cocotb.test()
async def two_flip_break_it(dut):
    await setup(dut)
    value = 0x5A
    dut.d.value = value
    dut.we.value = 1
    await FallingEdge(dut.clk) # set dut.d into abc b/c we == 1
    dut.we.value = 0
    dut.b.value = (value ^ 0x01)
    dut.c.value = (value ^ 0x01)
    await Timer(1, unit="ns") # let the changes go through
    
    assert dut.q.value != 0x5A, f"q = {dut.q.value}, did not expect 0x5A"
    assert dut.err.value == 1, f"err = {dut.err.value}, expected err == 1"

@cocotb.test() # <- what is this doing? just a test
async def write_and_read(dut):
    # device under test
    # ^ is this standard?
    await setup(dut)
    assert dut.q.value == 0, "reset should clear q"
    await write(dut, 0x5A)
    # 10 - A + 5 * 16 = 80 + 10 = 90?
    # 0101 1010 
    # 128 64 32 16, 8 4 2 1
    assert dut.q.value == 0x5A, f"q = {dut.q.value}, expected 0x5A"
    assert dut.err.value == 0

# command to run : scripts/eda.sh "python3 tb/run.py test_tmr"
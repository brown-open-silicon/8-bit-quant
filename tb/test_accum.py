"""accum_buf alone, built with ACC_W=16 so overflow is reachable (see tb/run.py)."""
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

N, W = 4, 16


def pack(vals):
    return sum((v & 0xFFFF) << (W * i) for i, v in enumerate(vals))


def unpack(word):
    out = []
    for i in range(N):
        v = (word >> (W * i)) & 0xFFFF
        out.append(v - 0x10000 if v & 0x8000 else v)
    return out


async def write(dut, addr, vals, first):
    dut.in_valid.value, dut.in_addr.value = 1, addr
    dut.in_first.value, dut.in_vec.value = int(first), pack(vals)
    await FallingEdge(dut.clk)
    dut.in_valid.value = 0


async def drain(dut):
    """Wait until the 2-stage accumulate pipeline has written everything."""
    while dut.busy.value:
        await FallingEdge(dut.clk)


async def read(dut, addr):
    await drain(dut)
    dut.rd_en.value, dut.rd_addr.value = 1, addr
    await FallingEdge(dut.clk)
    dut.rd_en.value = 0
    return unpack(int(dut.rd_vec.value))


@cocotb.test()
async def first_add_overflow(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for s in (dut.rst_n, dut.in_valid, dut.in_first, dut.in_addr, dut.in_vec,
              dut.rd_en, dut.rd_addr, dut.ovf_clear):
        s.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1

    await write(dut, 1, [5, -7, 100, 0], first=True)
    await write(dut, 1, [1, 2, -300, 9], first=False)
    await write(dut, 2, [42, 42, 42, 42], first=True)
    assert await read(dut, 1) == [6, -5, -200, 9]
    await write(dut, 1, [3, 3, 3, 3], first=True)          # first overwrites
    assert await read(dut, 1) == [3, 3, 3, 3]
    assert await read(dut, 2) == [42, 42, 42, 42]          # other row untouched
    assert dut.ovf.value == 0

    await write(dut, 0, [30000, -30000, 0, 0], first=True)
    await write(dut, 0, [30000, 0, 0, 0], first=False)     # 60000 > 32767
    await drain(dut)
    assert dut.ovf.value == 1, "positive overflow not flagged"
    dut.ovf_clear.value = 1
    await FallingEdge(dut.clk)
    dut.ovf_clear.value = 0
    assert dut.ovf.value == 0
    await write(dut, 0, [0, -30000, 0, 0], first=False)    # lane 1: -60000
    await drain(dut)
    assert dut.ovf.value == 1, "negative overflow not flagged"


@cocotb.test()
async def random_back_to_back(dut):
    """Random accumulates every cycle, often to the same row twice in a row
    (exercises forwarding), checked against a Python model."""
    import random
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for sig in (dut.in_valid, dut.in_first, dut.in_addr, dut.in_vec, dut.rd_en,
                dut.rd_addr, dut.ovf_clear):
        sig.value = 0
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    rng = random.Random(3)
    model = [[0] * N for _ in range(4)]
    for addr in range(4):                                  # initialize every row
        await write(dut, addr, [0] * N, first=True)
    prev = 0
    for _ in range(400):
        addr = prev if rng.random() < 0.5 else rng.randrange(4)
        first = rng.random() < 0.1
        vals = [rng.randint(-50, 50) for _ in range(N)]
        model[addr] = vals[:] if first else [a + v for a, v in zip(model[addr], vals)]
        dut.in_valid.value, dut.in_addr.value = 1, addr
        dut.in_first.value, dut.in_vec.value = int(first), pack(vals)
        await FallingEdge(dut.clk)
        prev = addr
        if rng.random() < 0.2:                             # sometimes a gap
            dut.in_valid.value = 0
            await FallingEdge(dut.clk)
    dut.in_valid.value = 0
    for addr in range(4):
        assert await read(dut, addr) == model[addr], f"row {addr}"
    assert dut.ovf.value == 0

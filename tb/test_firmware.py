"""firmware/npu.c driving the wb_npu RTL.

The C firmware is compiled for the host (-DNPU_HOST) into a shared library.
Its register reads/writes call back into Python, which turns each one into a
real Wishbone cycle on the simulated chip. The C code runs in its own thread
(cocotb bridge/resume), so it can block on the bus like it would on silicon.

firmware_full_model: the whole 784-128-10 MNIST network, run by the C code,
bit-exact against the Python model.
"""
import ctypes
import json
import subprocess
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

try:
    from cocotb import bridge, resume
except ImportError:                      # cocotb 2.0.x keeps them here
    from cocotb._bridge import bridge, resume

from npu_driver import Npu

ROOT = Path(__file__).resolve().parents[1]
VECTORS = Path(__file__).parent / "vectors"
N = 16


def build_lib(out_dir):
    so = Path(out_dir) / "libnpu_host.so"
    subprocess.run(["gcc", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC", "-DNPU_HOST",
                    "-o", str(so), str(ROOT / "firmware" / "npu.c")], check=True)
    return ctypes.CDLL(str(so))


def pack_rows(w, n_in, n_out):
    """w[n][k] 2-bit codes -> rows[((g * n_tiles) + t) * 16 + k], the layout npu.h expects."""
    n_tiles, groups = -(-n_in // N), -(-n_out // N)
    rows = []
    for g in range(groups):
        for t in range(n_tiles):
            for k in range(N):
                word = 0
                for n in range(N):
                    nn, kk = N * g + n, N * t + k
                    c = w[nn][kk] if nn < n_out and kk < n_in else 0
                    word |= (c & 3) << (2 * n)
                rows.append(word)
    return rows


def arr(ctype, values):
    return (ctype * len(values))(*values)


@cocotb.test()
async def firmware_full_model(dut):
    cocotb.start_soon(Clock(dut.wb_clk_i, 10, unit="ns").start())
    for s in (dut.wbs_stb_i, dut.wbs_cyc_i, dut.wbs_we_i, dut.wbs_sel_i,
              dut.wbs_dat_i, dut.wbs_adr_i):
        s.value = 0
    dut.wb_rst_i.value = 1
    await RisingEdge(dut.wb_clk_i)
    await FallingEdge(dut.wb_clk_i)
    dut.wb_rst_i.value = 0
    npu = Npu(dut)

    lib = build_lib(Path.cwd())
    WR = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32)
    RD = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32)

    @resume
    async def bus_wr(off, v):
        await npu.write(off, v)

    @resume
    async def bus_rd(off):
        return await npu.read(off)

    cb_wr, cb_rd = WR(bus_wr), RD(bus_rd)          # keep references alive
    lib.npu_host_bind(cb_wr, cb_rd)
    lib.npu_present.restype = ctypes.c_int
    lib.npu_dense.restype = ctypes.c_uint32
    lib.npu_dense.argtypes = [
        ctypes.POINTER(ctypes.c_int8), ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
        ctypes.c_int16, ctypes.c_uint8, ctypes.POINTER(ctypes.c_int64), ctypes.c_int,
        ctypes.POINTER(ctypes.c_int8), ctypes.POINTER(ctypes.c_int32)]

    d = json.loads((VECTORS / "e2e_ternary.json").read_text())
    n_img, n_in, n_hid, n_cls = 16, 784, 128, 10
    x = arr(ctypes.c_int8, [v for row in d["xq"][:n_img] for v in row])
    w1 = arr(ctypes.c_uint32, pack_rows(d["w1"], n_in, n_hid))
    w2 = arr(ctypes.c_uint32, pack_rows(d["w2"], n_hid, n_cls))
    b1, b2 = arr(ctypes.c_int64, d["b1"]), arr(ctypes.c_int64, d["b2"])
    h = (ctypes.c_int8 * (n_img * n_hid))()
    logits = (ctypes.c_int32 * (n_img * n_cls))()

    @bridge
    def firmware():                                # runs in a thread, like main() on the chip
        assert lib.npu_present() == 1
        s1 = lib.npu_dense(x, n_img, n_in, w1, n_hid, d["m1"], d["sh1"], b1, 1, h, None)
        s2 = lib.npu_dense(h, n_img, n_hid, w2, n_cls, d["m2"], d["sh2"], b2, 0, None, logits)
        return s1, s2

    s1, s2 = await firmware()
    assert not (s1 & 2) and not (s2 & 2), "bit-flip error flagged"
    hq = [list(h[i * n_hid:(i + 1) * n_hid]) for i in range(n_img)]
    lg = [list(logits[i * n_cls:(i + 1) * n_cls]) for i in range(n_img)]
    assert hq == d["hq"][:n_img], "hidden layer mismatch (C firmware)"
    assert lg == d["logits"][:n_img], "logits mismatch (C firmware)"
    preds = [max(range(n_cls), key=lambda c: r[c]) for r in lg]
    correct = sum(p == y for p, y in zip(preds, d["label"][:n_img]))
    dut._log.info(f"C firmware: {n_img} images bit-exact, {correct}/{n_img} correct, "
                  f"{npu.n_access:,} bus accesses ({npu.n_access // n_img:,}/image)")

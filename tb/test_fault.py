"""Fault-injection campaign on wb_npu (docs/radiation.md, item 5).

Each trial runs MNIST layer 2 (128 -> 10, 4 images, weights through the SRAM
buffer) and flips ONE stored bit at a random cycle, like a single-event upset.
The bit is picked uniformly over every state register in the design: SRAM,
PE weights and pipelines, accumulator, postproc, bus/config registers, TMR
copies. Each trial lands in one bucket:

  masked       right answer, no flag     (the flip didn't matter)
  detected     wrong answer, flagged     (STATUS.err: firmware knows to retry)
  corrected    right answer, flagged     (TMR repaired it, or flag only)
  SDC          wrong answer, NO flag     (silent data corruption: the bad one)
  timeout      firmware's poll limit tripped (it knows: reset and retry)
  hang         the bus itself stopped answering

  FI_TRIALS=500 python3 tb/run.py fault     # campaign size (default 40)
  FI_SEED=1 ...                              # different random draw
Writes build/fault_results.json with every trial.
"""
import json
import os
import random
from pathlib import Path

import cocotb
import cocotb.utils
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, with_timeout

from npu_driver import ERR, STATUS, Npu, NpuTimeout

VECTORS = Path(__file__).parent / "vectors"
OUT = Path(__file__).parent.parent / "build" / "fault_results.json"
N, LAT = 16, 31


def sites():
    """(path, width, region): every state register, one entry per scalar element."""
    s = []
    def add(region, path, width, count=None):
        if count is None:
            s.append((path, width, region))
        else:
            for i in range(count):
                s.append((f"{path}[{i}]", width, region))
    # bus + config registers (wb_npu)
    for name, w in [("adr_q", 32), ("dat_q", 32), ("we_q", 1), ("sel_q", 4), ("act", 1),
                    ("mem_pend", 1), ("rd_pend", 1), ("bias_pend", 1), ("bias_en", 32),
                    ("wbs_ack_o", 1), ("wbs_dat_o", 32), ("ld_run", 1), ("ld_v", 1),
                    ("ld_tile", 4), ("ld_k", 4), ("ld_kd", 4), ("wp_go", 1), ("wp_row", 8),
                    ("wp_mask", 4), ("wp_bits", 4), ("pexp0", 4), ("pexp1", 4),
                    ("w_load", 1), ("in_valid", 1), ("rd_en", 1), ("err_clear", 1),
                    ("w_row", 4), ("in_addr", 4), ("rd_addr", 4), ("in_first", 1),
                    ("rd_misc", 32), ("rd_wide", 32), ("rd_bias", 32), ("rd_grp", 2),
                    ("res_ready", 1), ("cfg_err", 1), ("bias_err", 1), ("wmem_err", 1),
                    ("tag_err", 1), ("acc_err", 1)]:
        add("bus/ctrl", name, w)
    for name, w in [("w_data", 32), ("a_vec", 128), ("q_res", 128), ("wide_res", 512)]:
        add("data regs", name, w)
    add("BIAS", "bias", 768)
    add("BIAS", "bias_par", 32)
    for c in "abc":
        add("PP_CFG (TMR)", f"u_ppcfg.u{c}.r", 32)
    add("WMEM parity", "wpar", 4, 256)
    add("weight SRAM", "u_wmem.mem", 32, 256)
    # core
    for t in range(LAT):
        for c in "abc":
            add("row tags (TMR)", f"u_core.g_tag[{t}].u_tag.u{c}.r", 6)
    for k in range(N):
        for n in range(N):
            pe = f"u_core.u_array.g_row[{k}].g_col[{n}].pe"
            add("PE weights", f"{pe}.w", 2)
            add("PE pipeline", f"{pe}.a_out", 8)
            add("PE pipeline", f"{pe}.psum_out", 16)
    for k in range(1, N):
        add("PE pipeline", f"u_core.u_array.g_skew[{k}].g_delay.sr", 8, k)
    for n in range(N - 1):
        add("PE pipeline", f"u_core.u_array.g_deskew[{n}].g_delay.sr", 16, N - 1 - n)
    add("PE pipeline", "u_core.u_array.vsr", LAT)            # unused since the TMR tag valid replaced it
    add("bus/ctrl", "u_core.u_array.err", 1)
    add("accumulator", "u_core.u_acc.mem", 32, 16 * N)   # [DEPTH][N], flattened by the simulator
    add("accumulator", "u_core.u_acc.par", N, 16)
    add("accumulator", "u_core.u_acc.rd_par", N)
    add("accumulator", "u_core.u_acc.chk1", 1)
    for n in range(N):
        add("accumulator", f"u_core.u_acc.g_lane[{n}].x1", 32)
        add("accumulator", f"u_core.u_acc.g_lane[{n}].base1", 32)
        add("accumulator", f"u_core.u_acc.g_lane[{n}].bpar1", 1)
    for name, w in [("v1", 1), ("a1", 4), ("rd_vec", 512), ("rd_valid", 1), ("ovf", 1)]:
        add("accumulator", f"u_core.u_acc.{name}", w)
    for name, w in [("acc_q", 512), ("g", 4), ("g0", 4), ("g1", 4), ("g2", 4), ("run", 1),
                    ("v0", 1), ("v1", 1), ("v2", 1), ("out_valid", 1), ("wide_vec", 512),
                    ("q_vec", 128), ("g_lane[0].acc", 32), ("g_lane[0].b", 48),
                    ("g_lane[0].s1", 50), ("g_lane[0].y2", 50)]:
        add("postproc", f"u_core.u_pp.{name}", w)
    return s


def resolve(dut, path):
    h = dut
    for part in path.split("."):
        while part:
            if "[" in part:
                name, rest = part.split("[", 1)
                if name:
                    h = getattr(h, name)
                idx, part = rest.split("]", 1)
                h = h[int(idx)]
            else:
                h = getattr(h, part)
                part = ""
    return h


def flip(dut, path, bit):
    h = resolve(dut, path)
    v = h.value
    if not v.is_resolvable:                      # X/Z (e.g. SRAM word never written)
        return False
    h.value = int(v) ^ (1 << bit)
    return True


async def reset(dut):
    for sig in (dut.wbs_stb_i, dut.wbs_cyc_i, dut.wbs_we_i, dut.wbs_sel_i,
                dut.wbs_dat_i, dut.wbs_adr_i):
        sig.value = 0
    dut.wb_rst_i.value = 1
    await RisingEdge(dut.wb_clk_i)
    await FallingEdge(dut.wb_clk_i)
    dut.wb_rst_i.value = 0
    return Npu(dut)


async def run_layer2(dut, d, n_img):
    npu = await reset(dut)
    npu.poll_max = 2000                          # trips well before the hang watchdog
    out = await npu.dense(d["hq"][:n_img], d["w2"], d["m2"], d["sh2"], d["b2"],
                          relu=False, wide=True, wmem=True)
    return out, await npu.read(STATUS)


@cocotb.test()
async def fault_campaign(dut):
    cocotb.start_soon(Clock(dut.wb_clk_i, 10, unit="ns").start())
    trials = int(os.environ.get("FI_TRIALS", "40"))
    rng = random.Random(int(os.environ.get("FI_SEED", "0")))
    d = json.loads((VECTORS / "e2e_ternary.json").read_text())
    n_img = 4
    want = d["logits"][:n_img]

    t0 = cocotb.utils.get_sim_time("ns")
    clean, st = await run_layer2(dut, d, n_img)
    t_run = cocotb.utils.get_sim_time("ns") - t0
    assert clean == want and not st & ERR, "clean run must be exact and unflagged"
    cycles = int(t_run / 10)

    S = sites()
    bad = []
    for path, _, _ in S:                         # every site must exist in this RTL
        try:
            resolve(dut, path)
        except Exception as e:
            bad.append(f"{path}: {e}")
    assert not bad, "unknown fault sites:\n" + "\n".join(bad[:20])
    weights = [w for _, w, _ in S]
    total_bits = sum(weights)
    buckets = {k: 0 for k in ("masked", "detected", "corrected", "SDC", "timeout", "hang")}
    by_region, log = {}, []
    for i in range(trials):
        path, width, region = rng.choices(S, weights=weights)[0]
        bit, when = rng.randrange(width), rng.randrange(cycles)

        async def strike():
            for _ in range(when):
                await FallingEdge(dut.wb_clk_i)
            ok = flip(dut, path, bit)
            if not ok:
                strike.skipped = True
        strike.skipped = False
        cocotb.start_soon(strike())
        try:
            got, st = await with_timeout(run_layer2(dut, d, n_img), 20 * t_run, "ns")
            right, flagged = got == want, bool(st & ERR)
            b = ("masked" if right and not flagged else "corrected" if right else
                 "detected" if flagged else "SDC")
        except NpuTimeout:
            b = "timeout"
        except Exception:                        # cocotb.triggers.SimTimeoutError
            b = "hang"
        if strike.skipped:
            b = "masked"                         # flipping an X does nothing
        buckets[b] += 1
        r = by_region.setdefault(region, {k: 0 for k in buckets})
        r[b] += 1
        log.append({"path": path, "bit": bit, "cycle": when, "region": region, "result": b})
        if b in ("SDC", "timeout", "hang"):
            dut._log.info(f"trial {i}: {b} after flipping {path} bit {bit} at cycle {when}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"trials": trials, "cycles_per_run": cycles,
                               "state_bits": total_bits, "buckets": buckets,
                               "by_region": by_region, "log": log}, indent=1))
    dut._log.info(f"{trials} single-bit upsets over {total_bits:,} state bits, "
                  f"{cycles:,}-cycle layer-2 run:")
    for k, v in buckets.items():
        dut._log.info(f"  {k:9s} {v:5d}  ({100 * v / trials:5.1f}%)")
    for reg, r in sorted(by_region.items()):
        dut._log.info(f"  {reg:16s} " + "  ".join(f"{k}={v}" for k, v in r.items() if v))
    assert buckets["hang"] == 0, "a single upset hung the bus"

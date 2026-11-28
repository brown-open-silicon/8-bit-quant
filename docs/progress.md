# Reference branch: progress log

This branch (`brubru6707/timing-r6`) moves the whole chip toward tape-out in one place, so it can serve as a
**reference** while the team builds the same pieces on their own branches. It is not meant to be merged as one
big PR. Take ideas, diffs or tests from it piece by piece.

Every item below has a commit, and every RTL change has a test in `tb/`. `make sim` passes on every commit.

## Done

| Area | What | Issue | Where |
|---|---|---|---|
| Timing | BIAS writes take an extra cycle: decode into one-hot enables in cycle 2, write in cycle 3 | #6 | `rtl/wb_npu.sv` |
| Timing | Register reads take 3 cycles: three small read muxes, then a final pick (was one ~1,400-input mux) | #6 | `rtl/wb_npu.sv` |
| Timing | Postproc split into 4 stages: lane select, multiply + bias, round + shift, saturate | #6 | `rtl/postproc.sv` |
| Timing | P&R: timing repair after global routing turned on | #6 | `pnr/wb_npu/config.json` |
| Radiation | PP_CFG on `tmr_reg` (3 copies, vote, self-repair) | #10 | `rtl/wb_npu.sv` |
| Radiation | BIAS parity per half-word (detect + reload; TMR would add about 1,536 FFs) | #10 | `rtl/wb_npu.sv` |
| Radiation | Weight-SRAM byte parity, checked on tile stream and bus reads | plan rank 1 | `rtl/wb_npu.sv` |
| Radiation | Row-tag/valid delay line on TMR (a flipped tag silently adds into the wrong row) | plan rank 2 | `rtl/core_ternary.sv` |
| Radiation | Control-state analysis: a flipped pending bit re-runs the access instead of hanging. Firmware poll timeouts | plan rank 3 | `docs/radiation.md`, `firmware/npu.c` |
| Radiation | `ERRCNT` saturating upset counters (telemetry) | plan rank 4 | `rtl/wb_npu.sv` |
| Radiation | Fault-injection campaign over all ~32k state bits: masked / corrected / detected / silent / hang | plan item 5 | `tb/test_fault.py` |
| Radiation | Radiation plan: threats, per-block table, area costs, build order | #7 | `docs/radiation.md` |
| Verification | Array edge cases: zero weights, extreme sums, all 256 one-hot positions, gapped stream, reload | #3 | `tb/test_array.py` |
| Verification | CI workflow running `make sim` in the EDA image (file ready; pushing it needs a token with `workflow` scope) | #5 | `.github/workflows/sim.yml` |
| Integration | `user_project_wrapper`: template ports, address decode with gated stb/cyc, default slave, IRQ, tie-offs | #4 | `rtl/user_project_wrapper.v`, `tb/test_wrapper.py` |

## STATUS / CTRL changes (firmware must know)

| Reg | Bit | Meaning |
|---|---|---|
| STATUS | [1] | any error. It's the OR of the bits below, so old firmware keeps working |
| STATUS | [4] | weight stored as `11` |
| STATUS | [5] | PP_CFG copy flipped (TMR already repaired it) |
| STATUS | [6] | BIAS parity. Stays set until BIAS is rewritten |
| STATUS | [7] | weight-SRAM parity. Re-send the tile |
| STATUS | [8] | row-tag copy flipped (TMR already repaired it) |
| CTRL | [1] | clear ERRCNT |
| ERRCNT (0x034) | [7:0] [15:8] [23:16] [31:24] | weight `11`, PP_CFG TMR, BIAS/WMEM parity, row-tag TMR |

Bus timing: register reads and BIAS writes now take 3 cycles (WMEM reads already did). Postproc latency is N+4.
The full model costs about 0.9% more cycles per image.

## Open

- **Timing at the slow corners:** see the latest P&R numbers below.
- **Accumulator path:** if routing-time repair doesn't close the accumulator path (`tag` → `accum_buf` row select, −2.4 ns in r5), pre-decode the row one cycle earlier.
- **Caravel hardening and precheck:**
  - Needs the official `caravel_user_project` template (fixed wrapper DEF, pin order).
  - Then harden `wb_npu` as a macro inside `user_project_wrapper` and run precheck.
- **Workload (#11):** a team decision; nothing done here.

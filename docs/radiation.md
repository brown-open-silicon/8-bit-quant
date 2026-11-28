# Radiation plan

What radiation can do to this chip, which blocks it hits, and what we add to catch or fix it.
Every protection feature (ECC, TMR, counters, fault-injection tests) should trace back to a row here.

## What can go wrong

| Effect | What it is | What it does to us |
|---|---|---|
| **SEU** (single-event upset) | A particle hits a flip-flop or SRAM cell and flips one stored bit. | Wrong weight, wrong bias, wrong partial sum, or a stuck state machine. The main threat. |
| **SET** (single-event transient) | A particle makes a short glitch on a logic wire. It only matters if a flip-flop captures the glitch on a clock edge. | Same as an SEU, but rarer: the glitch has to land in the capture window. At 40 MHz the chance is small. |
| **SEFI** (single-event functional interrupt) | An upset in control logic puts the whole block in a bad mode. | The bus never acks, the tile loader runs forever, `busy` never drops. The CPU hangs. |
| **TID** (total ionizing dose) | Damage that builds up over months. Transistors get slower and leak more. | Paths that barely met timing start failing. Same effect as the slow corner (issue #6). |
| **SEL** (single-event latch-up) | A particle turns on a parasitic thyristor between power and ground. | Large current, possibly permanent damage. Only fix: cut power fast. |

## Block by block

FF = flip-flop. Area numbers are rough, for Sky130 `sky130_fd_sc_hd`. Each FF is about 25 um^2 of cell area,
or about 55 um^2 after placement at our ~45% utilization. "Lifetime" is how long a value sits before it's overwritten,
which is how long a flip can do damage.

| Block | Bits | Lifetime | If one bit flips | Severity | Protection | Status | Extra area |
|---|---|---|---|---|---|---|---|
| Weight SRAM (WMEM) | 8,192 | whole layer, or longer | one weight wrong for every image until reload. A flip into code `11` is caught (2 of the 6 possible single flips) | **high** (silent, long-lived) | parity per SRAM byte (per byte so masked writes work), checked on bus read and tile stream, sticky `STATUS[7]`. Firmware re-sends the tile | **done** | 1,024 FFs + XOR trees, about 0.06 mm^2 |
| PE weight registers | 512 | one K-tile (reloaded every tile) | one weight wrong until the next tile. `11` is caught | medium | already scrubbed by the per-tile reload. `11` detection | done | 0 |
| Row-tag delay line (`tag_sr`) | 155 | 31 cycles | a result is added into the **wrong accumulator row**, or starts a fresh sum | **high** (silent) | TMR per stage (31 `tmr_reg`s, valid bits included), sticky `STATUS[8]` | **done** | +372 FFs + voters, about 0.025 mm^2 |
| Control state (`act`, `*_pend`, `ld_run`/`ld_k`, postproc `run`/`g`) | about 40 | always live | an access is re-run or repeated (a hang was the worry; it re-captures instead) | medium | a flipped pending bit makes the request re-run (bus retry), not hang. Firmware poll timeouts | **done** (analysis + firmware) | 0 |
| Accumulator (`accum_buf`) | 8,192 | one layer | one output neuron wrong for one image | **high** (the fault campaign's top source of silent errors) | parity per word, checked on accumulate and readout, sticky `STATUS[9]`. Firmware re-runs the layer | **done** | 256 FFs + XOR trees, about 0.02 mm^2 |
| BIAS | 768 | one 16-output group | every image in that group off by a constant | medium | parity per half-word, sticky `STATUS[6]`. Firmware rewrites BIAS (it does every group anyway) | **done** (#10) | 32 FFs + XOR, about 0.01 mm^2 |
| PP_CFG (m, shift, relu) | 32 | whole layer | every output of the layer wrong | **high** (one bit ruins everything) | TMR with self-repair, sticky `STATUS[5]` | **done** (#10) | +64 FFs + voters, about 0.004 mm^2 |
| Postproc pipeline, results (`q_res`, `wide_res`) | about 900 | a few cycles until the CPU reads | one output wrong once | low | none | — | 0 |
| Bus capture regs (`adr_q`, `dat_q`) | about 70 | one access | one access goes to the wrong place or carries a wrong value | low to medium | none (TMR here would sit on the timing-critical decode) | — | 0 |
| Clock / reset tree | — | — | glitch resets the NPU or double-clocks | medium | Caravel's problem; the CPU re-inits on reset | — | — |

What we already have:
- **Weight code `11` = error.** The chip treats it as 0 and sets `STATUS[4]`.
- **Overflow flag.**
- **`irq` output.** It fires on any error or overflow.
- **`STATUS[1]`.** It's the OR of every error source, so old firmware still works. Bits 4–6 say which source it was.

### TID and SEL

- **TID:** we can't fix the transistors, only leave margin. Meeting timing at the slow corner (#6) is the TID margin. The ring-oscillator PVT sensor (`analog/ring_osc`) can measure slowdown in flight, and firmware can then drop the clock.
- **SEL:** Sky130 standard cells already have tap cells (well contacts) at the required spacing. That's the main on-die defense. A real mission adds a current monitor and power switch on the board. That's outside this chip.

## Measured so far

From `make quant`: 784-128-10 MNIST, random flips in stored weights only, 5 trials.

| Weights | Clean | 1% of weight bits flipped |
|---|---|---|
| int8 | 96.6% | 92.6% |
| ternary, quantization-aware | 96.7% | 96.4% |

Ternary weights already degrade gracefully: a flip moves a weight by at most 1 step, or into the detected `11` code.
**This only models weight flips.** The PP_CFG and tag rows in the table above are worse: one bit there breaks every output.
That's why they go first, even though they hold far fewer bits.

## Fault-injection results

`tb/test_fault.py`: one random state bit flipped at a random cycle during MNIST layer 2 (4 images, SRAM path),
uniform over every state bit in `wb_npu`. 1,000 trials per row, seed 1.

| Design | State bits | masked | corrected | detected | **silent (SDC)** | hang |
|---|---|---|---|---|---|---|
| PP_CFG TMR, BIAS + WMEM parity, tag TMR | 32,423 | 86.2% | 7.8% | 3.0% | **3.0%** | 0 |
| + accumulator parity | 32,713 | 85.8% | 8.9% | 4.7% | **0.6%** | 0 |

- **First row:** 23 of the 30 silent errors were accumulator words.
- **Second row:** accumulator parity turned them into detections (18 detected, 14 corrected, 0 silent).
- **The 6 that remain:**
  - 2 in the array's valid shift register. Since fixed: the accumulator now takes its valid from the TMR'd tag line.
  - 2 in PE partial sums and 1 in a PE weight (transient, in flight).
  - 1 in `wide_res` (a result waiting for the CPU).
- **Corrected:** a flagged run with the right answer. That's a TMR repair, or a flip in a word that was rewritten before it mattered.

## Build order

Each item can be its own issue.

1. ~~**WMEM parity**~~: done. Byte parity in flip-flops (the stock SRAM has no spare column), checked on
   tile stream and bus reads, sticky `STATUS[7]`. Test: `test_wb.wmem_parity` (a `00`→`01` flip the `11` code misses).
   Note: after power-up the SRAM holds random data, so reading a word that was never written can flag a false error.
2. ~~**TMR the row-tag delay line**~~: done, valid bits included. Test: `test_core.tag_tmr_flip`.
3. ~~**Control state**~~: analyzed instead of TMR'd.
   - **No hang:** if `act` or any `*_pend` flips 1→0 while the CPU waits, the CPU is still holding `stb`. The request is captured and executed again, so the bus doesn't hang.
   - **Residual risk:** a command write (PUSH, W_LOAD, READ, W_TILE) running **twice**, or a flip 0→1 repeating the last access. That's silent corruption, not a hang. The fault-injection campaign (item 5) measures how often it happens. Fix it only if the number says so.
   - **Firmware:** every poll loop gives up after `NPU_POLL_MAX` polls and returns `NPU_FW_TIMEOUT`.
4. ~~**Error counter register**~~: done, `ERRCNT` at 0x034 (`test_wb.errcnt`). a saturating count of each error type, for telemetry. "How many flips per day in orbit" is the number the mission team actually wants.
5. **Fault-injection regression:**
   - A cocotb test that flips a random FF anywhere in `wb_npu` during a full MNIST run.
   - It checks that the result is either still correct or flagged in `STATUS`.
   - The fraction that's neither is our *silent data corruption* rate, the headline radiation number.
6. **Optional firmware re-run-and-compare** for the accumulator: costs time, not area.

Done: PP_CFG TMR, BIAS parity, per-source STATUS bits (#10), WMEM byte parity, row-tag TMR.

# 8-bit-quant: BOS accelerator foundations

Starting point for a **low-bit (ternary) AI accelerator on Sky130** (via ChipFoundry chipIgnite) that is robust to
radiation-style bit flips. Everything here runs end to end in under a minute:

```
Python model ──quantize──▶ int8 / int4 / ternary ──fault-inject──▶ accuracy table
      │
      └──export golden vectors──▶ tb/vectors/*.json ──cocotb──▶ RTL must match bit-for-bit
                                                                  │
                                                     yosys + Sky130 cells ──▶ area
```

## Quick start

Needs `uv` (Python) and Docker with the `hpretl/iic-osic-tools:chipathon26` image
(Sky130 + GF180 PDKs, yosys, OpenROAD, LibreLane, magic, klayout, xschem, ngspice, iverilog, cocotb).

```bash
make quant   # train + quantize + fault-inject + export golden vectors   (~10 s)
make sim     # RTL tests in the EDA container                            (~10 s)
make area    # synthesize blocks to Sky130 cells (PDK=gf180mcuD for GF180) (~90 s)
make shell   # interactive shell in the EDA container
```

## Layout

| Path | What |
|---|---|
| `quant/qlib.py` | Quantization (symmetric, per-tensor), storage encoding, bit-flip injection |
| `quant/mnist.py` | Tiny NumPy MLP (784-128-10) + ternary quantization-aware training |
| `quant/experiment.py` | The experiment: accuracy, memory, GF180 SRAM count, fault tolerance |
| `rtl/mac_int8.sv` | INT8 multiply-accumulate PE (baseline) |
| `rtl/pe_ternary.sv` | Ternary PE: add/sub/skip, flags invalid code `11` as a bit flip |
| `rtl/pe_ws_ternary.sv` | Weight-stationary ternary PE (array building block) |
| `rtl/array_ternary.sv` | **16×16 ternary systolic array**: skew/deskew, valid pipeline, sticky bit-flip flag |
| `rtl/accum_buf.sv` | int32 accumulator buffer: sums K-tiles (`first` = overwrite, else add), sticky overflow flag |
| `rtl/postproc.sv` | Requantize int32 → int8: `(acc·m + bias) >> sh`, round, ReLU, clamp (integer-only); `P` lanes per cycle |
| `rtl/wb_npu.sv` | **Wishbone host interface** (Caravel's bus): memory-mapped registers for weights, activations, config, results, status/irq; 1 KB SRAM weight buffer |
| `firmware/npu.{h,c}` | **C firmware** for Caravel's RISC-V core (port of `tb/npu_driver.py`); 912 B of code on RV32 |
| `tb/test_firmware.py` | Runs that exact C file against the RTL (host build, register accesses bridged into cocotb) |
| `rtl/macros/` | Simulation model of the stock Sky130 SRAM macro (`sky130_sram_1kbyte_1rw1r_32x256_8`, OpenRAM, Apache-2.0) |
| `tb/npu_driver.py` | Reference "firmware": runs layers using only bus reads/writes (port to C for Caravel) |
| `rtl/core_ternary.sv` | Array + accumulator + postproc; `{first, addr}` tags ride a 31-cycle delay line with the data |
| `tb/` | cocotb tests + golden vectors |
| `synth/area.sh` | yosys → `sky130_fd_sc_hd` (tt 1.8 V) by default, or GF180 `gf180mcu_fd_sc_mcu7t5v0` with `PDK=gf180mcuD` |
| `scripts/eda.sh` | Run anything inside the EDA container |
| `third_party/coralnpu` | Google Coral NPU (submodule, Apache-2.0) |

## First results (MNIST placeholder, 101,632 weights)

| Weights | Memory | GF180 512 B SRAM macros | Clean acc | Acc @ 1% bit flips |
|---|---|---|---|---|
| int8 | 99.2 KB | 199 (41.7 mm²) | 96.6% | 92.6% |
| int4 | 49.6 KB | 100 (20.9 mm²) | 96.8% | 89.8% |
| ternary (just rounded) | 24.8 KB | 50 (10.5 mm²) | 78.1% | 76.2% |
| **ternary (QAT)** | **24.8 KB** | **50 (10.5 mm²)** | **96.7%** | **96.4%** |

| Block (synthesized, logic only, before place & route) | Sky130 cells | **Sky130 area** | GF180 area |
|---|---|---|---|
| `mac_int8` (32-bit acc) | 755 | 5,907 µm² | 18,762 µm² |
| `pe_ternary` | 278 | 2,233 µm² (**2.6× smaller**) | 7,325 µm² |
| `pe_ws_ternary` (16-bit psum) | 139 | 1,394 µm² | 4,395 µm² |
| **`array_ternary` 16×16** | **36,580** | **0.41 mm²** | 1.26 mm² |
| `accum_buf` (16 rows × 16 lanes × int32, flops) | 24,630 | 0.39 mm² | 1.19 mm² |
| `postproc` (1 shared multiplier, 16 cycles/row) | 7,059 | 0.075 mm² (was 0.39 with 16 multipliers) | — |
| **`core_ternary`** (array + accumulator + postproc) | **66,535** | **0.86 mm²** | — |
| **`wb_npu`** (core + Wishbone registers) | **85,552** | **0.99 mm²** | — |

- The 8 Kb accumulator built from flip-flops is as big as the whole array, but it **stays in flops**: it does a
  512-bit read-modify-write every cycle, and the stock SRAM macro is 32 bits wide. Matching that bandwidth would take
  16 macros (~3 mm²) vs 0.39 mm² of flops.
- The SRAM goes where its width fits: the **weight buffer**. One weight row (16 × 2 bits) is exactly one 32-bit word,
  so the 1 KB macro (0.19 mm²) holds 16 tiles and streams a row into the array every cycle.
- `postproc` runs once per output row, so it time-shares one multiplier (`P=1`); `P=4`/`P=16` trade area back for speed.

Takeaways:
- **Memory dominates.** On GF180 the biggest SRAM macro is 512 bytes, about 0.21 mm². An int8 model this size
  wouldn't fit on a small shuttle die. Ternary cuts that by 4×.
- **Ternary needs quantization-aware training** (BitNet-style). Rounding a trained model loses about 19 points;
  QAT recovers it fully.
- **Ternary degrades least under bit flips:** -0.2 pts at 1% flip rate vs. -4 pts for int8. The free `11`
  error detection helps slightly, but at 5 trials that difference is within noise. More trials are needed before claiming it.
- 16×16 ternary array synthesizes to 0.41 mm² on Sky130 (1.26 mm² on GF180); 256 INT8 MACs alone would be ~1.5 mm² on Sky130.

Caveats: MNIST + MLP is a stand-in. Swap in the real workload (e.g. satellite cloud/wildfire
imagery) and a small CNN. The bit-flip model is uniform random flips in stored weights only.

## Full model on the RTL

`test_core.full_model_mnist` runs the entire 784-128-10 ternary network on the RTL:
layer 1 (8 neuron groups × 49 chunks) → requant + ReLU → layer 2 (8 chunks) → logits.
For 32 test images, every hidden activation and logit matches Python bit-for-bit, and 32/32 are classified correctly.
The integer-only Python model (`int_forward_fixed`, exactly what the chip computes) scores **96.70%** on 2,000 test images,
the same as the float-scale version.

`test_wb.full_model_bus` runs the same network **through the Wishbone bus only**, the way Caravel's RISC-V
core would, using `tb/npu_driver.py` as firmware: 16 images bit-exact, 16/16 correct.
`test_wb.full_model_wmem` does the same with weights staged in the SRAM buffer (write 16 tiles, then one
`W_TILE` write streams each into the array; the bus waits instead of the CPU polling):

| 16 images, MNIST 784-128-10 | bus accesses / image | cycles / image |
|---|---|---|
| direct weights (`W_DATA`/`W_LOAD`) | 3,400 | 6,800 |
| SRAM weight buffer | 2,609 (−23%) | 6,129 (−10%) |

Activations are now most of the remaining traffic (5 bus writes per image per tile); a DMA or wider feed is the fix.
`test_firmware.firmware_full_model` runs the network from **`firmware/npu.c`**, the C code that would run on Caravel's
CPU: compiled for the host, every register access becomes a real bus cycle on the simulated chip. 16/16 bit-exact.

`test_wb.sram_bitflip` flips a stored bit inside the SRAM (`01`→`11`) and checks the array flags it on load.

## Physical design (LibreLane, Sky130)

`pnr/wb_npu`: the whole bus-connected NPU **with the SRAM macro**, placed and routed to GDS
(`klayout`/`render_def.py` + `floorplan_map.py` draw it).

| | |
|---|---|
| Die | 1.77 × 1.78 mm (3.15 mm²; Caravel user area ≈ 10 mm²) |
| Cells | 174k std cells + 1 SRAM macro (1 KB, 0.19 mm²) |
| Timing @ 40 MHz, typical (tt 25 °C 1.8 V) | **met**: +5.1 ns setup, +0.22 ns hold |
| Timing @ 40 MHz, slow (ss 100 °C 1.6 V) | **not met**: −9.5 ns (bus address → read mux), −5.4 ns (accumulator read-modify-write) |
| Hold, all corners | met |
| Power (typical, estimated) | ~0.10 W |
| Open issues | 24 routing DRC, 294 antenna nets, slew/cap violations at the slow corner; DRC/LVS not run yet |

Flow fixes that were needed: `CTS_APPLY_NDR: none` (wide clock wires could not reach clkbuf pins),
SRAM black-box header with power pins (`rtl/macros/*_bb.v`), `STA_THREADS: 2` (9-corner STA ran out of 8 GB).

## Coral NPU notes
- Chisel + SystemVerilog, built with **Bazel 8.6** (not installed; their CI uses `utils/coralnpu.dockerfile`, linux/amd64).
- Matrix engine (VME) is **experimental** and supports **INT8 / FP32 / BF16 only**, with no int4 or ternary. That's an opening.
- Their reference physical build is ~1.43M cells on ASAP7 (7 nm). The full core is far too big for a 10 mm² Sky130 slot;
  reuse pieces (scalar RISC-V core as controller, AXI interfaces) or treat it as a reference design.
- Start with `third_party/coralnpu/doc/overview.md` and `doc/microarch/`.

## Next steps
1. Pick the real workload + dataset; replace MNIST with a small CNN.
2. More fault-injection trials and fault models (multi-bit upsets, activations/accumulators, not just weights).
3. ~~16×16 ternary systolic array~~ done: computes real MNIST layer-1 outputs (49 tiles) bit-exact vs. Python.
   ~~On-chip accumulator~~ done: `core_ternary` sums all 49 K-tiles on chip, bit-exact.
   ~~Weight SRAM~~ done: stock Sky130 1 KB macro as a weight buffer, bit-exact. Next: activation buffer / DMA,
   INT8 array for comparison.
4. Error counter on the weight SRAM (doubles as a radiation monitor); ECC or scrubbing for the stored weights.
5. LibreLane hardening of the PE/array for real post-route area and timing on Sky130 (`pnr/core_ternary`, in progress).
6. Put `wb_npu` in Caravel's `user_project_wrapper`; ~~port `npu_driver.py` to C firmware~~ done (`firmware/`); precheck.

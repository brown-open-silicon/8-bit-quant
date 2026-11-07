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
| `rtl/postproc.sv` | Requantize int32 → int8: `(acc·m + bias) >> sh`, round, ReLU, clamp (integer-only, no float) |
| `rtl/wb_npu.sv` | **Wishbone host interface** (Caravel's bus): memory-mapped registers for weights, activations, config, results, status/irq |
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
| `postproc` (16 lanes, 32×16 multiply each) | 53,995 | 0.39 mm² | — |
| **`core_ternary`** (array + accumulator + postproc) | **113,150** | **1.18 mm²** | — |

- The 8 Kb accumulator built from flip-flops is as big as the whole array. It should become SRAM.
- `postproc` runs once per output row, so 16 parallel multipliers is overkill; one time-shared lane would be ~16× smaller.

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
core would, using `tb/npu_driver.py` as firmware: 16 images bit-exact, 16/16 correct, ~3,300 bus accesses per image.
The bus is now the bottleneck (the array idles while the CPU pushes data); a DMA or wider feed is the fix.

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
   Next: move the accumulator to SRAM, weight/activation SRAM feeding the array, INT8 array for comparison.
4. SRAM wrapper around `gf180mcu_fd_ip_sram__sram512x8m8wm1` + error counter (doubles as a radiation monitor).
5. LibreLane hardening of the PE/array for real post-route area and timing on Sky130 (`pnr/core_ternary`, in progress).
6. Put `wb_npu` in Caravel's `user_project_wrapper`; port `npu_driver.py` to C firmware; precheck.

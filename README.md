# 8-bit-quant: BOS accelerator foundations

Starting point for a **low-bit (ternary) AI accelerator on GF180** that is robust to
radiation-style bit flips. Everything here runs end to end in under a minute:

```
Python model ──quantize──▶ int8 / int4 / ternary ──fault-inject──▶ accuracy table
      │
      └──export golden vectors──▶ tb/vectors/*.json ──cocotb──▶ RTL must match bit-for-bit
                                                                  │
                                                     yosys + GF180 cells ──▶ area
```

## Quick start

Needs `uv` (Python) and Docker with the `hpretl/iic-osic-tools:chipathon26` image
(GF180 PDK, yosys, OpenROAD, LibreLane, magic, klayout, xschem, ngspice, iverilog, cocotb).

```bash
make quant   # train + quantize + fault-inject + export golden vectors   (~10 s)
make sim     # RTL tests in the EDA container                            (~10 s)
make area    # synthesize PEs to GF180 cells                             (~10 s)
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
| `tb/` | cocotb tests + golden vectors |
| `synth/area.sh` | yosys → GF180 `gf180mcu_fd_sc_mcu7t5v0` cells, typical corner 5 V |
| `scripts/eda.sh` | Run anything inside the EDA container |
| `third_party/coralnpu` | Google Coral NPU (submodule, Apache-2.0) |

## First results (MNIST placeholder, 101,632 weights)

| Weights | Memory | GF180 512 B SRAM macros | Clean acc | Acc @ 1% bit flips |
|---|---|---|---|---|
| int8 | 99.2 KB | 199 (41.7 mm²) | 96.6% | 92.6% |
| int4 | 49.6 KB | 100 (20.9 mm²) | 96.8% | 89.8% |
| ternary (just rounded) | 24.8 KB | 50 (10.5 mm²) | 78.1% | 76.2% |
| **ternary (QAT)** | **24.8 KB** | **50 (10.5 mm²)** | **96.7%** | **96.4%** |

| PE (GF180, synthesized) | Cells | Area |
|---|---|---|
| `mac_int8` (32-bit acc) | 900 | 18,762 µm² |
| `pe_ternary` | 311 | 7,325 µm² (**2.6× smaller**) |
| `pe_ws_ternary` (16-bit psum) | 154 | 4,395 µm² |
| **`array_ternary` 16×16** | **37,970** | **1.26 mm²** (logic only, before place & route) |

Takeaways:
- **Memory dominates on GF180.** The biggest PDK SRAM macro is 512 bytes, about 0.21 mm². An int8 model this size
  wouldn't fit on a small shuttle die. Ternary cuts that by 4×.
- **Ternary needs quantization-aware training** (BitNet-style). Rounding a trained model loses about 19 points;
  QAT recovers it fully.
- **Ternary degrades least under bit flips:** -0.2 pts at 1% flip rate vs. -4 pts for int8. The free `11`
  error detection helps slightly, but at 5 trials that difference is within noise. More trials are needed before claiming it.
- 16×16 ternary array synthesizes to 1.26 mm² of GF180 logic; 256 INT8 MACs alone would be ~4.8 mm².

Caveats: MNIST + MLP is a stand-in. Swap in the real workload (e.g. satellite cloud/wildfire
imagery) and a small CNN. The bit-flip model is uniform random flips in stored weights only.

## Coral NPU notes
- Chisel + SystemVerilog, built with **Bazel 8.6** (not installed; their CI uses `utils/coralnpu.dockerfile`, linux/amd64).
- Matrix engine (VME) is **experimental** and supports **INT8 / FP32 / BF16 only**, with no int4 or ternary. That's an opening.
- Their reference physical build is ~1.43M cells on ASAP7 (7 nm). The full core is far too big for GF180;
  reuse pieces (scalar RISC-V core as controller, AXI interfaces) or treat it as a reference design.
- Start with `third_party/coralnpu/doc/overview.md` and `doc/microarch/`.

## Next steps
1. Pick the real workload + dataset; replace MNIST with a small CNN.
2. More fault-injection trials and fault models (multi-bit upsets, activations/accumulators, not just weights).
3. ~~16×16 ternary systolic array~~ done: computes real MNIST layer-1 outputs (49 tiles) bit-exact vs. Python.
   Next: on-chip accumulator for K-tiling, weight/activation SRAM feeding it, INT8 array for comparison.
4. SRAM wrapper around `gf180mcu_fd_ip_sram__sram512x8m8wm1` + error counter (doubles as a radiation monitor).
5. LibreLane hardening of the PE/array for real post-route area and timing on GF180.

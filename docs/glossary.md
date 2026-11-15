# Glossary

TLDR: the words you will hear, in one line each. Sorted by topic.

## Neural networks and quantization

| Term | Meaning |
|---|---|
| Inference | running a trained model to get an answer. This chip only does inference |
| Weight | a learned number the input gets multiplied by. MNIST model: 101,770 parameters |
| Activation | an input or intermediate value flowing through the network (int8 here) |
| Dense / MLP layer | every output is a weighted sum of every input. Our model: 784-128-10 |
| MNIST | 28x28 images of handwritten digits (784 pixels). Placeholder workload |
| Quantization | storing numbers with fewer bits (float32 -> int8 -> ternary) |
| Ternary | weights are only -1, 0, +1. Stored as 2 bits (`11` is unused, so it flags a bit flip) |
| PTQ | post-training quantization: train in float, round afterwards. Bad for ternary (78%) |
| QAT | quantization-aware training: the model trains while rounded, so it adapts (96.7%) |
| BitNet | Microsoft papers showing ternary LLMs work ([arXiv 2402.17764](https://arxiv.org/abs/2402.17764)) |
| Requantize | scale the wide int32 sum back down to int8 for the next layer |
| ReLU | negative values become 0 |
| Golden vectors | Python results saved to JSON. The RTL must match them bit-for-bit |
| Bit flip / SEU | radiation flips a stored 0 to 1 or back |

## Architecture

| Term | Meaning |
|---|---|
| NPU | neural processing unit: hardware built to run neural networks |
| MAC | multiply-accumulate: `acc += a * w`. The core operation of a neural net |
| PE | processing element: one cell of the array. Ours holds one weight and does add, skip, or subtract |
| Systolic array | a grid of PEs that pass data only to their neighbors, like a bucket brigade. Short wires, easy to scale |
| Weight-stationary | weights stay inside the PEs while inputs flow through |
| Tile | one 16x16 block of weights, the size of the array. MNIST needs 400 |
| K-tile | a 16-input slice of a layer. Partial sums of all K-tiles get added up |
| Skew / deskew | delays that line up data entering and leaving the array diagonally |
| Accumulator | memory that adds each tile's partial sums into a running int32 total |
| Batch | images processed together through one loaded tile (up to 16) |
| Wishbone | the simple bus Caravel's CPU uses to read and write our registers |
| Register map | the list of addresses the CPU reads and writes to control a block |
| Firmware | C code on the CPU that drives the NPU (`firmware/npu.c`) |
| DMA | hardware that moves data without the CPU. Not built yet |

## Chips and fabrication

| Term | Meaning |
|---|---|
| RTL | register-transfer level: the design written in SystemVerilog |
| Flip-flop | a 1-bit storage cell built from logic. Fast and flexible, but big |
| SRAM | dense memory block (a "macro"). Smaller per bit, but only a few ports |
| Macro | a pre-made layout block, such as an SRAM, placed as one piece |
| Standard cells | the library of small logic gates the tools build the design from |
| PDK | process design kit: a fab's rules, cells, and models. Ours: Sky130 (also tested GF180) |
| Sky130 | SkyWater's open 130 nm process |
| Caravel | the chip harness for Sky130 shuttles: CPU, pads, and a user area (2.92 x 3.52 mm) for our design |
| chipIgnite | ChipFoundry's paid shuttle that fabricates Caravel chips |
| Tapeout | sending the final layout to the fab |
| Synthesis | turning RTL into standard cells (yosys) |
| Place and route (P&R) | placing the cells and drawing the wires (OpenROAD / LibreLane) |
| GDS | the final layout file the fab uses |
| Timing / slack | whether signals arrive before the next clock edge. Negative slack = too slow |
| Corner | a worst-case condition for timing: tt (typical), ss (slow: hot, low voltage), ff (fast) |
| Setup / hold | data must arrive before the clock edge (setup) and stay put just after it (hold) |
| DRC | design rule check: the layout obeys the fab's spacing and width rules |
| LVS | layout vs schematic: the layout matches the circuit |
| Antenna | long wires that build up charge during manufacturing and can damage gates. Fixed with diodes |
| Precheck | ChipFoundry's automated checks before a tapeout is accepted |
| PVT | process, voltage, temperature: the conditions that change how fast the chip runs |
| TID | total ionizing dose: radiation damage that builds up over time |
| cocotb | Python framework for writing hardware tests |
| Icarus | the Verilog simulator our tests use |
| LibreLane | the open-source flow that takes RTL to GDS |
| KLayout | layout viewer |

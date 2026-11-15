# Contributing

TLDR: install Docker and uv, run `make sim`, pick a `good first issue`, open a PR.

## 1. Understand it (15 min)

- Read the [README](README.md) and look at the block diagram.
- Skim [docs/architecture.md](docs/architecture.md). Look up unknown words in [docs/glossary.md](docs/glossary.md).

## 2. Set up (about 1 hour, mostly downloading)

| Need | Get it |
|---|---|
| git | macOS: `xcode-select --install`. Windows: use WSL2 (Ubuntu) and run everything inside it |
| Docker | Docker Desktop. Give it at least 8 GB of RAM (16 GB for place and route) |
| uv (Python) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

```bash
git clone https://github.com/brown-open-silicon/8-bit-quant && cd 8-bit-quant
docker pull hpretl/iic-osic-tools:chipathon26     # 10+ GB: all EDA tools + PDKs
make quant                                        # Python: train + quantize (~10 s)
make sim                                          # RTL tests (a few minutes)
```

Done when `make sim` ends with every test `PASS`. If it doesn't, open an issue with the output.

## 3. See the chip (30 min, optional)

The GUI tools (KLayout, xschem) run in a desktop inside the container, viewed in your browser:

```bash
docker run -d --name npu_vnc -p 8080:80 -v "$PWD":/foss/designs/8-bit-quant hpretl/iic-osic-tools:chipathon26
# open http://localhost:8080  (password abc123), then in its terminal:
cd /foss/designs/8-bit-quant && sak-pdk sky130A
xschem analog/ring_osc/ring_osc.sch                    # schematic
klayout pnr/wb_npu/runs/<run>/final/gds/wb_npu.gds     # layout (needs a finished layout run)
```

`docker stop npu_vnc` when done, `docker start npu_vnc` to come back.
No layout run yet? See the pictures in [docs/architecture.md](docs/architecture.md#physical-design).

## 4. Pick a task

Filter issues by label:

| Label | Area |
|---|---|
| `good first issue` | small, safe, good for learning |
| `rtl` | SystemVerilog design |
| `verification` | cocotb tests |
| `layout` | LibreLane, timing, DRC/LVS |
| `ml` | model, quantization, fault injection (Python) |
| `firmware` | C driver for the RISC-V CPU |
| `sensor` | PVT / radiation sensor |
| `sram` | custom SRAM |
| `integration` | Caravel wrapper, precheck |
| `documentation` | docs, diagrams |
| `blocked` | waiting on something else |

Comment on the issue to claim it, so two people don't do the same work.

## 5. Submit work

```bash
git checkout -b <your-name>/<short-topic>
# make changes
make sim                                   # must still pass
git push -u origin <your-name>/<short-topic>
```

Then open a pull request. Rules:

- No direct pushes to `main`. Every change goes through a PR with one review.
- Changes in `rtl/` need a test in `tb/` and a review from the RTL owner.
- Don't change a register address or port listed in [docs/interfaces.md](docs/interfaces.md) without updating the doc in the same PR.
- Don't commit build outputs (`build/`, `pnr/*/runs/`), large binaries, or anyone's personal info. This repo is public.

## Useful commands

| Command | Does |
|---|---|
| `scripts/eda.sh "python3 tb/run.py wb_npu"` | run one test group (names in `tb/run.py`) |
| `PDK=gf180mcuD make area` | synthesize for GF180 instead of Sky130 |
| `scripts/eda.sh 'librelane --manual-pdk --pdk-root $PDK_ROOT --pdk sky130A --run-tag mine pnr/wb_npu/config.json'` | full place and route (~1-2 h, 8+ GB RAM) |

## Where to ask

Ask in the team chat, or open an issue with the `question` label. No question is too basic.

## Other

Make a new folder when it's a new kind of thing. If something already exists for it then work on that folder.

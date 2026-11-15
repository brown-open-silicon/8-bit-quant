# Contributing

TLDR: install Docker and uv, run `make sim`, pick a `good first issue`, open a PR.

## 1. Understand it (15 min)

- Read the [README](README.md) and look at the block diagram.
- Skim [docs/architecture.md](docs/architecture.md). Look up unknown words in [docs/glossary.md](docs/glossary.md).

## 2. Set up (about 1 hour, mostly downloading)

Follow **[docs/setup.md](docs/setup.md)**: install steps for macOS, Windows and Linux, the VNC desktop (xschem, KLayout),
running the tests, and a troubleshooting table.

Done when `make sim` (or `python3 tb/run.py` in the VNC) passes with `FAIL=0`.

## 3. Pick a task

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

## 4. Submit work

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

## Commands and help

Useful commands and the troubleshooting table are in [docs/setup.md](docs/setup.md#10-other-commands).

## Where to ask

Ask in the team chat, or open an issue with the `question` label. No question is too basic.

## Other

Make a new folder when it's a new kind of thing. If something already exists for it then work on that folder.

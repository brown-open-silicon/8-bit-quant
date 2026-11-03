#!/usr/bin/env bash
# Run a command inside the IIC-OSIC-TOOLS container (GF180 PDK + yosys,
# OpenROAD, LibreLane, magic, klayout, xschem, ngspice, iverilog, verilator,
# cocotb) with this repo mounted at /work.
#
#   scripts/eda.sh yosys -V
#   scripts/eda.sh              # interactive shell
set -euo pipefail
IMAGE="${EDA_IMAGE:-hpretl/iic-osic-tools:chipathon26}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TTY=(); [ -t 0 ] && [ -t 1 ] && TTY=(-t)
CMD="${*:-bash}"
exec docker run --rm -i ${TTY[@]+"${TTY[@]}"} \
    -v "$ROOT":/work -w /work \
    -e PDK=gf180mcuD \
    --entrypoint bash "$IMAGE" -lc "$CMD" 2> >(grep -v '^\[INFO\]' >&2)

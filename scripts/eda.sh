#!/usr/bin/env bash
# Run a command inside the IIC-OSIC-TOOLS container (Sky130 + GF180 PDKs, yosys,
# OpenROAD, LibreLane, magic, klayout, xschem, ngspice, iverilog, verilator,
# cocotb) with this repo mounted at /work.
#
#   scripts/eda.sh yosys -V
#   scripts/eda.sh              # interactive shell
#   PDK=gf180mcuD scripts/eda.sh ...   # use GF180 instead of the default Sky130
set -euo pipefail
IMAGE="${EDA_IMAGE:-hpretl/iic-osic-tools:chipathon26}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TTY=(); [ -t 0 ] && [ -t 1 ] && TTY=(-t)
CMD="${*:-bash}"
# The image's login profile sets its own PDK, so re-export after login.
PDK_SEL="${PDK:-sky130A}"
case "$PDK_SEL" in
  sky130A)   LIBSEL=sky130_fd_sc_hd ;;
  gf180mcuD) LIBSEL=gf180mcu_fd_sc_mcu7t5v0 ;;
  *) echo "unknown PDK $PDK_SEL" >&2; exit 1 ;;
esac
exec docker run --rm -i ${TTY[@]+"${TTY[@]}"} \
    -v "$ROOT":/work -w /work \
    --entrypoint bash "$IMAGE" -lc "export PDK=$PDK_SEL STD_CELL_LIBRARY=$LIBSEL; $CMD" 2> >(grep -v '^\[INFO\]' >&2)

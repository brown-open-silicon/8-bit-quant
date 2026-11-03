#!/usr/bin/env bash
# Synthesize each PE to GF180 standard cells and report area.
# Runs inside the EDA container:  scripts/eda.sh synth/area.sh
set -euo pipefail
LIB=$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib
mkdir -p build/synth
for top in ${@:-mac_int8 pe_ternary}; do
  yosys -q -l build/synth/$top.log -p "
    read_verilog -sv rtl/$top.sv
    synth -top $top -flatten
    dfflibmap -liberty $LIB
    abc -liberty $LIB
    opt_clean
    tee -o build/synth/$top.stat stat -liberty $LIB" >/dev/null
  area=$(grep -i "chip area" build/synth/$top.stat | awk '{print $NF}')
  cells=$(awk '/ cells$/{print $1; exit}' build/synth/$top.stat)
  printf "%-12s %8s cells  %10s um^2\n" "$top" "$cells" "$area"
done

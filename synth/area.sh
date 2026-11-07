#!/usr/bin/env bash
# Synthesize blocks to standard cells and report area.
# Runs inside the EDA container:
#   scripts/eda.sh synth/area.sh                    # Sky130 (default)
#   PDK=gf180mcuD scripts/eda.sh synth/area.sh      # GF180
#   scripts/eda.sh synth/area.sh core_ternary       # one block
set -euo pipefail
case "${PDK:-sky130A}" in
  sky130A)   LIB=$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib ;;
  gf180mcuD) LIB=$PDK_ROOT/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib ;;
  *) echo "unknown PDK $PDK" >&2; exit 1 ;;
esac
OUT=build/synth/$PDK
mkdir -p $OUT
echo "PDK: $PDK"
for top in ${@:-mac_int8 pe_ternary pe_ws_ternary array_ternary accum_buf core_ternary}; do
  yosys -q -l $OUT/$top.log -p "
    read_verilog -sv rtl/*.sv
    synth -top $top -flatten
    dfflibmap -liberty $LIB
    abc -liberty $LIB
    opt_clean
    tee -o $OUT/$top.stat stat -liberty $LIB" >/dev/null 2>$OUT/$top.warn
  area=$(grep -i "chip area" $OUT/$top.stat | awk '{print $NF}')
  cells=$(awk '/ cells$/{print $1; exit}' $OUT/$top.stat)
  printf "%-14s %8s cells  %14s um^2\n" "$top" "$cells" "$area"
done

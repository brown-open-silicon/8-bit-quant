"""Build + run the cocotb tests for each PE with Icarus Verilog."""
import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[1]
TOPS = sys.argv[1:] or ["mac_int8", "pe_ternary"]

failed = 0
for top in TOPS:
    runner = get_runner("icarus")
    build_dir = ROOT / "build" / "sim" / top
    runner.build(
        sources=[ROOT / "rtl" / f"{top}.sv"],
        hdl_toplevel=top,
        build_dir=build_dir,
        timescale=("1ns", "1ps"),
        always=True,
    )
    results = runner.test(
        hdl_toplevel=top,
        test_module="test_pe",
        test_dir=Path(__file__).parent,
        build_dir=build_dir,
        extra_env={"COCOTB_TOPLEVEL": top},
    )
    failed += get_results(results)[1]
sys.exit(1 if failed else 0)

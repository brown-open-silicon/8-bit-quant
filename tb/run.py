"""Build + run cocotb tests with Icarus Verilog.

  python3 tb/run.py                 # all
  python3 tb/run.py array_ternary   # one
"""
import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "rtl"

# name -> (rtl sources, cocotb test module[, top, parameters])
TESTS = {
    "mac_int8":      (["mac_int8.sv"], "test_pe"),
    "pe_ternary":    (["pe_ternary.sv"], "test_pe"),
    "array_ternary": (["pe_ws_ternary.sv", "array_ternary.sv"], "test_array"),
    "core_ternary":  (["pe_ws_ternary.sv", "array_ternary.sv", "accum_buf.sv",
                       "postproc.sv", "core_ternary.sv"], "test_core"),
    "wb_npu":        (["pe_ws_ternary.sv", "array_ternary.sv", "accum_buf.sv",
                       "postproc.sv", "core_ternary.sv", "wb_npu.sv"], "test_wb"),
    "postproc":      (["postproc.sv"], "test_postproc"),
    "accum_narrow":  (["accum_buf.sv"], "test_accum", "accum_buf",
                      {"N": 4, "IN_W": 16, "ACC_W": 16, "DEPTH": 4}),
}

failed = 0
for name in sys.argv[1:] or TESTS:
    sources, module, *rest = TESTS[name]
    top = rest[0] if rest else name
    params = rest[1] if len(rest) > 1 else {}
    runner = get_runner("icarus")
    build_dir = ROOT / "build" / "sim" / name
    runner.build(
        sources=[RTL / s for s in sources],
        hdl_toplevel=top,
        build_dir=build_dir,
        parameters=params,
        timescale=("1ns", "1ps"),
        always=True,
    )
    results = runner.test(
        hdl_toplevel=top,
        test_module=module,
        test_dir=Path(__file__).parent,
        build_dir=build_dir,
        extra_env={"COCOTB_TOPLEVEL": top},
    )
    failed += get_results(results)[1]
sys.exit(1 if failed else 0)

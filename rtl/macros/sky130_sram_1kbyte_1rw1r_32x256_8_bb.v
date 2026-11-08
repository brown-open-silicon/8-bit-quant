// Black-box port list of the Sky130 1 KB SRAM macro, for synthesis / P&R
// (LibreLane MACROS "vh"). The layout comes from the PDK's LEF/GDS; the
// simulation model is sky130_sram_1kbyte_1rw1r_32x256_8.v next to this file.
(* blackbox *)
module sky130_sram_1kbyte_1rw1r_32x256_8 (
`ifdef USE_POWER_PINS
    inout         vccd1,
    inout         vssd1,
`endif
    input         clk0,
    input         csb0,
    input         web0,
    input  [3:0]  wmask0,
    input  [7:0]  addr0,
    input  [31:0] din0,
    output [31:0] dout0,
    input         clk1,
    input         csb1,
    input  [7:0]  addr1,
    output [31:0] dout1
);
endmodule

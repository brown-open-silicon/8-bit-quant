// Caravel user_project_wrapper: plugs wb_npu into the Caravel harness (issue #4).
//
// Port list matches the template in chipfoundry/caravel_user_project
// (verilog/rtl/user_project_wrapper.v): Wishbone slave, 128 logic-analyzer bits,
// MPRJ_IO_PADS GPIOs, analog_io, user_clock2, user_irq[2:0], power pins.
//
// Address plan (docs/interfaces.md): Caravel sends every 0x3xxx_xxxx access here.
//   0x3000_0000 - 0x3000_07FF  wb_npu
//   everything else            default slave: acks next cycle, reads 0
//                              (pvt_sensor 0x3001_xxxx / sram_test 0x3002_xxxx go here
//                              once those blocks exist)
// stb/cyc are gated so wb_npu only ever sees its own addresses: wb_npu ignores
// address bits above [10] and would otherwise answer at every alias.
//
// IRQs: user_irq[0] = NPU error/overflow. GPIOs: all inputs (io_oeb = 1), outputs 0.
`default_nettype none
`ifndef MPRJ_IO_PADS
`define MPRJ_IO_PADS 38
`endif

module user_project_wrapper #(
    parameter BITS = 32
) (
`ifdef USE_POWER_PINS
    inout vdda1,        // user area 1 3.3V supply
    inout vdda2,        // user area 2 3.3V supply
    inout vssa1,        // user area 1 analog ground
    inout vssa2,        // user area 2 analog ground
    inout vccd1,        // user area 1 1.8V supply
    inout vccd2,        // user area 2 1.8v supply
    inout vssd1,        // user area 1 digital ground
    inout vssd2,        // user area 2 digital ground
`endif

    // Wishbone Slave ports (WB MI A)
    input  wire        wb_clk_i,
    input  wire        wb_rst_i,
    input  wire        wbs_stb_i,
    input  wire        wbs_cyc_i,
    input  wire        wbs_we_i,
    input  wire [3:0]  wbs_sel_i,
    input  wire [31:0] wbs_dat_i,
    input  wire [31:0] wbs_adr_i,
    output wire        wbs_ack_o,
    output wire [31:0] wbs_dat_o,

    // Logic Analyzer Signals
    input  wire [127:0] la_data_in,
    output wire [127:0] la_data_out,
    input  wire [127:0] la_oenb,

    // IOs
    input  wire [`MPRJ_IO_PADS-1:0] io_in,
    output wire [`MPRJ_IO_PADS-1:0] io_out,
    output wire [`MPRJ_IO_PADS-1:0] io_oeb,

    // Analog (direct connection to GPIO pad---use with caution)
    // Note that analog I/O is not available on the 7 lowest-numbered
    // GPIO pads, and so the analog_io indexing is offset from the
    // GPIO indexing by 7 (also upper 2 GPIOs do not have analog_io).
    inout  wire [`MPRJ_IO_PADS-10:0] analog_io,

    // Independent clock (on independent integer divider)
    input  wire user_clock2,

    // User maskable interrupt signals
    output wire [2:0] user_irq
);
    // ---- address decode
    wire acc     = wbs_stb_i && wbs_cyc_i;
    wire npu_sel = (wbs_adr_i[31:16] == 16'h3000) && (wbs_adr_i[15:11] == 5'd0);

    // ---- wb_npu
    wire        npu_ack, npu_irq;
    wire [31:0] npu_dat;
    wb_npu u_npu (
`ifdef USE_POWER_PINS
        .vccd1     (vccd1),
        .vssd1     (vssd1),
`endif
        .wb_clk_i  (wb_clk_i),
        .wb_rst_i  (wb_rst_i),
        .wbs_stb_i (wbs_stb_i && npu_sel),
        .wbs_cyc_i (wbs_cyc_i && npu_sel),
        .wbs_we_i  (wbs_we_i),
        .wbs_sel_i (wbs_sel_i),
        .wbs_dat_i (wbs_dat_i),
        .wbs_adr_i (wbs_adr_i),
        .wbs_ack_o (npu_ack),
        .wbs_dat_o (npu_dat),
        .irq       (npu_irq)
    );

    // ---- default slave: every other address acks one cycle later and reads 0,
    // so a stray access can never hang the CPU
    reg dflt_ack;
    always @(posedge wb_clk_i) begin
        if (wb_rst_i) dflt_ack <= 1'b0;
        else          dflt_ack <= acc && !npu_sel && !dflt_ack;
    end

    assign wbs_ack_o = npu_ack | dflt_ack;
    assign wbs_dat_o = npu_ack ? npu_dat : 32'h0;

    // ---- IRQs and tie-offs
    assign user_irq    = {2'b00, npu_irq};
    assign la_data_out = 128'h0;
    assign io_out      = {`MPRJ_IO_PADS{1'b0}};
    assign io_oeb      = {`MPRJ_IO_PADS{1'b1}};     // all pads are inputs
endmodule
`default_nettype wire

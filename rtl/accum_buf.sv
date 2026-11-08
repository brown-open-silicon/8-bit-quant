// Accumulator buffer: sums array outputs across K-tiles.
//
// A layer with K inputs is computed as K/N tiles. Each tile produces a
// partial result per input vector; this buffer adds them up:
//
//   in_first=1 : acc[addr] <=            in_vec   (first K-tile: overwrite)
//   in_first=0 : acc[addr] <= acc[addr] + in_vec   (later tiles: accumulate)
//
// DEPTH rows, each N lanes of ACC_W bits. Stored in flops for now; a real
// chip would use SRAM here (DEPTH*N*ACC_W bits = 8 Kb at the defaults).
//
// Two-stage pipeline (keeps the 16:1 row select out of the adder's cycle):
//   stage 1: read the row (or 0 if first), register it with the input
//   stage 2: add, write back
// If the same row arrives on consecutive cycles, stage 2's sum is forwarded
// into stage 1. A write lands 2 cycles after in_valid; busy covers that.
//
// Read port has 1-cycle latency. ovf is a sticky flag set if any lane's
// signed add overflows ACC_W bits.
module accum_buf #(
    parameter int N      = 16,
    parameter int IN_W   = 16,
    parameter int ACC_W  = 32,
    parameter int DEPTH  = 16,
    localparam int AW    = $clog2(DEPTH)
) (
    input  logic                  clk,
    input  logic                  rst_n,
    // write / accumulate
    input  logic                  in_valid,
    input  logic                  in_first,
    input  logic [AW-1:0]         in_addr,
    input  logic [IN_W*N-1:0]     in_vec,     // lane n = in_vec[IN_W*n +: IN_W], signed
    // read
    input  logic                  rd_en,
    input  logic [AW-1:0]         rd_addr,
    output logic                  rd_valid,
    output logic [ACC_W*N-1:0]    rd_vec,     // lane n = rd_vec[ACC_W*n +: ACC_W], signed
    output logic                  busy,       // an accumulate is still in the pipeline
    // status
    input  logic                  ovf_clear,
    output logic                  ovf
);
    logic signed [ACC_W-1:0] mem [DEPTH][N];
    logic [N-1:0] lane_ovf;

    // stage-1 registers (shared by all lanes)
    logic          v1;
    logic [AW-1:0] a1;
    logic          fwd;                      // stage 2 writes the row stage 1 wants
    assign fwd  = v1 && (a1 == in_addr) && !in_first;
    assign busy = v1;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin v1 <= 1'b0; a1 <= '0; end
        else begin        v1 <= in_valid; a1 <= in_addr; end
    end

    genvar n;
    generate
        for (n = 0; n < N; n++) begin : g_lane
            logic signed [ACC_W-1:0] x1, base1, sum;
            // stage 1
            always_ff @(posedge clk) begin
                if (in_valid) begin
                    x1    <= ACC_W'($signed(in_vec[IN_W*n +: IN_W]));
                    base1 <= in_first ? '0 : (fwd ? sum : mem[in_addr][n]);
                end
            end
            // stage 2
            assign sum = base1 + x1;
            // signed overflow: operands same sign, result different sign
            assign lane_ovf[n] = v1 && (base1[ACC_W-1] == x1[ACC_W-1])
                                    && (sum[ACC_W-1]   != x1[ACC_W-1]);
            always_ff @(posedge clk) begin
                if (v1) mem[a1][n] <= sum;
            end

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n)     rd_vec[ACC_W*n +: ACC_W] <= '0;
                else if (rd_en) rd_vec[ACC_W*n +: ACC_W] <= mem[rd_addr][n];
            end
        end
    endgenerate

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_valid <= 1'b0;
            ovf      <= 1'b0;
        end else begin
            rd_valid <= rd_en;
            if (ovf_clear)     ovf <= 1'b0;
            else if (|lane_ovf) ovf <= 1'b1;
        end
    end
endmodule

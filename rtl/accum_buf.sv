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
    // status
    input  logic                  ovf_clear,
    output logic                  ovf
);
    logic signed [ACC_W-1:0] mem [DEPTH][N];
    logic [N-1:0] lane_ovf;

    genvar n;
    generate
        for (n = 0; n < N; n++) begin : g_lane
            logic signed [ACC_W-1:0] x, base, sum;
            assign x    = ACC_W'($signed(in_vec[IN_W*n +: IN_W]));
            assign base = in_first ? '0 : mem[in_addr][n];
            assign sum  = base + x;
            // signed overflow: operands same sign, result different sign
            assign lane_ovf[n] = in_valid && (base[ACC_W-1] == x[ACC_W-1])
                                          && (sum[ACC_W-1]  != x[ACC_W-1]);

            always_ff @(posedge clk) begin
                if (in_valid) mem[in_addr][n] <= sum;
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

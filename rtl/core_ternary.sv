// Ternary compute core = 16x16 systolic array + int32 accumulator + requant.
//
//   a_vec ──▶ array_ternary ──c_vec──▶ accum_buf ──rd_vec──▶ postproc ──▶ q_vec (int8)
//   (addr, first) ──▶ delay line (LAT cycles) ──┘                    └──▶ wide_vec (int32)
//
// Each input vector is tagged with:
//   in_addr  : which accumulator row its result goes to (e.g. image index)
//   in_first : 1 on the first K-tile (overwrite), 0 afterwards (add)
// The tags ride a LAT-deep delay line so they reach the accumulator on the
// same cycle as the array result they belong to.
//
// Usage for a layer of K inputs, M vectors, N outputs:
//   for t in 0..K/N-1:
//       load weight tile t           (N cycles, w_load)
//       stream M vectors, addr=i, first=(t==0)
//       wait for the pipeline to drain before the next weight load
//   read rows 0..M-1: rd_vec (raw int32) after 1 cycle,
//   q_vec / wide_vec (requantized) when pp_valid pulses (N+2 cycles with the
//   default 1-lane postproc); wait for pp_valid before the next rd_en
//
// Do not load weights while results are still in flight: the PEs would use
// the new weights for vectors already inside the array.
module core_ternary #(
    parameter int N      = 16,
    parameter int PSUM_W = 16,
    parameter int ACC_W  = 32,
    parameter int DEPTH  = 16,
    parameter int B_W    = 48,
    localparam int AW    = $clog2(DEPTH),
    localparam int LAT   = 2 * N - 1
) (
    input  logic                  clk,
    input  logic                  rst_n,
    // weights
    input  logic                  w_load,
    input  logic [$clog2(N)-1:0]  w_row,
    input  logic [2*N-1:0]        w_data,
    // activations
    input  logic                  in_valid,
    input  logic                  in_first,
    input  logic [AW-1:0]         in_addr,
    input  logic [8*N-1:0]        a_vec,
    output logic                  busy,       // results still in flight
    // results
    input  logic                  rd_en,
    input  logic [AW-1:0]         rd_addr,
    output logic                  rd_valid,
    output logic [ACC_W*N-1:0]    rd_vec,
    // post-processing (requantization) config + output
    input  logic signed [15:0]    pp_m,
    input  logic [5:0]            pp_sh,
    input  logic                  pp_relu,
    input  logic [B_W*N-1:0]      pp_bias,
    output logic                  pp_valid,
    output logic [32*N-1:0]       wide_vec,
    output logic [8*N-1:0]        q_vec,
    // status
    input  logic                  err_clear,
    output logic                  err,        // bit-flipped weight seen (code 11)
    output logic                  ovf         // accumulator overflow
);
    logic                  arr_valid;
    logic [PSUM_W*N-1:0]   arr_c;

    array_ternary #(.N(N), .PSUM_W(PSUM_W)) u_array (
        .clk, .rst_n,
        .w_load, .w_row, .w_data,
        .in_valid, .a_vec,
        .out_valid (arr_valid),
        .c_vec     (arr_c),
        .err_clear,
        .err
    );

    // tag delay line: {first, addr} travels with the data
    logic [AW:0] tag_sr [LAT];
    logic [LAT-1:0] inflight;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < LAT; i++) tag_sr[i] <= '0;
            inflight <= '0;
        end else begin
            tag_sr[0] <= {in_first, in_addr};
            for (int i = 1; i < LAT; i++) tag_sr[i] <= tag_sr[i-1];
            inflight <= {inflight[LAT-2:0], in_valid};
        end
    end
    logic pp_busy;
    logic acc_busy;
    assign busy = |inflight | acc_busy | pp_busy;

    accum_buf #(.N(N), .IN_W(PSUM_W), .ACC_W(ACC_W), .DEPTH(DEPTH)) u_acc (
        .clk, .rst_n,
        .in_valid (arr_valid),
        .in_first (tag_sr[LAT-1][AW]),
        .in_addr  (tag_sr[LAT-1][AW-1:0]),
        .in_vec   (arr_c),
        .rd_en, .rd_addr, .rd_valid, .rd_vec, .busy (acc_busy),
        .ovf_clear(err_clear),
        .ovf
    );

    postproc #(.N(N), .ACC_W(ACC_W), .B_W(B_W)) u_pp (
        .clk, .rst_n,
        .m (pp_m), .sh (pp_sh), .relu (pp_relu), .bias_vec (pp_bias),
        .in_valid (rd_valid), .in_vec (rd_vec),
        .busy (pp_busy),
        .out_valid (pp_valid), .wide_vec, .q_vec
    );
endmodule

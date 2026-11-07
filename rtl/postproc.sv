// Post-processing (requantization) after a layer: int32 accumulator -> int8.
//
//   y    = (acc * m + bias[n] + 2^(sh-1)) >>> sh     // multiply, add bias, round
//   wide = saturate(y) to int32                      // e.g. final-layer logits
//   q    = clamp(y, relu ? 0 : -127, 127)            // next layer's int8 input
//
// m and sh together are a fixed-point version of the float scale
// (M ~= m / 2^sh), so the chip needs no floating point. Shared m/sh
// (per-tensor scale), per-lane bias (per-neuron).
// Bit-exact model: quant/qlib.py requant().
//
// P = lanes processed per cycle (must divide N). The multiplier is the big
// part, so P trades area for speed:
//   P = N : all lanes at once, out_valid 3 cycles after in_valid
//   P = 1 : one shared multiplier, out_valid N+2 cycles after in_valid (default;
//           a row is only requantized once per layer, so speed rarely matters)
// Do not assert in_valid again until out_valid (busy = 1 while working).
module postproc #(
    parameter int N     = 16,
    parameter int P     = 1,
    parameter int ACC_W = 32,
    parameter int M_W   = 16,
    parameter int B_W   = 48,
    parameter int SH_W  = 6
) (
    input  logic                      clk,
    input  logic                      rst_n,
    // configuration (from registers)
    input  logic signed [M_W-1:0]     m,
    input  logic        [SH_W-1:0]    sh,
    input  logic                      relu,
    input  logic        [B_W*N-1:0]   bias_vec,   // lane n = bias_vec[B_W*n +: B_W], signed
    // data
    input  logic                      in_valid,
    input  logic        [ACC_W*N-1:0] in_vec,
    output logic                      busy,
    output logic                      out_valid,
    output logic        [32*N-1:0]    wide_vec,   // lane n: signed int32
    output logic        [8*N-1:0]     q_vec       // lane n: signed int8
);
    localparam int G   = N / P;                   // groups (cycles) per row
    localparam int GW  = (G > 1) ? $clog2(G) : 1;
    localparam int S_W = ACC_W + M_W + 2;         // product + bias + rounding headroom

    // ---- sequencing: group g enters stage 1, group g1 leaves stage 2
    logic [ACC_W*N-1:0] acc_q;
    logic [GW-1:0]      g, g1;
    logic               run, v1;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_q <= '0; g <= '0; g1 <= '0; run <= 1'b0; v1 <= 1'b0; out_valid <= 1'b0;
        end else begin
            out_valid <= v1 && (g1 == GW'(G - 1));
            v1 <= run;
            g1 <= g;
            if (in_valid) begin
                acc_q <= in_vec; g <= '0; run <= 1'b1;
            end else if (run) begin
                if (g == GW'(G - 1)) run <= 1'b0;
                else                 g   <= g + 1'b1;
            end
        end
    end
    assign busy = run | v1;

    // 2^(sh-1), or 0 when sh == 0
    logic signed [S_W-1:0] rnd;
    assign rnd = (sh == 0) ? '0 : (S_W'(1) <<< (sh - 1));

    genvar p;
    generate
        for (p = 0; p < P; p++) begin : g_lane
            // stage 1: multiply + bias for lane g*P + p
            logic signed [ACC_W-1:0] acc;
            logic signed [B_W-1:0]   b;
            logic signed [S_W-1:0]   s1, y;
            assign acc = acc_q[ACC_W * (g * P + p) +: ACC_W];
            assign b   = bias_vec[B_W * (g * P + p) +: B_W];
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) s1 <= '0;
                else        s1 <= S_W'(acc) * S_W'(m) + S_W'(b);
            end

            // stage 2: round, shift, saturate, clamp -> lane g1*P + p
            assign y = (s1 + rnd) >>> sh;
            logic signed [31:0] w_sat;
            logic signed [7:0]  q_sat;
            always_comb begin
                if      (y >  S_W'(32'sh7FFF_FFFF)) w_sat = 32'sh7FFF_FFFF;
                else if (y < -S_W'(64'sh8000_0000)) w_sat = 32'sh8000_0000;
                else                                 w_sat = y[31:0];
                if      (y > S_W'(127))              q_sat = 8'sd127;
                else if (relu && y < 0)              q_sat = 8'sd0;
                else if (y < -S_W'(127))             q_sat = -8'sd127;
                else                                 q_sat = y[7:0];
            end
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    for (int i = 0; i < G; i++) begin
                        wide_vec[32 * (i * P + p) +: 32] <= '0;
                        q_vec[8 * (i * P + p) +: 8]      <= '0;
                    end
                end else if (v1) begin
                    wide_vec[32 * (g1 * P + p) +: 32] <= w_sat;
                    q_vec[8 * (g1 * P + p) +: 8]      <= q_sat;
                end
            end
        end
    endgenerate
endmodule

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
//   P = N : all lanes at once, out_valid 5 cycles after in_valid
//   P = 1 : one shared multiplier, out_valid N+4 cycles after in_valid (default;
//           a row is only requantized once per layer, so speed rarely matters)
// Pipeline: stage 0 lane select, stage 1 multiply + bias, stage 2 round +
// shift, stage 3 saturate + store. The 16:1 lane select used to sit in front
// of the multiplier in the same cycle. Round/shift and saturate used to share one cycle and missed timing at
// the slow corner (issue #6, path 2), so they are split.
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

    // ---- sequencing: group g enters stage 0, g0 in stage 1, g1 in stage 2, g2 in stage 3
    logic [ACC_W*N-1:0] acc_q;
    logic [GW-1:0]      g, g0, g1, g2;
    logic               run, v0, v1, v2;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_q <= '0; g <= '0; g0 <= '0; g1 <= '0; g2 <= '0;
            run <= 1'b0; v0 <= 1'b0; v1 <= 1'b0; v2 <= 1'b0; out_valid <= 1'b0;
        end else begin
            out_valid <= v2 && (g2 == GW'(G - 1));
            v2 <= v1;
            g2 <= g1;
            v1 <= v0;
            g1 <= g0;
            v0 <= run;
            g0 <= g;
            if (in_valid) begin
                acc_q <= in_vec; g <= '0; run <= 1'b1;
            end else if (run) begin
                if (g == GW'(G - 1)) run <= 1'b0;
                else                 g   <= g + 1'b1;
            end
        end
    end
    assign busy = run | v0 | v1 | v2;

    // 2^(sh-1), or 0 when sh == 0
    logic signed [S_W-1:0] rnd;
    assign rnd = (sh == 0) ? '0 : (S_W'(1) <<< (sh - 1));

    genvar p;
    generate
        for (p = 0; p < P; p++) begin : g_lane
            // stage 0: select lane g*P + p (registered)
            logic signed [ACC_W-1:0] acc;
            logic signed [B_W-1:0]   b;
            logic signed [S_W-1:0]   s1, y, y2;
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin acc <= '0; b <= '0; end
                else begin
                    acc <= acc_q[ACC_W * (g * P + p) +: ACC_W];
                    b   <= bias_vec[B_W * (g * P + p) +: B_W];
                end
            end
            // stage 1: multiply + bias
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) s1 <= '0;
                else        s1 <= S_W'(acc) * S_W'(m) + S_W'(b);
            end

            // stage 2: round, shift (registered into y2)
            assign y = (s1 + rnd) >>> sh;
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) y2 <= '0;
                else        y2 <= y;
            end

            // stage 3: saturate, clamp -> lane g2*P + p
            logic signed [31:0] w_sat;
            logic signed [7:0]  q_sat;
            always_comb begin
                if      (y2 >  S_W'(32'sh7FFF_FFFF)) w_sat = 32'sh7FFF_FFFF;
                else if (y2 < -S_W'(64'sh8000_0000)) w_sat = 32'sh8000_0000;
                else                                 w_sat = y2[31:0];
                if      (y2 > S_W'(127))              q_sat = 8'sd127;
                else if (relu && y2 < 0)              q_sat = 8'sd0;
                else if (y2 < -S_W'(127))             q_sat = -8'sd127;
                else                                 q_sat = y2[7:0];
            end
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    for (int i = 0; i < G; i++) begin
                        wide_vec[32 * (i * P + p) +: 32] <= '0;
                        q_vec[8 * (i * P + p) +: 8]      <= '0;
                    end
                end else if (v2) begin
                    wide_vec[32 * (g2 * P + p) +: 32] <= w_sat;
                    q_vec[8 * (g2 * P + p) +: 8]      <= q_sat;
                end
            end
        end
    endgenerate
endmodule

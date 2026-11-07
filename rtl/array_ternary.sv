// N x N weight-stationary ternary systolic array.
//
// Computes, for each input vector a (length N):   c[n] = sum_k a[k] * W[k][n]
// i.e. one row of C = A x W, where W is an N x N ternary weight tile.
//
//              a[0] ─▶ PE(0,0) ─▶ PE(0,1) ─▶ ... ─▶ PE(0,N-1)
//                         │          │                 │       activations move RIGHT
//   (skewed)   a[1] ─▶ PE(1,0) ─▶ PE(1,1) ─▶ ... ─▶ PE(1,N-1)
//                         │          │                 │       partial sums move DOWN
//                        ...        ...               ...
//              a[N-1]▶ PE(N-1,0) ─▶ ...           ─▶ PE(N-1,N-1)
//                         ▼          ▼                 ▼
//                       c[0]       c[1]     ...      c[N-1]    (deskewed)
//
// Row k's input is delayed k cycles (skew) so it meets the partial sum coming
// down from row k-1 at the right time. Column n's output is delayed N-1-n
// cycles (deskew) so all N results come out on the same cycle.
//
// Throughput: one input vector per cycle.  Latency: 2N-1 cycles.
//
// Weights: load one row per cycle: w_load=1, w_row=k, w_data[2n+1:2n] = W[k][n].
module array_ternary #(
    parameter int N      = 16,
    parameter int PSUM_W = 16   // |c| <= N*128 = 2048 for N=16, fits in 13 bits
) (
    input  logic                       clk,
    input  logic                       rst_n,
    // weight load
    input  logic                       w_load,
    input  logic [$clog2(N)-1:0]       w_row,
    input  logic [2*N-1:0]             w_data,
    // activation stream
    input  logic                       in_valid,
    input  logic [8*N-1:0]             a_vec,     // a[k] = a_vec[8k+7:8k], signed
    output logic                       out_valid,
    output logic [PSUM_W*N-1:0]        c_vec,     // c[n] = c_vec[PSUM_W*n +: PSUM_W], signed
    // radiation / bit-flip monitor
    input  logic                       err_clear,
    output logic                       err        // sticky: some stored weight read as 11
);
    localparam int LAT = 2 * N - 1;

    // a_h[k][n]: activation entering PE(k,n) from the left
    // p_v[k][n]: partial sum entering PE(k,n) from above
    logic signed [7:0]        a_h [N][N+1];
    logic signed [PSUM_W-1:0] p_v [N+1][N];
    logic [N*N-1:0]           bad;

    genvar k, n;
    generate
        // ---- input skew: row k delayed k cycles
        for (k = 0; k < N; k++) begin : g_skew
            if (k == 0) begin : g_nodelay
                assign a_h[0][0] = a_vec[7:0];
            end else begin : g_delay
                logic signed [7:0] sr [k];
                always_ff @(posedge clk or negedge rst_n) begin
                    if (!rst_n) for (int i = 0; i < k; i++) sr[i] <= '0;
                    else begin
                        sr[0] <= a_vec[8*k +: 8];
                        for (int i = 1; i < k; i++) sr[i] <= sr[i-1];
                    end
                end
                assign a_h[k][0] = sr[k-1];
            end
        end

        // ---- the PE grid
        for (n = 0; n < N; n++) begin : g_top
            assign p_v[0][n] = '0;
        end
        for (k = 0; k < N; k++) begin : g_row
            for (n = 0; n < N; n++) begin : g_col
                pe_ws_ternary #(.PSUM_W(PSUM_W)) pe (
                    .clk     (clk),
                    .rst_n   (rst_n),
                    .w_load  (w_load && (w_row == k)),
                    .w_in    (w_data[2*n +: 2]),
                    .a_in    (a_h[k][n]),
                    .psum_in (p_v[k][n]),
                    .a_out   (a_h[k][n+1]),
                    .psum_out(p_v[k+1][n]),
                    .w_bad   (bad[k*N+n])
                );
            end
        end

        // ---- output deskew: column n delayed N-1-n cycles
        for (n = 0; n < N; n++) begin : g_deskew
            if (n == N - 1) begin : g_nodelay
                assign c_vec[PSUM_W*n +: PSUM_W] = p_v[N][n];
            end else begin : g_delay
                localparam int D = N - 1 - n;
                logic signed [PSUM_W-1:0] sr [D];
                always_ff @(posedge clk or negedge rst_n) begin
                    if (!rst_n) for (int i = 0; i < D; i++) sr[i] <= '0;
                    else begin
                        sr[0] <= p_v[N][n];
                        for (int i = 1; i < D; i++) sr[i] <= sr[i-1];
                    end
                end
                assign c_vec[PSUM_W*n +: PSUM_W] = sr[D-1];
            end
        end
    endgenerate

    // ---- valid pipeline (matches the data latency)
    logic [LAT-1:0] vsr;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) vsr <= '0;
        else        vsr <= {vsr[LAT-2:0], in_valid};
    end
    assign out_valid = vsr[LAT-1];

    // ---- sticky error flag
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)         err <= 1'b0;
        else if (err_clear) err <= 1'b0;
        else if (|bad)      err <= 1'b1;
    end
endmodule

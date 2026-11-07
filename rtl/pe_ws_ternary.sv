// Weight-stationary ternary PE for the systolic array.
//
// Each PE holds ONE 2-bit weight (loaded once, then reused for every input).
// Every cycle it:
//   - passes the activation it received to the PE on its right (a_out)
//   - adds (+a), subtracts (-a), or skips (0) into the partial sum and
//     passes that down to the PE below (psum_out)
//
// Weight code: 00 -> 0, 01 -> +1, 10 -> -1, 11 -> INVALID (bit flip) -> 0, w_bad=1
module pe_ws_ternary #(
    parameter int PSUM_W = 16
) (
    input  logic                     clk,
    input  logic                     rst_n,
    input  logic                     w_load,    // load w_in into this PE
    input  logic        [1:0]        w_in,
    input  logic signed [7:0]        a_in,      // from the left
    input  logic signed [PSUM_W-1:0] psum_in,   // from above
    output logic signed [7:0]        a_out,     // to the right
    output logic signed [PSUM_W-1:0] psum_out,  // to below
    output logic                     w_bad      // stored weight is the invalid code
);
    logic [1:0] w;
    logic signed [PSUM_W-1:0] a_ext;
    assign a_ext = PSUM_W'(a_in);
    assign w_bad = (w == 2'b11);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            w        <= 2'b00;
            a_out    <= '0;
            psum_out <= '0;
        end else begin
            if (w_load) w <= w_in;
            a_out <= a_in;
            case (w)
                2'b01:   psum_out <= psum_in + a_ext;
                2'b10:   psum_out <= psum_in - a_ext;
                default: psum_out <= psum_in;  // 00 = zero weight, 11 = invalid
            endcase
        end
    end
endmodule

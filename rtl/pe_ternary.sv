// Ternary processing element: acc += a * w, where w is in {-1, 0, +1}.
// No multiplier -- just add, subtract, or skip.
//
// Weight encoding (2 bits, matches quant/qlib.py):
//   00 -> 0     01 -> +1     10 -> -1     11 -> INVALID (a stored bit flipped)
// An invalid code is treated as 0 and raises a sticky error flag. That's
// free error detection that falls out of the encoding.
module pe_ternary #(
    parameter int ACC_W = 32
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    clear,  // start a new dot product (also clears err)
    input  logic                    en,
    input  logic signed [7:0]       a,      // int8 activation
    input  logic        [1:0]       w,      // ternary weight code
    output logic signed [ACC_W-1:0] acc,
    output logic                    err     // saw an invalid weight since last clear
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= '0;
            err <= 1'b0;
        end else if (clear) begin
            acc <= '0;
            err <= 1'b0;
        end else if (en) begin
            case (w)
                2'b01:   acc <= acc + ACC_W'(a);
                2'b10:   acc <= acc - ACC_W'(a);
                2'b11:   err <= 1'b1;
                default: ;  // 2'b00: weight is zero, skip
            endcase
        end
    end
endmodule

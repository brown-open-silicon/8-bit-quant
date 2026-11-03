// INT8 multiply-accumulate unit: acc += a * w   (signed 8b x 8b -> 32b)
// The baseline processing element (PE) for the 16x16 array.
module mac_int8 #(
    parameter int ACC_W = 32
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    clear,  // start a new dot product
    input  logic                    en,     // accumulate this cycle
    input  logic signed [7:0]       a,      // activation
    input  logic signed [7:0]       w,      // weight
    output logic signed [ACC_W-1:0] acc
);
    logic signed [15:0] prod;
    assign prod = a * w;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)      acc <= '0;
        else if (clear)  acc <= '0;
        else if (en)     acc <= acc + ACC_W'(prod);
    end
endmodule

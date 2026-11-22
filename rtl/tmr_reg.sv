// no vnc needed

(* keep_hierarchy *)
module tmr_copy #(
    parameter int W = 8
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         we,
    input  logic [W-1:0] d,
    input  logic [W-1:0] vote,
    output logic [W-1:0] r
);
    always_ff @(posedge clk or negedge rst_n) begin
        // can i replace r and load w/ params that we alr have?
        // -> yes, those were buffers
        // what is posedge and negedge?'
        // -> posedge is like the edge of 1 bit sig and opposite for negedge
        if (!rst_n)  r <= '0; // reset: all bits 0. is rst_n just rst & what is begin?
        else if (we) r <= d; // store new val
        else         r <= vote; // keep as old val
        // assign vote = a&b + a&c + b&c;
        // -> this is permenant
    end
endmodule

module tmr_reg #(
    parameter int W = 8 // how many bits wide for TMR
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         we,
    input  logic [W-1:0] d, // W bits, from W-1 to 0
    output logic [W-1:0] q,
    output logic         err // default 1 bit
);

// logic is the type for every signal
// -> what is a signal? Is it just I/O?
// --> any bundle of wires carrying bits. It's either ports (external signals that the module can see) or internal signals that only this module can see (the a/b/c copies and vote)
// why only 3 parameters? We have rst, clk, d, q, we, err
// -> before was just a buffer

    logic [W-1:0] a, b, c, vote;

    tmr_copy #(.W(W)) ua (.clk(clk), .rst_n(rst_n), .we(we), .d(d), .vote(vote), .r(a));
    tmr_copy #(.W(W)) ub (.clk(clk), .rst_n(rst_n), .we(we), .d(d), .vote(vote), .r(b));
    tmr_copy #(.W(W)) uc (.clk(clk), .rst_n(rst_n), .we(we), .d(d), .vote(vote), .r(c));

    assign vote = (a & b) | (a & c) | (b & c); // majority rule
    assign q    = vote; // shouldn't this be the majority though? why specifically a? -yes
    //assign err = 1'b0; // is this just 1? 1 bit of 0
    assign err  = (a != b) || (b != c);
endmodule

// break down this compile command: scripts/eda.sh "iverilog -g2012 -o build/tmr.vvp rtl/tmr_reg.sv"
// scripts/eda.sh -> whole file that is used to run the command inside of the docker terminal
// iverilog - icarus verilog compilers
// -g2012 - just the standard (like C++17)
// -o build/tmr.vvp - the compiled version (git ignores build)
// rtl/tmr_reg.sv - file to compile

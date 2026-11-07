// Wishbone host interface: lets a CPU (Caravel's RISC-V management core)
// drive core_ternary through a 32-bit bus instead of ~2,100 pins.
//
// The CPU sees memory-mapped registers (byte offsets from the NPU base;
// on Caravel the user-project base is 0x3000_0000):
//
//   off    name      access  meaning
//   0x000  ID        R       0x4E505531 ("NPU1")
//   0x004  STATUS    R       [0] busy  [1] err (bit flip)  [2] ovf  [3] result ready
//   0x008  CTRL      W       [0] clear err/ovf
//   0x00C  W_DATA    RW      one weight row: 16 x 2-bit codes, lane n = bits [2n+1:2n]
//   0x010  W_LOAD    W       write k -> load W_DATA into array row k
//   0x014  A_VEC0-3  RW      16 int8 activations, 4 per word (0x014..0x020)
//   0x024  PUSH      W       [3:0] acc row, [4] first tile -> stream A_VEC into the array
//   0x028  PP_CFG    RW      [15:0] m (signed)  [21:16] shift  [24] relu
//   0x02C  READ      W       [3:0] acc row -> requantize it; result in Q / WIDE
//   0x040  Q0-3      R       16 int8 results, 4 per word (0x040..0x04C)
//   0x080  WIDE0-15  R       16 int32 results (0x080..0x0BC)
//   0x100  BIAS      RW      lane n: 0x100+8n = bits [31:0], 0x104+8n = bits [47:32]
//
// Typical layer (see tb/npu_driver.py, the reference "firmware"):
//   write PP_CFG, BIAS
//   for each K-tile: 16x {W_DATA, W_LOAD}; per image {A_VEC0-3, PUSH}; poll STATUS.busy
//   per image: READ, poll STATUS.ready, read Q (or WIDE)
module wb_npu #(
    parameter int N   = 16,
    parameter int B_W = 48
) (
    input  logic        wb_clk_i,
    input  logic        wb_rst_i,     // active high (Caravel convention)
    input  logic        wbs_stb_i,
    input  logic        wbs_cyc_i,
    input  logic        wbs_we_i,
    input  logic [3:0]  wbs_sel_i,
    input  logic [31:0] wbs_dat_i,
    input  logic [31:0] wbs_adr_i,
    output logic        wbs_ack_o,
    output logic [31:0] wbs_dat_o,
    output logic        irq          // err or ovf (bit flip / overflow seen)
);
    localparam logic [31:0] ID = 32'h4E50_5531;

    logic clk, rst_n;
    assign clk   = wb_clk_i;
    assign rst_n = ~wb_rst_i;

    // ---- bus handshake: single-cycle ack
    logic       req, wr;
    logic [6:0] widx;                     // word index, byte offset [8:2]
    assign req  = wbs_stb_i && wbs_cyc_i && !wbs_ack_o;
    assign wr   = req && wbs_we_i;
    assign widx = wbs_adr_i[8:2];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) wbs_ack_o <= 1'b0;
        else        wbs_ack_o <= req;
    end

    // ---- registers
    logic [31:0]        w_data;
    logic [8*N-1:0]     a_vec;
    logic [31:0]        pp_cfg;
    logic [B_W*N-1:0]   bias;
    logic [8*N-1:0]     q_res;
    logic [32*N-1:0]    wide_res;
    logic               res_ready;

    // one-cycle command pulses
    logic               w_load, in_valid, rd_en, err_clear;
    logic [3:0]         w_row, in_addr, rd_addr;
    logic               in_first;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            w_data <= '0; a_vec <= '0; pp_cfg <= '0; bias <= '0;
            {w_load, in_valid, rd_en, err_clear} <= '0;
            {w_row, in_addr, rd_addr, in_first} <= '0;
        end else begin
            {w_load, in_valid, rd_en, err_clear} <= '0;
            if (wr) begin
                case (widx)
                    7'h02: err_clear <= wbs_dat_i[0];
                    7'h03: w_data    <= wbs_dat_i;
                    7'h04: begin w_load <= 1'b1; w_row <= wbs_dat_i[3:0]; end
                    7'h05, 7'h06, 7'h07, 7'h08:
                           a_vec[32*(widx-7'h05) +: 32] <= wbs_dat_i;
                    7'h09: begin in_valid <= 1'b1; in_addr <= wbs_dat_i[3:0];
                                 in_first <= wbs_dat_i[4]; end
                    7'h0A: pp_cfg    <= wbs_dat_i;
                    7'h0B: begin rd_en <= 1'b1; rd_addr <= wbs_dat_i[3:0]; end
                    default:
                        if (widx >= 7'h40 && widx < 7'h40 + 2 * N) begin
                            if (!widx[0]) bias[B_W*((widx-7'h40)>>1) +: 32]      <= wbs_dat_i;
                            else          bias[B_W*((widx-7'h40)>>1) + 32 +: 16] <= wbs_dat_i[15:0];
                        end
                endcase
            end
        end
    end

    // ---- the compute core
    logic busy, err, ovf, pp_valid;
    logic [32*N-1:0] wide_vec, rd_vec_unused;
    logic [8*N-1:0]  q_vec;
    logic            rd_valid_unused;

    core_ternary #(.N(N), .DEPTH(16), .B_W(B_W)) u_core (
        .clk, .rst_n,
        .w_load, .w_row, .w_data (w_data[2*N-1:0]),
        .in_valid, .in_first, .in_addr, .a_vec,
        .busy,
        .rd_en, .rd_addr, .rd_valid (rd_valid_unused), .rd_vec (rd_vec_unused),
        .pp_m (pp_cfg[15:0]), .pp_sh (pp_cfg[21:16]), .pp_relu (pp_cfg[24]),
        .pp_bias (bias),
        .pp_valid, .wide_vec, .q_vec,
        .err_clear, .err, .ovf
    );
    assign irq = err | ovf;

    // results are latched so the CPU can read them at its own pace
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q_res <= '0; wide_res <= '0; res_ready <= 1'b0;
        end else if (wr && widx == 7'h0B) begin   // clear on the READ write itself, so a
            res_ready <= 1'b0;                     // status poll can never see the old result

        end else if (pp_valid) begin
            q_res <= q_vec; wide_res <= wide_vec; res_ready <= 1'b1;
        end
    end

    // ---- read mux
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) wbs_dat_o <= '0;
        else if (req && !wbs_we_i) begin
            wbs_dat_o <= '0;
            if      (widx == 7'h00) wbs_dat_o <= ID;
            // busy also covers a PUSH accepted this cycle that hasn't entered the pipe yet
            else if (widx == 7'h01) wbs_dat_o <= {28'b0, res_ready, ovf, err, busy | in_valid};
            else if (widx == 7'h03) wbs_dat_o <= w_data;
            else if (widx >= 7'h05 && widx <= 7'h08) wbs_dat_o <= a_vec[32*(widx-7'h05) +: 32];
            else if (widx == 7'h0A) wbs_dat_o <= pp_cfg;
            else if (widx >= 7'h10 && widx <= 7'h13) wbs_dat_o <= q_res[32*(widx-7'h10) +: 32];
            else if (widx >= 7'h20 && widx < 7'h20 + N) wbs_dat_o <= wide_res[32*(widx-7'h20) +: 32];
            else if (widx >= 7'h40 && widx < 7'h40 + 2 * N) begin
                if (!widx[0]) wbs_dat_o <= bias[B_W*((widx-7'h40)>>1) +: 32];
                else          wbs_dat_o <= {16'b0, bias[B_W*((widx-7'h40)>>1) + 32 +: 16]};
            end
        end
    end
endmodule

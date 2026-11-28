// Wishbone host interface: lets a CPU (Caravel's RISC-V management core)
// drive core_ternary through a 32-bit bus instead of ~2,100 pins.
//
// The CPU sees memory-mapped registers (byte offsets from the NPU base;
// on Caravel the user-project base is 0x3000_0000):
//
//   off    name      access  meaning
//   0x000  ID        R       0x4E505531 ("NPU1")
//   0x004  STATUS    R       [0] busy  [1] err (any bit flip seen)  [2] ovf  [3] result ready
//                            [4] weight flip (code 11)  [5] PP_CFG copy flip (TMR, repaired)
//                            [6] BIAS parity error (reload BIAS)  [7] WMEM parity error (re-send tile)
//                            [8] row-tag copy flip (TMR, repaired)  [9] accumulator parity (re-run the layer)
//   0x008  CTRL      W       [0] clear err/ovf (a BIAS parity error stays until BIAS is rewritten)
//                            [1] clear ERRCNT
//   0x00C  W_DATA    RW      one weight row: 16 x 2-bit codes, lane n = bits [2n+1:2n]
//   0x010  W_LOAD    W       write k -> load W_DATA into array row k
//   0x014  A_VEC0-3  RW      16 int8 activations, 4 per word (0x014..0x020)
//   0x024  PUSH      W       [3:0] acc row, [4] first tile -> stream A_VEC into the array
//   0x028  PP_CFG    RW      [15:0] m (signed)  [21:16] shift  [24] relu
//   0x02C  READ      W       [3:0] acc row -> requantize it; result in Q / WIDE
//   0x030  W_TILE    W       [3:0] t -> stream weight tile t (WMEM rows 16t..16t+15)
//   0x034  ERRCNT    R       saturating upset counters (telemetry, docs/radiation.md):
//                            [7:0] weight 11  [15:8] PP_CFG TMR  [23:16] BIAS/WMEM/accumulator parity
//                            [31:24] row-tag TMR
//                            into the array, 1 row/cycle (16 cycles)
//   0x040  Q0-3      R       16 int8 results, 4 per word (0x040..0x04C)
//   0x080  WIDE0-15  R       16 int32 results (0x080..0x0BC)
//   0x100  BIAS      RW      lane n: 0x100+8n = bits [31:0], 0x104+8n = bits [47:32]
//   0x400  WMEM      RW      weight buffer: 256 rows (16 tiles x 16 rows), same
//                            format as W_DATA. Stock Sky130 SRAM macro (1 KB,
//                            sky130_sram_1kbyte_1rw1r_32x256_8): port 0 = bus,
//                            port 1 = array.
//
// Every access takes 2 cycles (request registered first). Register reads,
// WMEM reads and BIAS writes take 3 (an extra cycle keeps the slow-corner
// timing paths short, issue #6).
//
// Flow control (the bus waits instead of the CPU polling):
//   - W_TILE waits until in-flight results have left the array (weights are
//     stationary, so swapping them under live data would corrupt it)
//   - PUSH waits until a W_TILE burst has finished
// Typical layer (see tb/npu_driver.py, the reference "firmware"):
//   write PP_CFG, BIAS
//   for each K-tile: 16x {W_DATA, W_LOAD}; per image {A_VEC0-3, PUSH}; poll STATUS.busy
//     or, with the buffer: write up to 16 tiles to WMEM, then per tile
//     {W_TILE t; per image {A_VEC0-3, PUSH}} -- no polling needed
//   per image: READ, poll STATUS.ready, read Q (or WIDE)
module wb_npu #(
    parameter int N   = 16,
    parameter int B_W = 48
) (
`ifdef USE_POWER_PINS
    inout  wire         vccd1,        // 1.8 V
    inout  wire         vssd1,        // ground
`endif
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

    // ---- bus handshake
    // The request is captured in flops first (cycle 1) and decoded the next cycle (cycle 2), so the big address decode / read mux no big logic between the pins and the first flip flop. ack: cycle 2 (WMEM reads: cycle 3).
    // Input pins: wbs_adr_i/wbs_dat_i. The wires coming into wb_npu from the outside (the cpu through Careval's wiring). The issue is that those signals show up already late (issue #6). 
    logic        act;                     // a captured request waits to execute
    logic [31:0] adr_q, dat_q;
    logic        we_q;
    logic [3:0]  sel_q;
    logic        req, wr, mem_sel, stall, mem_pend, bias_pend; // mem_pend = a WMEM read is waiting for the SRAM to answer
    logic        rd_reg, rd_pend;         // register read: partial muxes in cycle 2, final mux + ack in cycle 3
    logic [6:0] widx;                     // register word index, byte offset [8:2]
    logic       busy, loading;
    logic       in_valid;
    assign mem_sel = adr_q[10];       // 0x400..0x7FF -> weight SRAM
    assign widx    = adr_q[8:2];
    assign stall   = we_q && !mem_sel &&
                     ((widx == 7'h09 && loading) ||                        // PUSH
                      (widx == 7'h0C && (loading || busy || in_valid)));   // W_TILE
    assign req  = act && !stall;          // execute the captured request now
    assign wr   = req && we_q && !mem_sel;
    // Issue #6: a BIAS write (widx 0x40..0x5F). Just a range check, cheap.
    logic bias_wr;
    assign bias_wr = wr && widx >= 7'h40 && widx < 7'h40 + 2 * N;
    assign rd_reg  = req && !we_q && !mem_sel;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wbs_ack_o <= 1'b0; mem_pend <= 1'b0; rd_pend <= 1'b0; act <= 1'b0;
            adr_q <= '0; dat_q <= '0; we_q <= 1'b0; sel_q <= '0;
        end else begin
            if (wbs_stb_i && wbs_cyc_i && !act && !wbs_ack_o && !mem_pend && !bias_pend && !rd_pend) begin
                // Issue #6: !bias_pend added so that we bloc capture of a second BIAS write
                act <= 1'b1;
                adr_q <= wbs_adr_i; dat_q <= wbs_dat_i; we_q <= wbs_we_i; sel_q <= wbs_sel_i;
            end else if (req) begin
                act <= 1'b0;
            end
            mem_pend  <= req && mem_sel && !we_q;   // SRAM read: data next cycle
            rd_pend   <= rd_reg;                    // register read: final mux next cycle
            // Issue #6: writes ack in cycle 2, except BIAS writes (cycle 3, bias_pend).
            // All reads ack in cycle 3 (mem_pend / rd_pend).
            // Only ack while the master is actually holding stb/cyc (Wishbone rule). A
            // flipped *_pend bit could otherwise ack between transfers and put the CPU
            // one ack ahead of the NPU (seen in the fault campaign as a hang).
            wbs_ack_o <= wbs_stb_i && wbs_cyc_i &&
                         ((req && we_q && !bias_wr) || mem_pend || bias_pend || rd_pend);
        end
    end

    // ---- weight buffer: stock Sky130 1 KB SRAM
    //   port 0 (RW): the bus.  port 1 (R): streams a tile into the array.
    logic        ld_run, ld_v;            // issuing reads / a row arrives this cycle
    logic [3:0]  ld_tile, ld_k, ld_kd;
    logic [31:0] mem_dout0, mem_dout1;
    assign loading = ld_run | ld_v;

    sky130_sram_1kbyte_1rw1r_32x256_8
`ifndef SYNTHESIS
        #(.VERBOSE(0))
`endif
    u_wmem (
`ifdef USE_POWER_PINS
        .vccd1 (vccd1), .vssd1 (vssd1),
`endif
        .clk0 (clk), .csb0 (!(req && mem_sel)), .web0 (!we_q), .wmask0 (sel_q),
        .addr0 (adr_q[9:2]), .din0 (dat_q), .dout0 (mem_dout0),
        .clk1 (clk), .csb1 (!ld_run), .addr1 ({ld_tile, ld_k}), .dout1 (mem_dout1)
    );

    // convery belt. When CPU writes W_TILE = t, this block streams 16 weight rows from the SRAM into the array. one row per cycle w/0 the CPU doing 16 seperate writes.
    // ld_run: the belt is moving
    // ld_tile: which tile (t)
    // ld_k: which row (counts 0 -> 15 (then stops))
    // ld_v: "a row arrives this cycle". It's ld_run delayed by 1, b/c SRAM takes a cycle to answer
    // ld_kd: ld_k dalyed by 1 so the row number matches the data arriving
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ld_run <= 1'b0; ld_v <= 1'b0; ld_tile <= '0; ld_k <= '0; ld_kd <= '0;
        end else begin
            ld_v  <= ld_run;              // row requested now arrives next cycle
            ld_kd <= ld_k;
            if (wr && widx == 7'h0C) begin
                ld_run <= 1'b1; ld_tile <= dat_q[3:0]; ld_k <= '0;
            end else if (ld_run) begin
                if (ld_k == 4'hF) ld_run <= 1'b0;
                ld_k <= ld_k + 1'b1;
            end
        end
    end

    // ---- WMEM parity (radiation plan rank 1, docs/radiation.md)
    // One even-parity bit per SRAM byte, kept in flip-flops (the stock macro is exactly
    // 32 bits wide, no spare column). Catches every single-bit flip in the weights;
    // the 11 code alone only catches 2 of the 6 possible single flips.
    //   write: cycle 2 writes the SRAM and saves {row, mask, parity}; cycle 3 writes the
    //          parity flops from those (keeps the 256-row decode off adr_q's cycle)
    //   check: expected parity is fetched the same cycle the SRAM read is issued, and
    //          compared with the data when it comes back
    logic [3:0]  wpar [256];
    logic        wp_go;
    logic [7:0]  wp_row;
    logic [3:0]  wp_mask, wp_bits;
    logic [3:0]  pexp0, pexp1;            // expected parity: bus read / tile stream
    logic        wmem_bad;
    function automatic logic [3:0] bpar(input logic [31:0] w);
        return {^w[31:24], ^w[23:16], ^w[15:8], ^w[7:0]};
    endfunction
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int r = 0; r < 256; r++) wpar[r] <= '0;
            wp_go <= 1'b0; wp_row <= '0; wp_mask <= '0; wp_bits <= '0;
            pexp0 <= '0; pexp1 <= '0;
        end else begin
            wp_go <= req && mem_sel && we_q;
            if (req && mem_sel && we_q) begin
                wp_row <= adr_q[9:2]; wp_mask <= sel_q; wp_bits <= bpar(dat_q);
            end
            if (wp_go)
                for (int b = 0; b < 4; b++)
                    if (wp_mask[b]) wpar[wp_row][b] <= wp_bits[b];
            if (req && mem_sel && !we_q) pexp0 <= wpar[adr_q[9:2]];
            if (ld_run)                  pexp1 <= wpar[{ld_tile, ld_k}];
        end
    end
    // reset leaves both SRAM contents and parity undefined vs each other, so firmware
    // must write a tile before streaming it (it always does)
    assign wmem_bad = (mem_pend && (bpar(mem_dout0) != pexp0)) ||
                      (ld_v     && (bpar(mem_dout1) != pexp1));

    // front desk registers
    logic [31:0]        w_data; // one weight row, waiting to be loaded
    logic [8*N-1:0]     a_vec; // 16 int 8 inputs
    logic [31:0]        pp_cfg; // scale (m, shift) + relu. Triple-redundant (tmr_reg), issue #10
    logic [B_W*N-1:0]   bias; // bias setting
    logic [8*N-1:0]     q_res; // result waiting to be read
    logic [32*N-1:0]    wide_res; // result waiting to be read
    logic               res_ready; // result waiting to be read

    // one-cycle command pulses
    logic               w_load, rd_en, err_clear, cnt_clear;
    logic [3:0]         w_row, in_addr, rd_addr;
    logic               in_first;

    // Issue #6: BIAS write saved in cycle 2, done in cycle 3
    localparam int LW = $clog2(N);
    // one enable flop per BIAS half-word: bit 2n = lane n low, bit 2n+1 = lane n high.
    // One-hot, so cycle 3 needs no decoder at all (each flop drives its slot directly).
    logic [2*N-1:0]     bias_en;
    // even parity per BIAS half-word, stored on write (issue #10: detect, don't correct.
    // Firmware rewrites BIAS for every 16-output group, so reload is the fix.)
    logic [2*N-1:0]     bias_par;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            w_data <= '0; a_vec <= '0; bias <= '0; bias_par <= '0;
            {w_load, in_valid, rd_en, err_clear, cnt_clear} <= '0;
            {w_row, in_addr, rd_addr, in_first} <= '0;
            bias_pend <= 1'b0; bias_en <= '0;
        end else begin
            {w_load, in_valid, rd_en, err_clear, cnt_clear} <= '0;
            if (wr) begin
                case (widx)
                    7'h02: begin err_clear <= dat_q[0]; cnt_clear <= dat_q[1]; end
                    7'h03: w_data    <= dat_q;
                    7'h04: begin w_load <= 1'b1; w_row <= dat_q[3:0]; end
                    7'h05, 7'h06, 7'h07, 7'h08:
                           a_vec[32*(widx-7'h05) +: 32] <= dat_q;
                    7'h09: begin in_valid <= 1'b1; in_addr <= dat_q[3:0];
                                 in_first <= dat_q[4]; end
                    7'h0B: begin rd_en <= 1'b1; rd_addr <= dat_q[3:0]; end
                    default: ;
                endcase
            end
            // cycle 2: decode which half-word into one-hot enable flops
            if (bias_wr) begin
                bias_pend <= 1'b1;
                bias_en   <= (2*N)'(1) << widx[LW:0];
            end
            // cycle 3: write from the saved flops. dat_q is still valid because
            // capture is blocked while bias_pend is set.
            if (bias_pend) begin
                for (int l = 0; l < N; l++) begin
                    if (bias_en[2*l])     begin bias[B_W*l +: 32]      <= dat_q;       bias_par[2*l]     <= ^dat_q;       end
                    if (bias_en[2*l + 1]) begin bias[B_W*l + 32 +: 16] <= dat_q[15:0]; bias_par[2*l + 1] <= ^dat_q[15:0]; end
                end
                bias_pend <= 1'b0;
                bias_en   <= '0;
            end
        end
    end

    genvar gl;

    // ---- PP_CFG on TMR: 3 copies + majority vote; a single flip is outvoted and
    // repaired on the next clock, so cfg_err only pulses -> kept in a sticky flag.
    logic cfg_tmr_err;
    tmr_reg #(.W(32)) u_ppcfg (
        .clk, .rst_n,
        .we  (wr && widx == 7'h0A),
        .d   (dat_q),
        .q   (pp_cfg),
        .err (cfg_tmr_err)
    );

    // ---- BIAS parity check (one XOR tree per half-word, into a sticky flag)
    logic [2*N-1:0] bias_bad;
    generate
        for (gl = 0; gl < N; gl++) begin : g_bpar
            assign bias_bad[2*gl]     = (^bias[B_W*gl +: 32])      != bias_par[2*gl];
            assign bias_bad[2*gl + 1] = (^bias[B_W*gl + 32 +: 16]) != bias_par[2*gl + 1];
        end
    endgenerate

    logic tag_tmr_err;
    logic acc_perr, acc_err;
    logic cfg_err, bias_err, wmem_err, tag_err;    // sticky, cleared by CTRL[0]
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cfg_err <= 1'b0; bias_err <= 1'b0; wmem_err <= 1'b0; tag_err <= 1'b0; acc_err <= 1'b0;
        end else begin
            wmem_err <= wmem_bad | (wmem_err & !err_clear);
            tag_err  <= tag_tmr_err | (tag_err & !err_clear);
            acc_err  <= acc_perr | (acc_err & !err_clear);
            cfg_err  <= cfg_tmr_err | (cfg_err  & !err_clear);
            bias_err <= (|bias_bad) | (bias_err & !err_clear);
        end
    end

    // ---- the compute core (weight rows come from W_LOAD or from a W_TILE burst)
    logic w_err, err, ovf, pp_valid;
    assign err = w_err | cfg_err | bias_err | wmem_err | tag_err | acc_err;
    logic [32*N-1:0] wide_vec, rd_vec_unused; // wide_vec, 16xint32, the full precision answers
    logic [8*N-1:0]  q_vec; // 16 x int8, the final small answers after the shift, ReLU & Saturates. These are what the next layer uses
    logic            rd_valid_unused;

    core_ternary #(.N(N), .DEPTH(16), .B_W(B_W)) u_core (
        .clk, .rst_n,
        .w_load (w_load | ld_v),
        .w_row  (ld_v ? ld_kd : w_row),
        .w_data (ld_v ? mem_dout1[2*N-1:0] : w_data[2*N-1:0]),
        .in_valid, .in_first, .in_addr, .a_vec,
        .busy,
        .rd_en, .rd_addr, .rd_valid (rd_valid_unused), .rd_vec (rd_vec_unused),
        .pp_m (pp_cfg[15:0]), .pp_sh (pp_cfg[21:16]), .pp_relu (pp_cfg[24]),
        .pp_bias (bias),
        .pp_valid, .wide_vec, .q_vec,
        .err_clear, .err (w_err), .ovf, .tag_err (tag_tmr_err), .acc_perr
    );
    assign irq = err | ovf;

    // ---- upset counters: count each new event (a rising edge, so a level that
    // stays high, like an unrepaired parity error, counts once), saturate at 255
    logic [31:0] errcnt;
    logic [3:0]  ev, ev_q;
    assign ev = {tag_tmr_err, wmem_bad | (|bias_bad) | acc_perr, cfg_tmr_err, w_err};
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            errcnt <= '0; ev_q <= '0;
        end else begin
            ev_q <= ev;
            for (int i = 0; i < 4; i++)
                if (cnt_clear)                                errcnt[8*i +: 8] <= '0;
                else if (ev[i] && !ev_q[i] && ~&errcnt[8*i +: 8]) errcnt[8*i +: 8] <= errcnt[8*i +: 8] + 1'b1;
        end
    end

    // results are latched so the CPU can read them at its own pace
    // copy wide_vec and q_vec into q_res/wide_res when pp_valid. Copy them because the cpu is slow. It reads them over the bus later, one word at a time
    // (issue #6, r6: the old "clear on READ write, else load" if/else put the bus
    // address decode in front of the load enable of all 640 result flops.)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q_res <= '0; wide_res <= '0;
        end else if (pp_valid) begin
            q_res <= q_vec; wide_res <= wide_vec;
        end
    end
    // res_ready clears on rd_en, the registered READ pulse (one cycle after the READ
    // write). The earliest STATUS read after a READ samples 2 cycles later, so a poll
    // still never sees the old result as ready.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)        res_ready <= 1'b0;
        else if (rd_en)    res_ready <= 1'b0;
        else if (pp_valid) res_ready <= 1'b1;
    end

    // ---- read mux (issue #6: split over 2 cycles)
    // cycle 2: three smaller muxes, each from flops, into rd_misc / rd_wide / rd_bias
    // cycle 3: pick one of the three (rd_grp) into wbs_dat_o, with the ack
    // Before, one giant mux (~1,400 inputs) sat between adr_q and wbs_dat_o.
    logic [31:0] bias_lo  [N];            // per-lane views, so the muxes index cleanly
    logic [15:0] bias_hi16[N];
    logic [31:0] wide_w   [N];
    generate
        for (gl = 0; gl < N; gl++) begin : g_rdview
            assign bias_lo[gl]   = bias[B_W*gl +: 32];
            assign bias_hi16[gl] = bias[B_W*gl + 32 +: 16];
            assign wide_w[gl]    = wide_res[32*gl +: 32];
        end
    endgenerate

    logic [31:0] rd_misc, rd_wide, rd_bias;
    logic [1:0]  rd_grp;                  // widx[6:5]: 0 = 0x00-0x1F, 1 = WIDE, 2 = BIAS, 3 = none
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_misc <= '0; rd_wide <= '0; rd_bias <= '0; rd_grp <= '0;
        end else if (rd_reg) begin
            rd_grp <= widx[6:5];
            case (widx[4:0])
                5'h00: rd_misc <= ID;
                // busy also covers a PUSH accepted this cycle that hasn't entered the pipe yet
                5'h01: rd_misc <= {22'b0, acc_err, tag_err, wmem_err, bias_err, cfg_err, w_err, res_ready, ovf, err, busy | in_valid | loading};
                5'h03: rd_misc <= w_data;
                5'h05: rd_misc <= a_vec[31:0];
                5'h06: rd_misc <= a_vec[63:32];
                5'h07: rd_misc <= a_vec[95:64];
                5'h08: rd_misc <= a_vec[127:96];
                5'h0A: rd_misc <= pp_cfg;
                5'h0D: rd_misc <= errcnt;
                5'h10: rd_misc <= q_res[31:0];
                5'h11: rd_misc <= q_res[63:32];
                5'h12: rd_misc <= q_res[95:64];
                5'h13: rd_misc <= q_res[127:96];
                default: rd_misc <= '0;
            endcase
            rd_wide <= (widx[4:0] < N) ? wide_w[widx[LW-1:0]] : '0;
            rd_bias <= (widx[4:0] < 2 * N)
                     ? (widx[0] ? {16'b0, bias_hi16[widx[LW:1]]} : bias_lo[widx[LW:1]])
                     : '0;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) wbs_dat_o <= '0;
        else if (mem_pend) wbs_dat_o <= mem_dout0;
        else if (rd_pend) begin
            case (rd_grp)
                2'd0:    wbs_dat_o <= rd_misc;
                2'd1:    wbs_dat_o <= rd_wide;
                2'd2:    wbs_dat_o <= rd_bias;
                default: wbs_dat_o <= '0;
            endcase
        end
    end
endmodule

// Issue #6
// - To fix the slow corner sweep, we are going to make the bus check if it is going to do a BIAS write. Since BIAS writes are rare, it won't have to check that often. IN a worst case scenario, it will be ~80 microseconds and ~0.7 microseconds min. It's dependent on layers that the neural net has. The math is: 
// layer 1: 128 biases | 128 * 2 (2 writes because it is bigger than word) = 256
// layer 2: 10 biasess | 1 group of 16 lanes = 32 (some unused)
// total is 288 extra cycles = ~7 microseconds
// Mechanism vvvv
// cycle 1 | capture (adr_q, dat_q)
// cycle 2 | decode + save lane/half into flops + set bias_pend (NO ack)
// cycle 3 | write BIAS from those flip-flops + ack, clear bias_pend
// It's cheap to see if we have BIAS addresses (widx 0x40-0x5F). The expensive part was steering the data into one of 16 lanes across 768 flip-flops. Cycle 3 does that starting from flip-flops that already hold the answer 
//bus pins → capture FFs (cycle 1) → decoder → NEW pending FFs (cycle 2) → 768 BIAS FFs (cycle 3)


// Notes vvv
// - Word: just 32 bits. the width of the bus. like how a byte is 8 bits
// - In a neural net, it is y = (W*x + B) * scale. BIAS is + B. The hardware works out to y = (acc*m + B) >> shift
// - If you wanted to use ReLu and shift example for PP_CFG: 0x010C_0029. where relu is bit 24, shift is bits 21:16, and m is 15/0. (e.g., scaling by 0.01 where m = 41 and shift is 12 because 41 / (2^12))
// - Every bus access takes about 2 cycles
// --> cycle 1 = capture: save CPU's requests into flip-flops: adr_q, dat_q, we_q
// --> cycle 2 = execute: decode widx, write the register (or read it out), send ack
// --> WMEM takes ~3 cycles
// - WMEME holds 16 tiles (1 KB) of weights on chip at once. Bigger models mean that the CPU reloads it between chunks
// - Accumulator holds 16 rows, so up to 16 images (or rows) per batch
// - Whole model has to fit in Caravel's CPU 

// Questions
// - Does the CPU read each response from the systolic array one word at a time? so instead of how the systolic array operates where it's row to row like in a convery belt, the CPU just reads one at a tie
// - Answer: Yes. The bus is 32 bits wide. 
// - Does PE stand for Processing _something_? Does it mean one unit that goes through a computation?
// - Answer: Processing Element. Holds one terenary weight (-1, 0, or +1)
// - Does the systolic array have 1 row active while the other ones are idle until they are used? or is there like a chain of information alaways passing through with space in between them?
// - Answer: Inputs move sideways and partial sums move down. Inputs enter staggered (skewed) so the work spreads as a diagonal wave. At the start, only the corner PE is busy and the wave spreads until all 256 PE's are busy. Every PE works every tick
// Q (issue #6): 
// - Where did the 25ns come from initially? It is set in config.json. Which is 40 MHz. We don't pick our own clock, we run off of Caravel's CPU and bus. 25ns is the default for Careval projects.
// - Are BIAS per PE or per what? BIAS is per lane which means per output. The array has 16 columns and each column produces on answer, so 16 answers come out at a time.  In neural-net terms, each answer is one output neuron and ach neuron has it's own bias. It is 16 in total
// - Why 16 lanes x 2 words for BIAS? Each BIAS is 48 bits but each and a word is 32 bits wide. so it needs to get split up to fit 
// - what are the max/min amount of layers for this NPU? There is no limit because the firmware (the CPU) loops over layers. Inside each layer, it loves over 16x16 tiles. 
// - Can we make each BIAS be a smaller amount of bits and would this improve the entire NPU overal?
// - What does a BIAS value look like for this? An example bias could be pos/neg 400,212 something like that. It is stored pre-scaled by 2^sh. The chips add the bias to acc x m before the shift. 
// Why does layer 1 have so many biases? 
// How many layers can a typical model have? 2-5 are tiny, 15-30 are small, and 12-100 blocks are for transformers
// Is a tile just another name for a pixel in CNN?
// Why do we need to give hardware ACK?
// NPU firmware, C port of tb/npu_driver.py (SRAM weight-buffer path).
// See npu.h for the API and how it is tested.
#include "npu.h"

#ifdef NPU_HOST
static npu_wr_fn host_wr;
static npu_rd_fn host_rd;
void npu_host_bind(npu_wr_fn wr, npu_rd_fn rd) { host_wr = wr; host_rd = rd; }
static inline void     wr(uint32_t off, uint32_t v) { host_wr(off, v); }
static inline uint32_t rd(uint32_t off)             { return host_rd(off); }
#else
static inline void wr(uint32_t off, uint32_t v) {
    *(volatile uint32_t *)(NPU_BASE + off) = v;
}
static inline uint32_t rd(uint32_t off) {
    return *(volatile uint32_t *)(NPU_BASE + off);
}
#endif

int  npu_present(void)      { return rd(NPU_ID) == NPU_ID_VALUE; }
void npu_clear_errors(void) { wr(NPU_CTRL, 1); }

static void wait_idle(void) {
    while (rd(NPU_STATUS) & NPU_BUSY) { }
}

// Copy one 16-input slice of a vector into A_VEC0..3 and push it into acc row `row`.
static void push(const int8_t *a, int n_valid, int row, int first) {
    for (int i = 0; i < 4; i++) {
        uint32_t w = 0;
        for (int j = 0; j < 4; j++) {
            int idx = 4 * i + j;
            uint8_t v = idx < n_valid ? (uint8_t)a[idx] : 0;   // zero-pad the last tile
            w |= (uint32_t)v << (8 * j);
        }
        wr(NPU_A_VEC + 4 * i, w);
    }
    wr(NPU_PUSH, (uint32_t)(row & 0xF) | ((uint32_t)(first != 0) << 4));
}

static void configure(int16_t m, uint8_t sh, int relu, const int64_t *bias, int n0, int n_out) {
    wr(NPU_PP_CFG, (uint16_t)m | ((uint32_t)(sh & 0x3F) << 16) | ((uint32_t)(relu != 0) << 24));
    for (int n = 0; n < NPU_N; n++) {
        uint64_t b = n0 + n < n_out ? (uint64_t)bias[n0 + n] : 0;
        wr(NPU_BIAS + 8 * n,     (uint32_t)b);
        wr(NPU_BIAS + 8 * n + 4, (uint32_t)(b >> 32) & 0xFFFF);
    }
}

uint32_t npu_dense(const int8_t *x, int n_vec, int n_in,
                   const uint32_t *rows, int n_out,
                   int16_t m, uint8_t sh, const int64_t *bias, int relu,
                   int8_t *q_out, int32_t *wide_out) {
    const int n_tiles = (n_in + NPU_N - 1) / NPU_N;
    for (int n0 = 0; n0 < n_out; n0 += NPU_N) {
        const uint32_t *grp = rows + (n0 / NPU_N) * n_tiles * NPU_N;
        for (int c0 = 0; c0 < n_tiles; c0 += NPU_WMEM_TILES) {
            int nc = n_tiles - c0 < NPU_WMEM_TILES ? n_tiles - c0 : NPU_WMEM_TILES;
            // stage up to 16 tiles in the SRAM buffer
            for (int i = 0; i < nc * NPU_N; i++)
                wr(NPU_WMEM + 4 * i, grp[c0 * NPU_N + i]);
            // stream each tile into the array, then push every vector through it.
            // The bus itself stalls W_TILE / PUSH until it is safe: no polling.
            for (int s = 0; s < nc; s++) {
                int t = c0 + s, k0 = NPU_N * t;
                wr(NPU_W_TILE, (uint32_t)s);
                for (int v = 0; v < n_vec; v++)
                    push(x + v * n_in + k0, n_in - k0, v, t == 0);
            }
        }
        wait_idle();
        configure(m, sh, relu, bias, n0, n_out);
        int keep = n_out - n0 < NPU_N ? n_out - n0 : NPU_N;
        for (int v = 0; v < n_vec; v++) {
            wr(NPU_READ, (uint32_t)v);
            while (!(rd(NPU_STATUS) & NPU_READY)) { }
            if (wide_out)
                for (int n = 0; n < keep; n++)
                    wide_out[v * n_out + n0 + n] = (int32_t)rd(NPU_WIDE + 4 * n);
            if (q_out)
                for (int i = 0; i < 4 && 4 * i < keep; i++) {
                    uint32_t w = rd(NPU_Q + 4 * i);
                    for (int j = 0; j < 4 && 4 * i + j < keep; j++)
                        q_out[v * n_out + n0 + 4 * i + j] = (int8_t)(w >> (8 * j));
                }
        }
    }
    return rd(NPU_STATUS);
}

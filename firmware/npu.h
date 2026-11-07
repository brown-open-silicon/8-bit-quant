// NPU firmware for the Caravel management core (RISC-V), C port of
// tb/npu_driver.py. Register map: rtl/wb_npu.sv.
//
// On the chip, registers are plain memory-mapped loads/stores at NPU_BASE.
// For testing on the host, build with -DNPU_HOST: every access then goes
// through two callbacks, which tb/test_firmware.py wires to the RTL simulation,
// so this exact file is checked bit-for-bit against the hardware.
#ifndef NPU_H
#define NPU_H

#include <stdint.h>

#ifndef NPU_BASE
#define NPU_BASE 0x30000000u               // Caravel user-project Wishbone base
#endif

enum {
    NPU_ID = 0x000, NPU_STATUS = 0x004, NPU_CTRL = 0x008, NPU_W_DATA = 0x00C,
    NPU_W_LOAD = 0x010, NPU_A_VEC = 0x014, NPU_PUSH = 0x024, NPU_PP_CFG = 0x028,
    NPU_READ = 0x02C, NPU_W_TILE = 0x030, NPU_Q = 0x040, NPU_WIDE = 0x080,
    NPU_BIAS = 0x100, NPU_WMEM = 0x400,
};
enum { NPU_BUSY = 1, NPU_ERR = 2, NPU_OVF = 4, NPU_READY = 8 };
enum { NPU_N = 16, NPU_WMEM_TILES = 16, NPU_ID_VALUE = 0x4E505531 };

#ifdef NPU_HOST
typedef void     (*npu_wr_fn)(uint32_t off, uint32_t data);
typedef uint32_t (*npu_rd_fn)(uint32_t off);
void npu_host_bind(npu_wr_fn wr, npu_rd_fn rd);
#endif

// Weights are pre-packed rows, one uint32 per array row (16 lanes x 2-bit
// codes, lane n in bits [2n+1:2n]; 0 = 0, 1 = +1, 2 = -1). Layout:
//   rows[((g * n_tiles) + t) * 16 + k]   g = output group of 16 neurons,
//                                        t = K-tile (16 inputs), k = row
// n_tiles = ceil(n_in / 16), groups = ceil(n_out / 16). Tools: tb/test_firmware.py pack_rows().

// One dense layer for n_vec (<= 16) input vectors.
//   x:      n_vec x n_in int8 activations (row-major)
//   bias:   n_out int64 (only the low 48 bits are used)
//   q_out:  n_vec x n_out int8 results     (NULL to skip)
//   wide_out: n_vec x n_out int32 results  (NULL to skip; e.g. final logits)
// Returns STATUS at the end (check NPU_ERR / NPU_OVF).
uint32_t npu_dense(const int8_t *x, int n_vec, int n_in,
                   const uint32_t *rows, int n_out,
                   int16_t m, uint8_t sh, const int64_t *bias, int relu,
                   int8_t *q_out, int32_t *wide_out);

int  npu_present(void);                    // ID register matches
void npu_clear_errors(void);

#endif

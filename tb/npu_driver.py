"""Reference "firmware" for wb_npu: drives the NPU only through Wishbone
register reads/writes, exactly what the Caravel RISC-V core would do.
Port this to C for the real chip; the register map is in rtl/wb_npu.sv.
"""
from cocotb.triggers import FallingEdge

N = 16
ID, STATUS, CTRL, W_DATA, W_LOAD = 0x000, 0x004, 0x008, 0x00C, 0x010
A_VEC, PUSH, PP_CFG, READ = 0x014, 0x024, 0x028, 0x02C
Q, WIDE, BIAS = 0x040, 0x080, 0x100
BUSY, ERR, OVF, READY = 1, 2, 4, 8


def _s(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Npu:
    def __init__(self, dut):
        self.dut = dut
        self.n_access = 0

    # ---------------------------------------------------------- bus primitives
    async def _cycle(self, addr, we, data=0):
        d = self.dut
        d.wbs_adr_i.value = addr
        d.wbs_we_i.value = int(we)
        d.wbs_dat_i.value = data & 0xFFFFFFFF
        d.wbs_sel_i.value = 0xF
        d.wbs_stb_i.value = 1
        d.wbs_cyc_i.value = 1
        while True:
            await FallingEdge(d.wb_clk_i)
            if d.wbs_ack_o.value == 1:
                break
        out = int(d.wbs_dat_o.value)
        d.wbs_stb_i.value = 0
        d.wbs_cyc_i.value = 0
        d.wbs_we_i.value = 0
        await FallingEdge(d.wb_clk_i)          # bus idle cycle between transfers
        self.n_access += 1
        return out

    async def write(self, addr, data):
        await self._cycle(addr, True, data)

    async def read(self, addr):
        return await self._cycle(addr, False)

    # ---------------------------------------------------------- NPU operations
    async def load_weights(self, w_codes):
        """w_codes[k][n] = 2-bit code for W[k][n]."""
        for k in range(N):
            word = 0
            for n, c in enumerate(w_codes[k]):
                word |= (c & 3) << (2 * n)
            await self.write(W_DATA, word)
            await self.write(W_LOAD, k)

    async def push(self, a, row, first):
        for i in range(4):
            word = 0
            for j in range(4):
                word |= (a[4 * i + j] & 0xFF) << (8 * j)
            await self.write(A_VEC + 4 * i, word)
        await self.write(PUSH, (row & 0xF) | (int(first) << 4))

    async def wait_idle(self):
        while await self.read(STATUS) & BUSY:
            pass

    async def configure(self, m, sh, relu, bias):
        await self.write(PP_CFG, (m & 0xFFFF) | (sh << 16) | (int(relu) << 24))
        for n in range(N):
            b = bias[n] & ((1 << 48) - 1)
            await self.write(BIAS + 8 * n, b & 0xFFFFFFFF)
            await self.write(BIAS + 8 * n + 4, b >> 32)

    async def read_row(self, row, wide=False):
        await self.write(READ, row)
        while not (await self.read(STATUS) & READY):
            pass
        if wide:
            return [_s(await self.read(WIDE + 4 * n), 32) for n in range(N)]
        out = []
        for i in range(4):
            w = await self.read(Q + 4 * i)
            out += [_s(w >> (8 * j), 8) for j in range(4)]
        return out

    async def dense(self, x_rows, w_codes, m, sh, bias, relu, wide=False):
        """One full layer for up to 16 input vectors."""
        n_vec, n_in, n_out = len(x_rows), len(x_rows[0]), len(w_codes)
        out = [[] for _ in range(n_vec)]
        for n0 in range(0, n_out, N):
            for t, k0 in enumerate(range(0, n_in, N)):
                tile = [[w_codes[n0 + n][k0 + k] if n0 + n < n_out else 0 for n in range(N)]
                        for k in range(N)]
                await self.load_weights(tile)
                for i, x in enumerate(x_rows):
                    await self.push(x[k0:k0 + N], i, first=(t == 0))
                await self.wait_idle()
            b = [bias[n0 + n] if n0 + n < n_out else 0 for n in range(N)]
            await self.configure(m, sh, relu, b)
            keep = min(N, n_out - n0)
            for i in range(n_vec):
                out[i] += (await self.read_row(i, wide))[:keep]
        return out

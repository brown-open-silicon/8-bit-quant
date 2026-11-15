"""Memory diagram for docs/architecture.md: python3 docs/img/memory_map.py (needs matplotlib)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

plt.rcParams["font.family"] = ["Arial", "Helvetica", "DejaVu Sans"]
K, G = "#111111", "#666666"
SRAM, FF, OFF, REG = "#f6e3ef", "#e8f0fb", "#eeeeee", "#fbf3dc"

fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 192)
ax.set_ylim(0, 108)
ax.axis("off")


def box(x, y, w, h, title, detail="", fc="white", ls="-", tsize=13.5):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=K, lw=1.3, ls=ls))
    ty = y + h / 2 + (2.4 if detail else 0)
    ax.text(x + w / 2, ty, title, ha="center", va="center", fontsize=tsize, fontweight="bold", color=K)
    if detail:
        ax.text(x + w / 2, y + h / 2 - 2.6, detail, ha="center", va="center", fontsize=11, color=G,
                linespacing=1.35)


def arrow(a, b, label="", lpos=None, col=K, ha="left"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=14, lw=1.4, color=col))
    if label:
        x, y = lpos or ((a[0] + b[0]) / 2 + 1, (a[1] + b[1]) / 2)
        ax.text(x, y, label, fontsize=11, color=col, ha=ha, va="center")


ax.text(6, 102.5, "Ternary NPU: memory map", fontsize=27, fontweight="bold", color=K, va="center")
ax.text(6, 98, "What the CPU sees (left) and where the data lives during one layer (right)",
        fontsize=15, color=G, va="center")

# ---------------- left: address map ----------------
x0, w = 6, 52
ax.text(x0, 91, "Address map (byte offsets from 0x3000_0000)", fontsize=14, fontweight="bold", color=K)
regions = [  # (label, offsets, detail, height, color)
    ("Control + data registers", "0x000 - 0x0BC",
     "ID, STATUS, CTRL, W_DATA, W_LOAD,\nA_VEC0-3, PUSH, PP_CFG, READ, W_TILE,\nQ0-3 (int8 out), WIDE0-15 (int32 out)",
     18, REG),
    ("unused", "0x0C0 - 0x0FC", "", 4, "white"),
    ("BIAS", "0x100 - 0x17C", "16 lanes x 48 bit (2 words each)", 9, REG),
    ("unused", "0x180 - 0x3FC", "", 7, "white"),
    ("WMEM: weight SRAM", "0x400 - 0x7FC",
     "256 words x 32 bit = 1 KB\n= 16 tiles x 16 rows\n1 word = one array row (16 x 2-bit weights)", 22, SRAM),
]
y = 86
for name, offs, detail, h, fc in regions:
    y -= h
    ax.add_patch(Rectangle((x0, y), w, h, fc=fc, ec=K, lw=1.2, ls="--" if name == "unused" else "-"))
    ax.text(x0 + 1.5, y + h - 2.2, name, fontsize=13 if name != "unused" else 11,
            fontweight="bold" if name != "unused" else "normal", color=K if name != "unused" else G, va="center")
    ax.text(x0 + w - 1.5, y + h - 2.2, offs, fontsize=11, color=G, va="center", ha="right", family="monospace")
    if detail:
        ax.text(x0 + 1.5, y + h - 4.4, detail, fontsize=11, color=G, va="top", linespacing=1.4)
ax.text(x0, y - 2.5, "Every access is one 32-bit Wishbone read or write.\nAddresses above 0x7FF are not decoded.",
        fontsize=11, color=G, va="top", linespacing=1.4)

# ---------------- right: where data lives ----------------
ax.text(70, 91, "Where the data lives", fontsize=14, fontweight="bold", color=K)

# CPU side (outside our design)
box(70, 70, 28, 14, "SPI flash", "off-chip: firmware + all weights\n(MNIST: ~25 KB ternary)", fc=OFF)
box(70, 48, 28, 14, "Mgmt CPU (RISC-V)", "runs npu.c, keeps inputs\nand results between layers", fc=OFF)
arrow((84, 70), (84, 62.2), "CPU reads flash", lpos=(85.5, 66))

# Wishbone bus
ax.plot([104, 104], [17, 84], color=K, lw=3)
ax.text(103, 86, "Wishbone", fontsize=11, color=K, ha="center", va="bottom")
ax.add_patch(FancyArrowPatch((98.2, 55), (104, 55), arrowstyle="<|-|>", mutation_scale=12, lw=1.4, color=K))

# bus-visible storage
box(110, 70, 30, 14, "Weight SRAM (WMEM)", "1 KB = 16 tiles\nstock Sky130 macro", fc=SRAM)
box(110, 52, 30, 14, "A_VEC", "16 x int8 inputs\n(128 bit)", fc=REG)
box(110, 34, 30, 14, "PP_CFG + BIAS", "scale, shift, ReLU\n16 x 48-bit bias", fc=REG)
box(110, 16, 30, 14, "Q / WIDE", "16 x int8  or  16 x int32\nresults", fc=REG)
for y in (77, 59, 41):
    arrow((104, y), (109.8, y))
arrow((110, 23), (104.2, 23))

# inside the core
box(154, 52, 32, 32, "Systolic array", "PE weights:\n16 x 16 x 2 bit = 512 bit\nflip-flops, one tile at a time", fc=FF)
box(154, 25, 32, 16, "Accumulator", "16 rows x 16 lanes x int32\n= 8 Kbit flip-flops", fc=FF)
arrow((140.2, 77), (153.8, 77), "W_TILE", lpos=(141.5, 79))
arrow((140.2, 59), (153.8, 59), "PUSH", lpos=(141.5, 61))
arrow((170, 52), (170, 41.2), "16 x int16 / cycle", lpos=(171.5, 46.5))
ax.plot([170, 170, 147], [25, 20, 20], color=K, lw=1.4)
ax.add_patch(FancyArrowPatch((147, 20), (140.2, 20), arrowstyle="-|>", mutation_scale=14, lw=1.4, color=K))
ax.text(172, 21.5, "READ: requantize", fontsize=11, color=K, va="center")
ax.add_patch(FancyArrowPatch((147, 41), (147, 20.5), arrowstyle="-", lw=1.2, ls="--", color=G))
ax.plot([140, 147], [41, 41], color=G, lw=1.2, ls="--")
ax.text(148, 31, "uses\nscale\n+ bias", fontsize=10, color=G, va="center")

# legend
lx, ly = 6, 14
for i, (fc, name) in enumerate([(SRAM, "SRAM macro (dense; 1 read/write + 1 read port)"),
                                (FF, "flip-flops inside the core (fast, ~2x area per bit)"),
                                (REG, "bus registers (flip-flops the CPU reads/writes)"),
                                (OFF, "outside our design")]):
    yy = ly - i * 2.6
    ax.add_patch(Rectangle((lx, yy - 0.9), 3, 1.8, fc=fc, ec=K, lw=1))
    ax.text(lx + 4.5, yy, name, fontsize=10.5, color=K, va="center")

ax.text(70, 4, "Fig. 2  Sizes are for the current design (16 x 16 array, 1 KB weight buffer).", fontsize=11, color=G)
fig.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_map.png"), facecolor="white")
print("ok")

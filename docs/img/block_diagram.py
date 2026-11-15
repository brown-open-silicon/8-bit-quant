"""Block diagram for the README: python3 docs/img/block_diagram.py (needs matplotlib)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
import os
from matplotlib import font_manager
plt.rcParams["font.family"] = ["Arial", "Helvetica", "DejaVu Sans"]
PIX = None                                             # headings use the same font

fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 192); ax.set_ylim(0, 108); ax.axis("off")
fig.patch.set_facecolor("white")
K, G, B = "#111111", "#666666", "#1f5fbf"     # ink, gray, one accent for the datapath

def block(x, y, w, h, name, detail="", fc="#f4f4f4", ec=K, ls="-", bold=True, size=16.2):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=ec, lw=1.4, ls=ls))
    ty = y + h / 2 + (1.9 if detail else 0)
    ax.text(x + w / 2, ty, name, ha="center", va="center", fontsize=size,
            fontweight="bold" if bold else "normal", family=None, color=K)
    if detail:
        ax.text(x + w / 2, y + h / 2 - 2.5, detail, ha="center", va="center", fontsize=12.4, color=G)

def wire(pts, col=K, lw=1.4, label=None, lpos=None, ha="center", head=True, ls="-"):
    for (x1, y1), (x2, y2) in zip(pts[:-2], pts[1:-1]):
        ax.plot([x1, x2], [y1, y2], color=col, lw=lw, ls=ls, solid_capstyle="butt")
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>" if head else "-",
                                 mutation_scale=13, color=col, lw=lw, ls=ls, shrinkA=0, shrinkB=0))
    if label:
        ax.text(*lpos, label, fontsize=11.9, color=col, ha=ha, va="center",
                bbox=dict(fc="white", ec="none", pad=0.6))

# title, plain
ax.text(6, 102.5, "Ternary NPU for Sky130 (Caravel): block diagram", fontsize=27.5, fontweight="bold", color=K, va="center")
ax.text(6, 98, "Brown Open Silicon, Compute Core", fontsize=16.2, color=G, va="center")

# Caravel boundary
ax.add_patch(Rectangle((22, 10), 128, 82, fc="none", ec=G, lw=1.2, ls=(0, (6, 3))))
ax.text(24, 11.5, "Caravel (Sky130A)", fontsize=14.4, color=G, style="normal")

# off-chip flash
block(4, 62, 14, 14, "SPI flash", "off-chip,\nweights", fc="white", size=15.0)

# management SoC
block(26, 56, 22, 26, "Mgmt SoC", "RISC-V\nruns firmware/npu.c", size=16.2)
wire([(18, 69), (25.9, 69)], label="SPI", lpos=(20, 71.5))

# Wishbone bus as a vertical line
ax.plot([54, 54], [16, 84], color=K, lw=3)
ax.text(52.5, 20, "Wishbone, 32 bit\nbase 0x3000_0000", fontsize=12.4, color=K, ha="right", va="center")
wire([(48, 72), (54, 72)], head=False)

# user project area
ax.add_patch(Rectangle((60, 14), 86, 74, fc="none", ec=K, lw=1.4))
ax.text(62, 85, "user project area: wb_npu", fontsize=15.0, fontweight="bold", color=K)

block(64, 66, 22, 14, "Bus regs + ctrl", "CTRL, STATUS, PP_CFG,\nBIAS, A_VEC, results")
wire([(54, 73), (63.9, 73)])
block(92, 66, 24, 14, "Weight SRAM", "256 x 32 b, 1 KB\nsky130_sram macro")
wire([(86, 76), (91.9, 76)], label="WMEM", lpos=(89, 78.3))
block(122, 66, 20, 14, "Error detect", "weight code 11\n= bit flip")

block(78, 40, 46, 18, "Systolic array 16 x 16", "256 ternary PEs (w in {-1, 0, +1})\nweight-stationary, add / skip / subtract", fc="#eaf1fb", ec=B)
wire([(104, 65.9), (104, 58.1)], col=B, label="1 row/cycle, 16 x 2 b", lpos=(105.5, 62), ha="left")
wire([(75, 65.9), (75, 49), (77.9, 49)], col=B, label="16 x int8", lpos=(76.5, 55), ha="left")
wire([(124.1, 50), (132, 50), (132, 65.9)], col="#b03030", label="flag", lpos=(133.5, 56), ha="left")

block(66, 18, 30, 14, "Accumulator", "16 rows x 16 lanes x int32\nsums K-tiles", fc="#eaf1fb", ec=B)
block(106, 18, 34, 14, "Requant + ReLU", "y = (acc*m + b) >> sh\nint8 or int32 out", fc="#eaf1fb", ec=B)
wire([(90, 39.9), (90, 32.1)], col=B, label="16 x int16", lpos=(91.5, 36), ha="left")
wire([(96, 25), (105.9, 25)], col=B)
wire([(123, 17.9), (123, 15.8), (62, 15.8), (62, 70), (63.9, 70)], col=G, label="results", lpos=(100, 15.8))

# irq back to the CPU
wire([(142, 73), (147.5, 73), (147.5, 92.5), (37, 92.5), (37, 82.1)], col="#b03030",
     label="irq (bit flip / overflow)", lpos=(92, 92.5))

# planned modules, dashed
block(154, 64, 32, 16, "PVT sensor", "process / voltage / temp,\nTID monitor", fc="white", ls="--")
block(154, 42, 32, 16, "Custom SRAM", "same ports as stock SRAM,\n256 x 32", fc="white", ls="--")
ax.text(154, 83, "Planned team modules", fontsize=14.4, color=G, style="normal")
wire([(153.9, 48), (152, 48), (152, 83.5), (104, 83.5), (104, 80.1)], col=G, ls="--", label="drop-in replacement", lpos=(128, 83.5))

# spec table
rows = [("Process", "SkyWater Sky130A"), ("Area, with SRAM", "1.79 x 1.81 mm"),
        ("Clock", "40 MHz (typical corner)"), ("Weights", "ternary, 2 bit"),
        ("Model", "MNIST 784-128-10, 96.7%"), ("Checked", "bit-exact vs Python")]
x0, y0 = 154, 34
ax.text(x0, y0 + 1.5, "Summary", fontsize=15.0, fontweight="bold", color=K)
for i, (k, v) in enumerate(rows):
    y = y0 - 3.4 - i * 3.6
    ax.plot([x0, 188], [y - 1.8, y - 1.8], color="#dddddd", lw=0.8)
    ax.text(x0, y, k, fontsize=12.4, color=G, va="center")
    ax.text(188, y, v, fontsize=12.4, color=K, va="center", ha="right")

ax.text(6, 4, "Fig. 1  Datapath in blue. Dashed blocks are planned.", fontsize=12.4, color=G)
fig.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)), "block_diagram.png"), facecolor="white")
print("ok")

"""Color a placed DEF by which RTL block each cell belongs to, and label it.

The flattened netlist gives cells anonymous names (_123285_), but nets keep
their hierarchical names (u_array.g_row[3]..., u_acc.mem..., u_pp...). Each
cell is assigned to the block whose named nets it touches most.

  uv run --with matplotlib --with pillow python pnr/floorplan_map.py <def> <layout.png> <out.png>
"""
import re
import sys
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

DEF, LAYOUT_PNG, OUT = sys.argv[1:4]

BLOCKS = [  # (key, label, color, net-name regex)
    ("pe",     "Systolic array: 256 PEs (16×16)",      "#4f8ef7", r"^(u_core\.)?u_array\.(g_row|a_h|p_v|bad)"),
    ("skew",   "Array input skew / output deskew",     "#9b6bf2", r"^(u_core\.)?u_array\.(g_skew|g_deskew|vsr|err)"),
    ("acc",    "Accumulator (16×16 × int32, flops)",   "#f2a93b", r"^(u_core\.)?(u_acc|arr_c|rd_vec)"),
    ("pp",     "Post-processing (scale, ReLU)",        "#3fc27a", r"^(u_core\.)?(u_pp|pp_|wide_vec|q_vec)"),
    ("ctrl",   "Control (tag delay line, valid)",      "#ef5b6b", r"^(u_core\.)?(tag_sr|inflight|busy|in_addr|in_first)"),
    ("wb",     "Wishbone registers + tile loader",     "#e8d44d", r"^(wbs_|w_data|a_vec|pp_cfg|bias|q_res|wide_res|res_ready|ld_|mem_|widx|req|stall)"),
]
OTHER = ("other", "Clock tree / IO buffers / glue", "#7d8590")

# ---- parse DEF
txt = open(DEF).read()
units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
die = [int(v) / units for v in re.search(r"DIEAREA \( (\-?\d+) (\-?\d+) \) \( (\-?\d+) (\-?\d+) \)", txt).groups()]

comps = {}
srams = []                                  # hard macros: (x, y) lower-left in um
sec = txt[txt.index("\nCOMPONENTS"):txt.index("END COMPONENTS")]
for m in re.finditer(r"- (\S+) (\S+)[^;]*?(?:PLACED|FIXED) \( (\-?\d+) (\-?\d+) \)", sec):
    name, macro, x, y = m.groups()
    if "sram" in macro:
        srams.append((int(x) / units, int(y) / units))
        continue
    if "TAPCELL" in name or "FILLER" in name or "decap" in macro or "fill" in macro:
        continue
    comps[name] = (int(x) / units, int(y) / units)

votes = defaultdict(Counter)
sec = txt[txt.index("\nNETS"):txt.index("END NETS")]
pats = [(k, re.compile(rx)) for k, _, _, rx in BLOCKS]
nets = []                                   # member lists of small nets, for propagation
for m in re.finditer(r"- (\S+)(.*?);", sec, re.S):
    net = m.group(1).replace("\\", "")
    members = [c for c in re.findall(r"\( (\S+) \S+ \)", m.group(2)) if c in comps]
    if 1 < len(members) <= 40:              # skip clock/reset/huge-fanout nets
        nets.append(members)
    key = next((k for k, p in pats if p.search(net)), None)
    if key is not None:
        for c in members:
            votes[c][key] += 1

assign = {c: votes[c].most_common(1)[0][0] for c in comps if votes[c]}
# clock tree and pad buffers stay "other"; everything else inherits its neighbors' block
fixed_other = {c for c in comps if re.match(r"(clkbuf|clkload|input|output|clone)", c)}
nbrs = defaultdict(list)
for members in nets:
    for c in members:
        nbrs[c].extend(m for m in members if m != c)
for _ in range(30):
    new = {}
    for c in comps:
        if c in assign or c in fixed_other:
            continue
        v = Counter(assign[n] for n in nbrs[c] if n in assign)
        if v:
            new[c] = v.most_common(1)[0][0]
    if not new:
        break
    assign.update(new)
assign = {c: assign.get(c, "other") for c in comps}
info = {k: (lbl, col) for k, lbl, col, _ in BLOCKS}
info["other"] = OTHER[1:]
counts = Counter(assign.values())
total = sum(counts.values())

# ---- figure: real layout (left) + labeled block map (right)
fig, (axL, axR) = plt.subplots(1, 2, figsize=(19.2, 10.8), dpi=100,
                               gridspec_kw={"width_ratios": [1, 1.35]})
fig.patch.set_facecolor("white")
import os
fig.suptitle(os.environ.get("TITLE", "Ternary NPU core on Sky130: where everything is"), fontsize=26, fontweight="bold", y=0.97)

axL.imshow(Image.open(LAYOUT_PNG), extent=(die[0], die[2], die[1], die[3]))
axL.set_title(os.environ.get("LEFT", "Actual layout (placed cells)"), fontsize=17)
axR.set_facecolor("#111418")
for key in ["other", "wb", "ctrl", "skew", "pp", "acc", "pe"]:
    pts = np.array([comps[c] for c in comps if assign[c] == key])
    if len(pts):
        axR.scatter(pts[:, 0], pts[:, 1], s=0.35, c=info[key][1], linewidths=0, rasterized=True)
axR.set_title("Same chip, colored by block", fontsize=17)
for ax in (axL, axR):
    ax.set_xlim(die[0], die[2]); ax.set_ylim(die[1], die[3]); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])

from matplotlib.patches import Rectangle
for (x, y) in srams:                        # 479.78 x 397.5 um macro
    for ax in (axL, axR):
        ax.add_patch(Rectangle((x, y), 479.78, 397.5, fill=(ax is axR), fc="#e05bd0", ec="#e05bd0", lw=3))
    axR.text(x + 240, y + 199, "WEIGHT SRAM\n1 KB macro", fontsize=15, fontweight="bold",
             ha="center", va="center", color="black",
             bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#e05bd0", lw=3, alpha=0.92))

# ---- labels placed on each big block; legend lists everything
w, h = die[2] - die[0], die[3] - die[1]
ON_CHIP = {"pe": "SYSTOLIC ARRAY\n16×16 PEs", "acc": "ACCUMULATOR", "pp": "POST-\nPROCESSING",
           "skew": "skew /\ndeskew"}
for key, text in ON_CHIP.items():
    pts = np.array([comps[c] for c in comps if assign[c] == key])
    if len(pts) < 50:
        continue
    H, xe, ye = np.histogram2d(pts[:, 0], pts[:, 1], bins=8, range=[[die[0], die[2]], [die[1], die[3]]])
    i, j = np.unravel_index(H.argmax(), H.shape)
    cx, cy = (xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2
    if key == "skew":   # skew registers hug the array edge; point at them instead of covering them
        axR.annotate(text, xy=(cx, cy), xytext=(cx - 0.18 * w, cy + 0.2 * h), fontsize=13,
                     fontweight="bold", ha="center", color="black",
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=info[key][1], lw=3, alpha=0.95),
                     arrowprops=dict(arrowstyle="-|>", color="white", lw=2.5))
        continue
    axR.text(cx, cy, text, fontsize=17, fontweight="bold", ha="center", va="center", color="black",
             bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=info[key][1], lw=4, alpha=0.92))

from matplotlib.lines import Line2D
handles = [Line2D([], [], ls="", marker="s", ms=18, mfc=info[k][1], mec="none",
                  label=f"{info[k][0]}\n{counts[k]:,} cells ({100 * counts[k] / total:.0f}%)")
           for k in ["pe", "acc", "pp", "skew", "ctrl", "wb", "other"] if counts[k]]
if srams:
    handles.insert(3, Line2D([], [], ls="", marker="s", ms=18, mfc="#e05bd0", mec="none",
                             label="Weight SRAM (stock Sky130 1 KB macro)\n0.19 mm²"))
fig.legend(handles=handles, loc="center left", bbox_to_anchor=(0.705, 0.5), fontsize=13,
           frameon=False, labelspacing=1.4, handletextpad=0.8)
axR.text(0.5, -0.04, f"{w / 1000:.2f} × {h / 1000:.2f} mm  ·  {total:,} cells  ·  " + os.environ.get("NOTE", "placed, wiring not routed yet"),
         transform=axR.transAxes, ha="center", fontsize=13, color="#444")
fig.subplots_adjust(left=0.02, right=0.70, top=0.88, bottom=0.07, wspace=0.05)
fig.savefig(OUT)
print("wrote", OUT)
for key, n in counts.most_common():
    print(f"  {info[key][0]:42s} {n:7,d}  {100 * n / total:4.1f}%")

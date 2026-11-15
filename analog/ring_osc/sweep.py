"""PVT sweep of the ring oscillator: process corner x supply x temperature.

    scripts/eda.sh "python3 analog/ring_osc/sweep.py"     # ~1 min

1. xschem netlists ring_osc.sch
2. one ngspice deck per process corner (tt, ss, ff) loops over VCC and temperature
3. writes sim/pvt.csv, sim/tran.csv, and the plots in docs/img/
"""
import csv
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE / "sim"
IMG = HERE.parents[1] / "docs" / "img"
CORNERS = ["tt", "ss", "ff"]
VCCS = [1.6, 1.8, 1.95]
TEMPS = [-40, 0, 27, 85, 125]


def netlist():
    SIM.mkdir(exist_ok=True)
    subprocess.run(["xschem", "-q", "-x", "-r", "-n", "-s", "-o", str(SIM), str(HERE / "ring_osc.sch")],
                   check=True, capture_output=True)
    return (SIM / "ring_osc.spice").read_text()


def deck(base, corner):
    """Swap the schematic's .control block for a sweep loop, and the model corner."""
    head, rest = base.split(".control", 1)
    tail = rest.split(".endc", 1)[1].replace("sky130.lib.spice tt", f"sky130.lib.spice {corner}")
    out = f"{corner}.txt"
    lines = [".control", f"  shell rm -f {out}"]
    for t in TEMPS:
        for v in VCCS:                       # temp must be set after reset, or it is lost
            lines += [f"  alterparam VCC={v}", "  reset", f"  option temp={t}", "  tran 2p 8n",
                      f'  meas tran tper TRIG v("z[0]") VAL={v / 2} RISE=3 TARG v("z[0]") VAL={v / 2} RISE=5',
                      f'  echo "{t} {v} $&tper" >> {out}']
    if corner == "tt":                       # one waveform for the picture, nominal 1.8 V 27 C
        lines += ["  alterparam VCC=1.8", "  reset", "  option temp=27", "  tran 2p 3n",
                  '  wrdata tran.txt v("z[0]") v("z[3]")']
    lines.append(".endc")
    path = SIM / f"{corner}.spice"
    path.write_text(head + "\n".join(lines) + tail)
    return path


def run(path):
    subprocess.run(["ngspice", "-b", path.name], cwd=SIM, check=True, capture_output=True)


def main():
    base = netlist()
    with ThreadPoolExecutor(len(CORNERS)) as ex:
        list(ex.map(run, [deck(base, c) for c in CORNERS]))
    rows = []
    for c in CORNERS:
        for line in (SIM / f"{c}.txt").read_text().split("\n"):
            parts = line.split()
            if len(parts) == 3:              # a failed measurement leaves the period blank
                t, v, per = parts
                rows.append({"corner": c, "vcc": float(v), "temp": float(t),
                             "freq_ghz": 1e-9 / (float(per) / 2)})   # meas spans 2 periods
    with open(SIM / "pvt.csv", "w", newline="") as f:
        w = csv.DictWriter(f, rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    plot(rows)
    for r in rows:
        print(f"{r['corner']} {r['vcc']:.2f} V {r['temp']:5.0f} C  {r['freq_ghz']:.3f} GHz")


def plot(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans Mono", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    colors = {"ff": "#1f6fb2", "tt": "#222222", "ss": "#c0392b"}
    styles = {1.6: ":", 1.8: "-", 1.95: "--"}

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for c in ["ff", "tt", "ss"]:
        for v in VCCS:
            pts = [(r["temp"], r["freq_ghz"]) for r in rows if r["corner"] == c and r["vcc"] == v]
            ax.plot(*zip(*pts), styles[v], color=colors[c], marker="o", ms=3,
                    label=f"{c}  {v:.2f} V")
    ax.set_xlabel("temperature (C)")
    ax.set_ylabel("frequency (GHz)")
    ax.set_title("7-stage ring oscillator, Sky130, ngspice", loc="left", fontsize=11)
    ax.legend(ncol=3, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.15))
    ax.grid(alpha=0.25)
    fig.text(0.01, 0.01, "process corner = color, supply = line style", fontsize=8, color="#666")
    fig.tight_layout()
    fig.savefig(IMG / "ring_osc_pvt.png", dpi=150)

    t, a, b = [], [], []
    for line in (SIM / "tran.txt").read_text().split("\n"):
        p = line.split()
        if len(p) == 4:
            t.append(float(p[0]) * 1e9); a.append(float(p[1])); b.append(float(p[3]))
    fig, ax = plt.subplots(figsize=(7.5, 3))
    ax.plot(t, a, color="#1f6fb2", lw=1.2, label="Z[0]")
    ax.plot(t, b, color="#c0392b", lw=1.2, label="Z[3]")
    ax.set_xlabel("time (ns)")
    ax.set_ylabel("V")
    ax.set_title("ring oscillator output, tt 1.8 V 27 C (supply ramps on at 0.5 ns)", loc="left", fontsize=11)
    ax.legend(frameon=False, loc="lower right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(IMG / "ring_osc_tran.png", dpi=150)


if __name__ == "__main__":
    main()

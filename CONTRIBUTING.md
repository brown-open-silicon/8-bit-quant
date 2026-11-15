# Contributing

TLDR: install Docker and uv, run `make sim`, pick a `good first issue`, open a PR.

## 1. Understand it (15 min)

- Read the [README](README.md) and look at the block diagram.
- Skim [docs/architecture.md](docs/architecture.md). Look up unknown words in [docs/glossary.md](docs/glossary.md).

## 2. Set up (about 1 hour, mostly downloading)

| Need | Get it |
|---|---|
| git | macOS: `xcode-select --install`. Windows: use WSL2 (Ubuntu) and run everything inside it |
| Docker | Docker Desktop. Give it at least 8 GB of RAM (16 GB for place and route) |
| uv (Python) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

```bash
git clone https://github.com/brown-open-silicon/8-bit-quant && cd 8-bit-quant
docker pull hpretl/iic-osic-tools:chipathon26     # 10+ GB: all EDA tools + PDKs
make quant                                        # Python: train + quantize (~10 s)
make sim                                          # RTL tests (a few minutes)
```

Done when `make sim` ends with every test `PASS`. If it doesn't, see [Troubleshooting](#troubleshooting), then open an issue with the output.

**Windows:** do everything inside WSL2 (Ubuntu), never PowerShell or `C:\`.

1. In PowerShell (admin): `wsl --install`, reboot, open "Ubuntu".
2. Docker Desktop: Settings > General > "Use the WSL 2 based engine", and Settings > Resources > WSL integration > turn on Ubuntu.
3. In Ubuntu: `sudo apt update && sudo apt install -y git make curl`, then the commands above.
4. Clone into your Linux home (`cd ~`), not `/mnt/c/...`. Clones on the Windows side are slow and break the scripts (line endings).
5. Edit with VS Code: run `code .` from Ubuntu inside the repo. Windows Explorer can see the files at `\\wsl$\Ubuntu\home\<you>`.

## 3. See the chip (30 min, optional)

The GUI tools (KLayout, xschem) run in a desktop inside the container, viewed in your browser.
Your repo folder is **mounted** into it: the same files, not a copy. Edits on either side show up on the other.

First time only. Run it **from the repo folder** (macOS, Linux, WSL):

```bash
docker run -d --name npu_vnc -p 8080:80 -v "$PWD":/foss/designs/8-bit-quant hpretl/iic-osic-tools:chipathon26
```

PowerShell, only if you can't use WSL: replace `"$PWD"` with `"${PWD}"`.

Then open http://localhost:8080 (password `abc123`) and in its terminal:

```bash
cd /foss/designs/8-bit-quant && sak-pdk sky130A        # sak-pdk every new terminal, or symbols go missing
xschem analog/ring_osc/ring_osc.sch                    # schematic
klayout pnr/wb_npu/runs/<run>/final/gds/wb_npu.gds     # layout (needs a finished layout run)
```

| Later | Command |
|---|---|
| stop when done | `docker stop npu_vnc` |
| come back | `docker start npu_vnc`, then open http://localhost:8080 |
| start over (e.g. mounted the wrong folder) | `docker rm -f npu_vnc`, then the `docker run` above again |
| check what is mounted | `docker inspect npu_vnc --format '{{range .Mounts}}{{.Source}}{{end}}'` |

No layout run yet? See the pictures in [docs/architecture.md](docs/architecture.md#physical-design).

## 4. Pick a task

Filter issues by label:

| Label | Area |
|---|---|
| `good first issue` | small, safe, good for learning |
| `rtl` | SystemVerilog design |
| `verification` | cocotb tests |
| `layout` | LibreLane, timing, DRC/LVS |
| `ml` | model, quantization, fault injection (Python) |
| `firmware` | C driver for the RISC-V CPU |
| `sensor` | PVT / radiation sensor |
| `sram` | custom SRAM |
| `integration` | Caravel wrapper, precheck |
| `documentation` | docs, diagrams |
| `blocked` | waiting on something else |

Comment on the issue to claim it, so two people don't do the same work.

## 5. Submit work

```bash
git checkout -b <your-name>/<short-topic>
# make changes
make sim                                   # must still pass
git push -u origin <your-name>/<short-topic>
```

Then open a pull request. Rules:

- No direct pushes to `main`. Every change goes through a PR with one review.
- Changes in `rtl/` need a test in `tb/` and a review from the RTL owner.
- Don't change a register address or port listed in [docs/interfaces.md](docs/interfaces.md) without updating the doc in the same PR.
- Don't commit build outputs (`build/`, `pnr/*/runs/`), large binaries, or anyone's personal info. This repo is public.

## Useful commands

| Command | Does |
|---|---|
| `scripts/eda.sh "python3 tb/run.py wb_npu"` | run one test group (names in `tb/run.py`) |
| `PDK=gf180mcuD make area` | synthesize for GF180 instead of Sky130 |
| `scripts/eda.sh 'librelane --manual-pdk --pdk-root $PDK_ROOT --pdk sky130A --run-tag mine pnr/wb_npu/config.json'` | full place and route (~1-2 h, 8+ GB RAM) |

## Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running. Start it and wait for "Engine running". On WSL, also turn on WSL integration (above) |
| `permission denied ... docker.sock` (Linux) | `sudo usermod -aG docker $USER`, then log out and back in |
| `$'\r': command not found` or `bad interpreter` | Windows line endings. Run `git config --global core.autocrlf input`, delete the repo, and clone it again inside WSL |
| `make: command not found` | macOS: `xcode-select --install`. WSL/Linux: `sudo apt install -y make` |
| `uv: command not found` right after installing | Close and reopen the terminal |
| `make sim` dies with `Killed` or exit code 137 | Out of memory. Docker Desktop > Settings > Resources: 8 GB or more |
| `no space left on device` | The image is 10+ GB. Free disk space, or `docker image prune` to drop old images |
| `invoke the docker CLI from the docker-desktop WSL2 distribution` | You opened Docker's internal distro (prompt `docker-desktop:~#`). `exit`, then open **Ubuntu** from the Start menu (`wsl --install -d Ubuntu` if missing) and turn on its WSL integration in Docker Desktop |
| `"$PWD" includes invalid characters for a local volume name` | You're in Command Prompt, or the quotes got pasted as curly `“ ”`. Use Ubuntu (WSL), or in cmd use `"%cd%"`, in PowerShell `"${PWD}"`. Retype the quotes by hand |
| `Conflict. The container name "/npu_vnc" is already in use` | It already exists: `docker start npu_vnc`. To recreate it: `docker rm -f npu_vnc` |
| `port is already allocated` | Something else uses 8080. Use `-p 8081:80` and open http://localhost:8081 |
| Browser shows a blank or black page | Wait 20 s and refresh. Still blank: `docker logs npu_vnc` |
| `/foss/designs/8-bit-quant` is empty in the VNC | You ran `docker run` outside the repo folder. Start over (`docker rm -f npu_vnc`) from the repo folder |
| xschem shows missing symbols (red boxes) | Run `sak-pdk sky130A` in that terminal, then reopen xschem |
| Very slow on Windows | The repo is under `/mnt/c/`. Clone it into `~` inside WSL instead |

Still stuck? Open an issue with the Bug template and paste the full command and output.

## Where to ask

Ask in the team chat, or open an issue with the `question` label. No question is too basic.

## Other

Make a new folder when it's a new kind of thing. If something already exists for it then work on that folder.

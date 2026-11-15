# Setup

TLDR: install Docker Desktop, clone the repo, pull the tools image, run the tests.

```bash
git clone https://github.com/brown-open-silicon/8-bit-quant && cd 8-bit-quant
docker pull hpretl/iic-osic-tools:chipathon26     # ~5 GB download: all EDA tools + PDKs
make sim                                          # RTL tests (a few minutes)
```

Done when `make sim` ends with `FAIL=0` in every summary and no errors. Stuck? See [Troubleshooting](#troubleshooting).

Contents:

1. [What you are installing and why](#1-what-you-are-installing-and-why)
2. [Before you start](#2-before-you-start)
3. Install for your OS: [macOS](#3a-macos) | [Windows](#3b-windows) | [Linux](#3c-linux)
4. [Get the repo and the tools image](#4-get-the-repo-and-the-tools-image)
5. [Run the tests](#5-run-the-tests)
6. [Open the VNC desktop (xschem, KLayout)](#6-open-the-vnc-desktop-xschem-klayout)
7. [Choose the PDK (Sky130)](#7-choose-the-pdk-sky130)
8. [Editing files](#8-editing-files)
9. [Staying up to date](#9-staying-up-to-date)
10. [Other commands](#10-other-commands)
11. [Cleaning up](#11-cleaning-up)
12. [Troubleshooting](#troubleshooting)

---

## 1. What you are installing and why

| Piece | What it is | Why we need it |
|---|---|---|
| **git** | version control | get the repo, make branches, open PRs |
| **Docker Desktop** | runs "containers": small Linux computers inside your computer | all chip tools run in one container, so everyone has the exact same versions on any OS |
| **`hpretl/iic-osic-tools:chipathon26`** | the container image: Icarus Verilog, cocotb, Yosys, OpenROAD, LibreLane, Magic, KLayout, xschem, ngspice, and the Sky130 + GF180 PDKs | the whole toolchain in one download. No installing 15 tools by hand |
| **make** | runs short named commands from the `Makefile` | `make sim` is shorter than the full Docker command |
| **uv** (optional) | fast Python package manager | only for `make quant` (training the model). Not needed for tests or layout |

How it fits together:

```
your laptop                               Docker container (Linux)
-----------                               ------------------------
repo folder  <==== mounted (same files) ====>  /work  or  /foss/designs/8-bit-quant
editor (VS Code)                          iverilog, cocotb, yosys, openroad, xschem, klayout, ngspice
terminal: make sim  ------- runs ------->  python3 tb/run.py
browser: localhost:8080 <-- VNC desktop --  xschem / klayout windows
```

You edit files on your laptop. The tools in the container read the same files. Nothing is copied back and forth.

## 2. Before you start

| Need | Minimum | Better |
|---|---|---|
| Disk space free | 20 GB | 40 GB (place and route runs are big) |
| RAM | 8 GB (tests, xschem) | 16 GB+ (place and route) |
| Internet | a few GB to download once | |
| Time | about 1 hour, mostly downloading | |

Apple Silicon (M1-M4) and Intel Macs both work. The image has native arm64 and x86 versions.

---

## 3a. macOS

1. **git and make:** open Terminal and run
   ```bash
   xcode-select --install
   ```
   Click Install in the popup. Check: `git --version` and `make --version` both print a version.
2. **Docker Desktop:** download from https://www.docker.com/products/docker-desktop/ (pick Apple Silicon or Intel),
   drag it to Applications, open it, and accept the prompts.
   Wait for the whale icon in the menu bar to stop animating. Check: `docker run --rm hello-world` prints "Hello from Docker!".
3. **Memory:** Docker Desktop > Settings > Resources > Memory: at least 8 GB. Apply & restart.
4. **uv (optional, for `make quant`):**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   Close and reopen Terminal. Check: `uv --version`.
5. Go to [step 4](#4-get-the-repo-and-the-tools-image).

The first time Docker touches your repo folder, macOS may ask whether Docker can access it. Click **Allow**.
If you click Don't Allow, the folder shows up empty inside the container. Fix it in
System Settings > Privacy & Security > Files and Folders > Docker.

## 3b. Windows

There are two ways. Use **WSL2** if you can. It is a real Linux (Ubuntu) inside Windows, so every command in
this repo works as written, including `make sim`.

### Option A: WSL2 + Ubuntu (recommended)

1. **Install WSL and Ubuntu.** Open PowerShell **as administrator** (right click > Run as administrator):
   ```powershell
   wsl --install -d Ubuntu
   ```
   Reboot when asked. After reboot an Ubuntu window opens. Pick a username and password (the password is for
   `sudo`; nothing shows as you type, that is normal).
2. **Check you are in the right Linux.** In PowerShell:
   ```powershell
   wsl -l -v
   ```
   You should see `Ubuntu` with VERSION 2. You will also see `docker-desktop`. **Never use that one.** It is
   Docker's internal system, and running docker from it fails.
   From now on, open **Ubuntu** from the Start menu. Its prompt looks like `name@PC:~$`.
3. **Docker Desktop:** install from https://www.docker.com/products/docker-desktop/ and open it. Then:
   - Settings > General > "Use the WSL 2 based engine": on.
   - Settings > Resources > WSL integration > turn on **Ubuntu**. Apply & restart.
   - Check, in Ubuntu: `docker run --rm hello-world` prints "Hello from Docker!".
4. **Tools inside Ubuntu:**
   ```bash
   sudo apt update && sudo apt install -y git make curl
   git config --global core.autocrlf input    # keep Linux line endings
   curl -LsSf https://astral.sh/uv/install.sh | sh    # optional, for make quant
   ```
5. **Work in your Linux home folder.** Run `cd ~` before cloning. Do **not** clone into `/mnt/c/...`
   (your Windows drive): it is about 10x slower, and Windows line endings break the scripts.
6. Go to [step 4](#4-get-the-repo-and-the-tools-image).

### Option B: PowerShell only (no WSL)

Works for the VNC desktop (xschem, KLayout) and for running tests inside it. You can't use `make`
or `scripts/eda.sh` directly, because PowerShell has no `make` or `bash`.

1. Install Git for Windows (https://git-scm.com/download/win). During install, choose
   "Checkout as-is, commit Unix-style line endings". Or after install: `git config --global core.autocrlf input`.
2. Install Docker Desktop and open it.
3. Clone and pull in PowerShell (step 4 commands work the same).
4. Start the VNC with the **PowerShell** command in [step 6](#6-open-the-vnc-desktop-xschem-klayout).
5. Run the tests in the VNC terminal ([step 5](#5-run-the-tests), second row).

Command Prompt (`cmd`) is different from PowerShell. If your prompt looks like `C:\Users\you>` without `PS` in front,
you are in cmd. Use the cmd command in step 6.

## 3c. Linux

1. Install git and make: `sudo apt install -y git make curl` (Debian/Ubuntu) or your distro's equivalent.
2. Install Docker Engine: https://docs.docker.com/engine/install/
3. Let your user run docker without sudo:
   ```bash
   sudo usermod -aG docker $USER
   ```
   Log out and back in. Check: `docker run --rm hello-world`.
4. Optional: `curl -LsSf https://astral.sh/uv/install.sh | sh` for `make quant`.
5. Go to step 4.

---

## 4. Get the repo and the tools image

```bash
cd ~                                                          # or wherever you keep code
git clone https://github.com/brown-open-silicon/8-bit-quant
cd 8-bit-quant
docker pull hpretl/iic-osic-tools:chipathon26
```

- The pull downloads about 5 GB once. It can take 10-40 minutes. Later runs reuse it.
- Check: `docker images` lists `hpretl/iic-osic-tools` with tag `chipathon26`.
- Set your git name once if you haven't: `git config --global user.name "<github username>"` and
  `git config --global user.email "<the email on your GitHub account>"`.

## 5. Run the tests

| Where you are | Command |
|---|---|
| macOS, Linux, WSL terminal, in the repo folder | `make sim` |
| VNC terminal (any OS, and the only option for PowerShell users) | `cd /foss/designs/8-bit-quant && python3 tb/run.py` |

Both run the same tests. `make sim` just starts a container and runs `python3 tb/run.py` inside it (see `scripts/eda.sh`).

What happens:

1. For each test group in `tb/run.py` (PE, array, accumulator, postproc, core, bus, firmware), Icarus Verilog
   compiles the RTL in `rtl/`.
2. cocotb runs the Python tests in `tb/test_*.py` against it, comparing every output with the expected values
   in `tb/vectors/`.
3. Each group prints a summary like:
   ```
   ** TESTS=4 PASS=4 FAIL=0 SKIP=0 **
   ```

**Passed:** every summary says `FAIL=0`, and the command exits without an error. The full run takes a few minutes.
The MNIST tests are the slowest.

Run one group only (faster while you work):

```bash
scripts/eda.sh "python3 tb/run.py array_ternary"      # from your laptop
python3 tb/run.py array_ternary                       # inside the VNC
```

Group names are the keys of `TESTS` in `tb/run.py`.
Build files go to `build/sim/`, which git ignores. Delete it any time.

`make quant` (optional) retrains and requantizes the model in Python (~10 s) and regenerates the vectors.
You don't need it to run the tests, because the vectors are already in the repo.

## 6. Open the VNC desktop (xschem, KLayout)

GUI tools need a screen. The container can run a whole Linux desktop and stream it to your browser (VNC).

**What "mounting" means:** `-v <your folder>:<container folder>` makes your repo folder appear inside the container.
It is the same files, not a copy. Save in xschem and the change is on your laptop. Edit in VS Code and xschem sees it.

**First time only.** In a terminal, `cd` into the repo folder, then run the command for your shell.
**Type the quotes by hand.** Quotes pasted from a chat or notes app are often curly (`“ ”`) and break the command.

| Your shell | Command |
|---|---|
| macOS, Linux, WSL (Ubuntu) | `docker run -d --name npu_vnc -p 8080:80 -v "$PWD":/foss/designs/8-bit-quant hpretl/iic-osic-tools:chipathon26` |
| Windows PowerShell (prompt starts with `PS`) | `docker run -d --name npu_vnc -p 8080:80 -v "${PWD}:/foss/designs/8-bit-quant" hpretl/iic-osic-tools:chipathon26` |
| Windows Command Prompt | `docker run -d --name npu_vnc -p 8080:80 -v "%cd%":/foss/designs/8-bit-quant hpretl/iic-osic-tools:chipathon26` |

What each part does:

| Part | Meaning |
|---|---|
| `-d` | run in the background |
| `--name npu_vnc` | a name, so you can stop and start it later |
| `-p 8080:80` | your browser's port 8080 goes to the desktop inside |
| `-v "$PWD":/foss/designs/8-bit-quant` | mount the current folder (the repo) into the container |
| `hpretl/iic-osic-tools:chipathon26` | the tools image |

Then:

1. Open http://localhost:8080 in your browser. Password: `abc123`.
2. Open a terminal in the desktop and check the mount:
   ```bash
   cd /foss/designs/8-bit-quant && ls
   ```
   You should see `rtl`, `tb`, `docs`, `Makefile`, and the rest. Empty? See Troubleshooting.
3. Switch to Sky130 ([step 7](#7-choose-the-pdk-sky130)), then open a tool from that same terminal:
   ```bash
   xschem analog/ring_osc/ring_osc.sch                    # schematic + simulation
   klayout pnr/wb_npu/runs/<run>/final/gds/wb_npu.gds     # layout (needs a finished layout run)
   ```
   No layout run yet? See the pictures in [architecture.md](architecture.md#physical-design).

Every time after that:

| Want to | Command (on your laptop, not in the VNC) |
|---|---|
| stop when done (frees memory) | `docker stop npu_vnc` |
| come back | `docker start npu_vnc`, then open http://localhost:8080 |
| see if it is running | `docker ps` |
| check what folder is mounted | `docker inspect npu_vnc --format '{{range .Mounts}}{{.Source}}{{end}}'` |
| start over (wrong folder, broken) | `docker rm -f npu_vnc`, then the `docker run` again |

`docker rm` deletes the container only, not your files. Your repo is on your laptop and is untouched.
Anything you saved *outside* `/foss/designs/8-bit-quant` inside the container is lost.

## 7. Choose the PDK (Sky130)

The PDK is the fab's rulebook and cell library. **We build on Sky130.** The container also has GF180, and the VNC
desktop **starts on GF180** by default.

In each new VNC terminal, before opening xschem or KLayout:

```bash
sak-pdk sky130A
echo $PDK            # should print sky130A
```

- It only applies to that terminal. Tools you already opened keep the old PDK, so close and reopen them.
- To make Sky130 the default for every new terminal, run once:
  ```bash
  echo 'sak-pdk sky130A' >> ~/.bashrc
  ```
  If that doesn't work, use `echo 'source sak-pdk-script.sh sky130A' >> ~/.bashrc`.
- `make sim` and `scripts/eda.sh` already use Sky130 automatically. This step is only for the VNC desktop.

Wrong PDK symptom: xschem shows red boxes or "missing symbol" for transistors.

## 8. Editing files

- Edit with any editor on your laptop. VS Code: `code .` in the repo folder.
  On WSL, run `code .` from **Ubuntu** (it installs the WSL extension the first time).
- Windows Explorer can reach WSL files at `\\wsl$\Ubuntu\home\<you>\8-bit-quant`.
- Schematics (`.sch`) are edited in xschem in the VNC. Layouts (`.gds`) are viewed in KLayout.
- Never edit files under `build/` or `pnr/*/runs/`. They are generated and not committed.

## 9. Staying up to date

```bash
git checkout main && git pull          # latest code
docker pull hpretl/iic-osic-tools:chipathon26   # only if we announce a new image
```

If the image changes, recreate the VNC container: `docker rm -f npu_vnc`, then the `docker run` again.

## 10. Other commands

| Command | Does |
|---|---|
| `make shell` | a terminal inside the tools container, repo at `/work` (no desktop) |
| `make area` | synthesize each block to Sky130 cells and report area |
| `PDK=gf180mcuD make area` | same for GF180 (comparison only) |
| `scripts/eda.sh "<command>"` | run any command inside the container, repo at `/work` |
| `scripts/eda.sh "python3 analog/ring_osc/sweep.py"` | ring oscillator PVT sweep (~1 min), remakes the plots |
| `scripts/eda.sh 'librelane --manual-pdk --pdk-root $PDK_ROOT --pdk sky130A --run-tag mine pnr/wb_npu/config.json'` | full place and route (~1-2 h, 16 GB RAM) |
| `make clean` | delete `build/` and test outputs |

## 11. Cleaning up

| To free | Command |
|---|---|
| the VNC container | `docker rm -f npu_vnc` |
| test and build outputs | `make clean` |
| the tools image (~5 GB, re-download later) | `docker rmi hpretl/iic-osic-tools:chipathon26` |
| old, unused images | `docker image prune` |

---

## Troubleshooting

Find your error message in the left column. Errors are grouped by when they happen.

### Installing Docker / WSL

| Problem | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running. Start it and wait for "Engine running". On WSL, also turn on WSL integration for Ubuntu |
| `permission denied ... docker.sock` (Linux) | `sudo usermod -aG docker $USER`, then log out and back in |
| `invoke the docker CLI from the docker-desktop WSL2 distribution` | You opened Docker's internal distro (prompt `docker-desktop:~#`). `exit`, open **Ubuntu** from the Start menu (`wsl --install -d Ubuntu` if missing), and turn on its WSL integration |
| `docker: command not found` in Ubuntu | WSL integration for Ubuntu is off. Docker Desktop > Settings > Resources > WSL integration |
| WSL install says virtualization is disabled | Turn on virtualization (Intel VT-x / AMD SVM) in your BIOS, then retry |
| `make: command not found` | macOS: `xcode-select --install`. WSL/Linux: `sudo apt install -y make` |
| `make` not recognized (PowerShell) | PowerShell has no make. Use WSL, or run the tests in the VNC terminal: `python3 tb/run.py` |
| `uv: command not found` right after installing | Close and reopen the terminal |

### Pulling the image

| Problem | Fix |
|---|---|
| `no space left on device` | Free disk space (20 GB+). `docker image prune` drops old images. On Mac, Docker Desktop > Settings > Resources > disk limit |
| Pull is very slow or stops | Retry `docker pull`. It resumes. Campus Wi-Fi can be slow; try a wired or home network |
| `manifest unknown` | Typo in the image name. It is `hpretl/iic-osic-tools:chipathon26` |

### Running the tests

| Problem | Fix |
|---|---|
| `$'\r': command not found` or `bad interpreter` | Windows line endings. `git config --global core.autocrlf input`, delete the repo, and clone again inside WSL (`~`) |
| `make sim` dies with `Killed` or exit code 137 | Out of memory. Docker Desktop > Settings > Resources: 8 GB or more |
| `No rule to make target 'sim'` | You are not in the repo folder. `cd 8-bit-quant` |
| A test says `FAIL` on `main` | That is a real bug, not your setup. Open a Bug issue with the output |
| `ModuleNotFoundError: No module named 'cocotb_tools'` | You ran `python3 tb/run.py` on your laptop, not in the container. Use `make sim`, or run it inside the VNC |

### VNC desktop

| Problem | Fix |
|---|---|
| `"$PWD" includes invalid characters for a local volume name` | You're in Command Prompt, or the quotes got pasted as curly `“ ”`. Use the command for your shell (step 6) and retype the quotes |
| `Conflict. The container name "/npu_vnc" is already in use` | It already exists: `docker start npu_vnc`. To recreate it: `docker rm -f npu_vnc` |
| `port is already allocated` | Something else uses 8080 (often another VNC container). `docker ps`, `docker stop <name>`, retry. Or use `-p 8081:80` and open http://localhost:8081 |
| Browser can't connect to localhost:8080 | The container is not running: `docker ps`. If it is missing, `docker start npu_vnc`. Still broken: `docker logs npu_vnc` |
| Browser shows a blank or black page | Wait 20 s and refresh |
| Password rejected | It is `abc123` |
| `/foss/designs/8-bit-quant` is empty | `docker run` was not run from the repo folder, or macOS access was denied. `docker rm -f npu_vnc`, `cd` into the repo, run it again, click **Allow** |
| xschem shows missing symbols (red boxes) | Wrong PDK. `sak-pdk sky130A` in that terminal, then reopen xschem |
| Files saved in the VNC don't show on my laptop | You saved outside `/foss/designs/8-bit-quant`. Only that folder is shared |
| Very slow on Windows | The repo is under `/mnt/c/`. Clone it into `~` inside WSL instead |

Still stuck? Open an issue with the **Bug** template. Paste the exact command, the full output, and your OS.
Found a new error and its fix? Add a row here in your PR.

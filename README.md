# LAMMPS Dashboard

A full-featured GUI for running, monitoring, and analysing LAMMPS molecular dynamics simulations — available as both a **desktop app** (PyQt5) and a **browser app** (Flask + Socket.IO), with complete feature parity between both.

![Platform](https://img.shields.io/badge/platform-Linux-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-green)

---

## Features

| Feature | Desktop | Browser |
|---|:---:|:---:|
| File browser (local + SSH/SFTP) | ✓ | ✓ |
| **Right-click context menus** (rename, delete, copy path…) | ✓ | ✓ |
| Drag-and-drop file upload onto file tree | — | ✓ |
| Editor with LAMMPS syntax highlighting (CodeMirror) | ✓ | ✓ |
| "Use as Input" one-click | ✓ | ✓ |
| Upload / download files (SSH) | ✓ | ✓ |
| Simulation run / stop (local + SSH remote) | ✓ | ✓ |
| LAMMPS binary auto-detect | ✓ | ✓ |
| Live log streaming, line count, colour coding | ✓ | ✓ |
| **Live thermo plot** — chart updates in real-time during run | — | ✓ |
| Auto-switch to Plots after run | ✓ | ✓ |
| Thermo plots — subplot grid or overlay | ✓ | ✓ |
| **Multi-log comparison** — overlay curves from multiple runs | — | ✓ |
| Per-column checkboxes with colour swatches | ✓ | ✓ |
| Save plots as PNG | ✓ | ✓ |
| **Variable sweep** — run same input over a parameter range | — | ✓ |
| **Run history** — browse & reload past runs | — | ✓ |
| **Browser notifications** — desktop alert when run finishes | — | ✓ |
| **Light / dark theme toggle** | — | ✓ |
| SSH profile manager (password / key auth) | ✓ | ✓ |
| Embedded terminal (local PTY + SSH shell) | — | ✓ |
| HPC / SLURM script generation | ✓ | ✓ |
| Partition query (`sinfo`), Singularity detect | ✓ | ✓ |
| Job queue table with colour-coded status | ✓ | ✓ |
| **HPC queue auto-refresh** (every 30 s) | — | ✓ |
| Submit / cancel / view job output | ✓ | ✓ |
| HPC Mode toggle (routes ▶ → sbatch) | ✓ | ✓ |
| Auto-detect HPC on SSH connect | ✓ | ✓ |
| Offline AI assistant (Ollama / Qwen3-Coder) | ✓ | ✓ |
| AI streaming with `<think>` reasoning display | ✓ | ✓ |
| Attach open file to AI query | ✓ | ✓ |
| Model download dialog (6 presets + custom) | ✓ | ✓ |
| Download progress bar | ✓ | ✓ |
| CPU-mode toggle (safe for older GPUs) | ✓ | ✓ |
| CUDA error auto-recovery | ✓ | ✓ |
| HPC config save / load | ✓ | ✓ |

---

## Quick Start

```bash
git clone <repo-url> lammps_dashboard
cd lammps_dashboard
bash setup.sh        # installs everything (prompts for optional Ollama)
```

**Desktop GUI (PyQt5):**
```bash
bash run.sh
```

**Browser version (Flask + Socket.IO):**
```bash
bash web.sh          # → http://localhost:5000
```
The browser version is accessible from any machine on the same network at `http://<host-ip>:5000`.

---

## Setup Script

`setup.sh` runs once and does everything automatically:

1. Checks Python 3.8+
2. Installs system packages (`libgl1`, `python3-venv`, etc.)
3. Creates a Python virtual environment in `venv/`
4. Installs Python packages: `PyQt5`, `matplotlib`, `paramiko`, `ollama`, `flask`, `flask-socketio`
5. Generates `icon.png` and registers a desktop application entry
6. **Optionally** installs Ollama and the AI model — if `ollama_models/` is present, it installs from there (no internet download needed)

Re-running `setup.sh` is safe — it skips already-completed steps.

---

## Tab Guide

### 📁 Files
- Browse local and SSH/SFTP directories in a resizable split pane
- CodeMirror editor with LAMMPS keyword/variable syntax highlighting
- **"▶ Use as Input"** — one click sets the Run tab input and working directory
- Save, Save As (with folder picker), and when SSH is connected: Upload / Download
- **Drag-and-drop** — drop files onto the tree to upload them (local or remote)
- **Right-click on any file or folder:**
  | Action | Description |
  |---|---|
  | Open | Open in editor |
  | Use as Input | Set as simulation input |
  | Copy Path | Copy full path to clipboard |
  | Download | Browser download (SSH only) |
  | New File / Folder Here | Create inside that directory |
  | Rename | Rename in place |
  | Delete | Permanently remove (with confirmation) |
- **Right-click on empty tree area:** New File, New Folder, Refresh

### ▶ Run
- Set input file, working directory, MPI process count, binary path, extra args
- **"Detect"** button auto-finds `lmp` binary locally or on SSH remote
- **"Run on SSH server"** checkbox — routes the run to the connected remote
- Live log with colour-coded lines (errors red, warnings yellow, thermo green)
- **Right-click log view:** Copy All, Save as .txt, Clear
- **📋 History** — browse past runs; click any row to restore its settings
- **⚡ Sweep** — expand the sweep panel, enter a variable name and space-separated values; runs each value sequentially and waits for each run to finish
- Embedded terminal in the lower half — local bash shell or SSH remote shell
- **Right-click terminal output** is handled natively by xterm.js (copy selection)

### 📈 Plots
- **● Live badge** pulses while a simulation is running; chart updates every 2 s
- **+ Compare** — load additional `log.lammps` files; all curves appear on the same subplot per column with distinct colours
- **Grid mode** — separate subplot per column (default)
- **Overlay mode** — all columns on one chart
- Remove comparison logs individually with the × button
- Save each subplot as PNG

### 🔌 SSH
- Save multiple named connection profiles (password or SSH key)
- Profiles persist across sessions in `~/.lammps_dashboard/ssh_profiles.json`
- Upload a local file to a remote path via SFTP
- Download a remote file to the browser
- Connecting auto-populates the file browser with the remote home directory

### 🖥 HPC
- Generates SLURM batch scripts:
  - Singularity container execution (`--no-home`, `--bind`, `--pwd`)
  - `D-HH:MM:SS` walltime format
  - `set -euo pipefail`, file existence checks, exit code capture
  - `export OMP_NUM_THREADS`, echo banner, `mkdir -p` log dir
- **Query Partitions** — runs `sinfo` on the remote and fills the partition field
- **Detect Singularity** — finds `singularity`/`apptainer` binary on the remote
- **Job Queue** — colour-coded table (RUNNING=green, PENDING=yellow, FAILED=red)
- **Auto ⟳ checkbox** — polls `squeue` automatically every 30 seconds
- **Right-click queue row:** View Output, Copy Job ID, Cancel Job
- **HPC Mode** toggle — when enabled, ▶ Run routes through `sbatch`
- **Auto-detect** — connecting to an HPC hostname automatically enables HPC mode, queries partitions, detects Singularity, and loads saved config

### 🤖 AI Assistant
- Runs **entirely offline** via [Ollama](https://ollama.com/) — no data leaves your machine
- Streaming responses with `<think>…</think>` reasoning displayed in a collapsible block
- **"📎 Attach File"** — attaches the currently open file's content to the next message
- **"⬇ Get Model"** dialog:
  | Model | Size | Notes |
  |---|---|---|
  | `qwen3-coder:latest` | 18 GB | Bundled — no download needed |
  | `qwen2.5-coder:7b` | 4 GB | ⭐ Recommended for most systems |
  | `qwen2.5-coder:14b` | 9 GB | Better quality |
  | `qwen2.5-coder:32b` | 18 GB | Highest quality, 32+ GB RAM |
  | `llama3.2:3b` | 2 GB | Tiny, very fast |
  | `codellama:7b` | 4 GB | Meta CodeLlama |
  | Custom | — | Any `ollama pull`-compatible name |
- **CPU mode** checkbox — use `num_gpu=0` (safe for T1000 / Turing and older GPUs)
- CUDA error auto-recovery — if a GPU error is detected, CPU mode is enabled automatically

### Header Buttons
| Button | Function |
|---|---|
| 🌙 / 🌑 | Toggle light/dark theme (saved in browser localStorage) |
| 🔔 / 🔕 | Enable/disable desktop browser notifications for run completion |
| ⬤ badge | Shows current SSH connection name |

---

## AI Assistant — Bundled Model

The `ollama_models/` folder contains the full `qwen3-coder:latest` model (18 GB). `setup.sh` installs it automatically:

- **Same filesystem**: uses hardlinks → zero extra disk space
- **Copied from USB/network**: copies the files once → no internet download

To share with another member, copy the entire `lammps_dashboard/` folder including `ollama_models/`. They run `bash setup.sh` and the model is immediately ready.

---

## Directory Structure

```
lammps_dashboard/
├── gui.py              # Desktop app (PyQt5)
├── app.py              # Browser backend (Flask + Socket.IO)
├── ssh_manager.py      # SSH/SFTP connection manager (shared)
├── make_icon.py        # App icon generator
├── icon.png            # App icon (256×256)
├── setup.sh            # One-shot setup script
├── run.sh              # Desktop launcher
├── web.sh              # Browser launcher
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Browser frontend (SPA)
├── static/
│   ├── style.css       # Dark/light theme CSS
│   └── app.js          # Browser client JavaScript (~1700 lines)
├── README.md           # This file
└── ollama_models/      # Bundled AI model (18 GB, no download)
    ├── blobs/          # Model weight files
    └── manifests/      # Ollama registry metadata
```

---

## Requirements

### System (Ubuntu/Debian)
```bash
sudo apt install python3 python3-pip python3-venv libgl1 libglib2.0-0 libdbus-1-3
# For MPI runs:
sudo apt install libopenmpi-dev openmpi-bin
```

### Python packages
```
PyQt5         matplotlib      paramiko
flask         flask-socketio  ollama
```
All installed automatically by `setup.sh`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `PyQt5` install fails | `pip install --only-binary=:all: PyQt5` |
| `mpirun` not found | `sudo apt install libopenmpi-dev openmpi-bin` |
| Desktop app won't start | Run `python3 gui.py` in terminal and check error |
| Browser app can't reach port 5000 | Check firewall: `sudo ufw allow 5000` |
| AI model slow | Normal on CPU — use `qwen2.5-coder:7b` (4 GB) for best speed |
| Ollama CUDA error (T1000/Turing GPU) | Enable **CPU mode** checkbox in AI tab |
| SSH key auth fails | Check key path or use password auth |
| HPC script not submitting | Verify SSH is connected; check sbatch path on remote |
| Notifications don't appear | Click 🔔 in header and allow when browser asks |
| Light theme looks partial | Editor panel stays dark intentionally (CodeMirror theme is fixed) |

---

## License

MIT — free for academic and research use.

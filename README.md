# LAMMPS Dashboard

A desktop GUI for running, monitoring, and analyzing LAMMPS molecular dynamics simulations on local machines or remote HPC clusters.

![Platform](https://img.shields.io/badge/platform-Linux-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-green)

---

## Features

| Feature | Description |
|---|---|
| **File Browser** | Navigate, open, edit, and save LAMMPS input files |
| **Syntax Highlighting** | LAMMPS keywords colored in the built-in editor |
| **Run Controls** | Launch `mpirun -np N lmp -in file` with live log streaming |
| **Thermo Plots** | Real-time matplotlib plots of energy, temperature, pressure, etc. |
| **SSH Remote** | Connect to remote servers via SSH/SFTP; browse, edit, and run simulations remotely |
| **HPC / SLURM** | Generate and submit SLURM batch scripts (Singularity container style, matching IITJ HPC rules) |
| **AI Assistant** | Local AI (Qwen3-Coder via Ollama) for LAMMPS scripting help — runs fully offline |
| **Dark Theme** | Professional dark UI throughout |

---

## Requirements

### System packages
- Python 3.8 or newer
- `pip` / `pip3`
- MPI implementation: **OpenMPI** or **MPICH** (for `mpirun`)
- LAMMPS binary: `lmp` somewhere on `$PATH` (optional — can specify path in the GUI)
- **Ollama** — only required for the AI assistant feature

### Python packages (installed automatically by `setup.sh`)
```
PyQt5
matplotlib
paramiko
ollama
```

---

## Quick Start

```bash
git clone <repo-url> lammps_dashboard
cd lammps_dashboard
bash setup.sh
```

Then launch:
```bash
bash run.sh
# or
python3 gui.py
```

The first run registers a desktop entry so the app appears in your application launcher.

---

## Setup Script (`setup.sh`)

`setup.sh` does the following automatically:
1. Checks for Python 3.8+
2. Creates a Python virtual environment in `venv/`
3. Installs all required Python packages
4. Installs Ollama (optional — only if you want the AI assistant)
5. Pulls the Qwen3-Coder 8B model via Ollama (optional)
6. Registers the app as a desktop application
7. Creates `run.sh` launcher

You can safely re-run `setup.sh` at any time — it skips steps that are already done.

---

## AI Assistant

The AI assistant uses [Ollama](https://ollama.com/) running a local model — **no internet connection needed**.

- Model bundled: `qwen3-coder:latest` (~18 GB) — included in `ollama_models/`
- The model runs entirely on your machine — no data is sent to any server
- GPU is optional; runs on CPU if no compatible GPU is found

### Bundled model (no download needed)

The `ollama_models/` folder contains the full model. `setup.sh` installs it automatically:
- On the **same filesystem**: uses hardlinks (zero extra disk space)
- On a **different filesystem** (e.g. USB copy): copies the files once

If you are distributing this folder, copy the entire `lammps_dashboard/` directory including `ollama_models/`. Recipients run `bash setup.sh` and the model is ready without any internet download.

To install Ollama manually if needed:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

---

## SSH / Remote Usage

1. Open the **SSH** tab → **Add Profile**
2. Enter hostname, port, username, and authentication (password or SSH key)
3. Click **Connect**

Once connected:
- The file browser shows remote files via SFTP
- The editor reads/writes files directly on the remote server
- Simulations run on the remote machine via SSH

---

## HPC / SLURM Usage

The **HPC** tab generates SLURM batch scripts matching the IITJ HPC cluster style:
- Singularity container execution
- `--ntasks` + `--cpus-per-task` separately
- `D-HH:MM:SS` time format
- Full output/error log paths
- `set -euo pipefail`, file existence checks, exit code capture

1. Connect to the HPC via SSH first
2. Fill in the HPC tab form (job name, partition, nodes, tasks, paths, SIF file)
3. Click **Generate Script** to preview
4. Click **Submit Job** to run `sbatch`
5. Use **Refresh Queue** to monitor running jobs

Config auto-saves to `~/.lammps_dashboard/hpc_config.json`.

---

## Directory Structure

```
lammps_dashboard/
├── gui.py              # Main application
├── ssh_manager.py      # SSH/SFTP connection manager
├── make_icon.py        # App icon generator
├── icon.png            # App icon
├── setup.sh            # One-shot setup script
├── run.sh              # Launch script
├── README.md           # This file
└── ollama_models/      # Bundled AI model (download needed)
    ├── blobs/          # Model weight files
    └── manifests/      # Ollama registry metadata
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `PyQt5` install fails | Run: `pip install --only-binary=:all: PyQt5` |
| `mpirun` not found | Install OpenMPI: `sudo apt install libopenmpi-dev openmpi-bin` |
| App won't start | Run `python3 gui.py` in terminal and check error output |
| AI model slow | Normal on CPU — use `qwen2.5-coder:7b` (smaller/faster) |
| Ollama CUDA error on GPU | T1000/older GPUs may be incompatible — use CPU mode checkbox in AI tab |
| SSH key auth fails | Ensure key is `~/.ssh/id_rsa` or specify path in profile |

---

## License

MIT — free for academic and research use.

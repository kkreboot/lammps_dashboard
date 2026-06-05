#!/usr/bin/env python3
"""LAMMPS Dashboard — Flask/SocketIO web backend (full feature parity with desktop GUI)."""

import os, re, signal, threading, subprocess, json, time, select, struct, datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = "lammps-dashboard-2024"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# ── Shared state ──────────────────────────────────────────────────────────────
_state = {"process": None, "running": False, "working_dir": os.path.expanduser("~"), "ssh_home": None}
_ai_stop   = threading.Event()
_pull_stop = threading.Event()
_ai_history: list = []
_job_history: list = []
_JOB_HISTORY_FILE = os.path.expanduser("~/.lammps_dashboard_jobs.json")

def _load_job_history():
    global _job_history
    try:
        if os.path.exists(_JOB_HISTORY_FILE):
            with open(_JOB_HISTORY_FILE) as f:
                _job_history = json.load(f)
    except Exception:
        _job_history = []

def _save_job_history():
    try:
        with open(_JOB_HISTORY_FILE, "w") as f:
            json.dump(_job_history[-100:], f)
    except Exception:
        pass

_load_job_history()

# ── Terminal state ────────────────────────────────────────────────────────────
_term = {"active": False, "master": None, "proc": None, "channel": None}

# ── SSH ───────────────────────────────────────────────────────────────────────
try:
    from ssh_manager import SSHManager, SSHProfile, load_profiles, save_profiles
    _ssh      = SSHManager()
    _profiles = load_profiles()
    HAS_SSH   = True
except ImportError:
    HAS_SSH = False;  _ssh = None;  _profiles = []

# ── Ollama ────────────────────────────────────────────────────────────────────
try:
    import ollama as _ollama;  HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False;  _ollama = None

LAMMPS_SYSTEM_PROMPT = (
    "You are an expert LAMMPS (Large-scale Atomic/Massively Parallel Simulator) "
    "assistant embedded in a simulation dashboard. Help with writing and debugging "
    "LAMMPS input scripts, explaining commands, interpreting log files and errors, "
    "and best practices for NPT/NVT/NVE runs.\n"
    "Rules: wrap any LAMMPS script in ```lammps … ``` fenced blocks. "
    "Keep answers focused and practical. Identify root cause of errors first."
)

# ═══════════════════════════════════════════════════════════════════════════════
# Local file API
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/files")
def list_files():
    d = os.path.expanduser(os.path.abspath(
        request.args.get("dir", _state["working_dir"])))
    try:
        entries = []
        with os.scandir(d) as it:
            for e in sorted(it, key=lambda x: (not x.is_dir(), x.name.lower())):
                if e.name.startswith("."):
                    continue
                entries.append({"name": e.name, "path": e.path,
                                 "type": "dir" if e.is_dir() else "file",
                                 "size": e.stat().st_size if e.is_file() else None})
        return jsonify({"entries": entries, "cwd": d,
                         "parent": str(Path(d).parent) if d != "/" else None})
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/file", methods=["GET"])
def read_file():
    path = request.args.get("path", "")
    try:
        with open(path, "r", errors="replace") as f:
            return jsonify({"content": f.read(), "path": path})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/file", methods=["POST"])
def write_file():
    data = request.get_json()
    path, content = data.get("path", ""), data.get("content", "")
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/mkdir", methods=["POST"])
def mkdir():
    path = request.get_json().get("path", "")
    try:
        os.makedirs(path, exist_ok=True)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

# ═══════════════════════════════════════════════════════════════════════════════
# SSH API
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ssh/status")
def ssh_status():
    if not HAS_SSH or not _ssh:
        return jsonify({"connected": False, "has_ssh": False})
    profile = _ssh.profile.to_dict() if _ssh.profile else None
    if profile and _state.get("ssh_home"):
        profile["home"] = _state["ssh_home"]
    return jsonify({
        "connected": _ssh.connected,
        "has_ssh": True,
        "profile": profile,
    })

@app.route("/api/ssh/profiles")
def ssh_get_profiles():
    return jsonify({"profiles": [p.to_dict() for p in _profiles]})

@app.route("/api/ssh/connect", methods=["POST"])
def ssh_connect():
    global _profiles
    if not HAS_SSH:
        return jsonify({"error": "paramiko not installed"}), 400
    d = request.get_json()
    profile = SSHProfile(
        name=d.get("name", "Remote"),
        host=d.get("host", ""),
        port=int(d.get("port", 22)),
        username=d.get("username", ""),
        auth=d.get("auth", "password"),
        password=d.get("password", ""),
        key_path=d.get("key_path", ""),
    )
    idx = next((i for i, p in enumerate(_profiles) if p.name == profile.name), None)
    if idx is not None:
        _profiles[idx] = profile
    else:
        _profiles.append(profile)
    save_profiles(_profiles)
    try:
        _ssh.connect(profile)
        home = _ssh.get_home()
        _state["ssh_home"] = home
        return jsonify({"ok": True, "home": home})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/ssh/disconnect", methods=["POST"])
def ssh_disconnect():
    if _ssh:
        _ssh.disconnect()
    _state["ssh_home"] = None
    return jsonify({"ok": True})

@app.route("/api/ssh/delete_profile", methods=["POST"])
def delete_ssh_profile():
    global _profiles
    name = request.get_json().get("name", "")
    _profiles = [p for p in _profiles if p.name != name]
    save_profiles(_profiles)
    return jsonify({"ok": True})

@app.route("/api/ssh/upload", methods=["POST"])
def ssh_upload():
    """Receive a base64-encoded file and write it to the remote via SFTP."""
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    import base64
    d = request.get_json()
    remote_path = d.get("remote_path", "")
    content_b64 = d.get("content", "")
    try:
        data = base64.b64decode(content_b64)
        with _ssh._lock:
            with _ssh._sftp.open(remote_path, "wb") as f:
                f.write(data)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/ssh/download_file")
def ssh_download_file():
    """Stream a remote file as a browser download."""
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    from flask import Response
    path = request.args.get("path", "")
    filename = os.path.basename(path)
    try:
        with _ssh._lock:
            with _ssh._sftp.open(path, "rb") as f:
                content = f.read()
        return Response(content, headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/octet-stream",
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/ssh/files")
def ssh_files():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    path = request.args.get("path", "/")
    try:
        entries = _ssh.list_dir(path)
        return jsonify({
            "entries": [{"name": e.name, "path": e.path,
                          "type": "dir" if e.is_dir else "file",
                          "size": e.size} for e in entries],
            "cwd": path,
            "parent": str(Path(path).parent) if path != "/" else None,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/ssh/file", methods=["GET"])
def ssh_read():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    path = request.args.get("path", "")
    try:
        return jsonify({"content": _ssh.read_file(path), "path": path})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/ssh/file", methods=["POST"])
def ssh_write():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    d = request.get_json()
    try:
        _ssh.write_file(d["path"], d["content"])
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

# ═══════════════════════════════════════════════════════════════════════════════
# Simulation run / stop
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/run", methods=["POST"])
def run_simulation():
    if _state["running"]:
        return jsonify({"error": "Already running"}), 400
    d          = request.get_json()
    inp        = d.get("input_file", "").strip()
    np_val     = int(d.get("np", 4))
    wdir       = os.path.expanduser((d.get("working_dir", "") or _state["working_dir"]).strip())
    if not wdir:
        wdir = _state["working_dir"]
    lmp_bin    = d.get("lmp_bin", "lmp").strip()
    extra      = d.get("extra_args", "").strip()
    remote     = d.get("remote", False)
    if not inp:
        return jsonify({"error": "No input file specified"}), 400

    # Resolve relative input path against working dir so LAMMPS always gets
    # an absolute path — avoids "file not found" when cwd drifts.
    if not os.path.isabs(inp):
        inp_abs = os.path.join(wdir, inp)
    else:
        inp_abs = inp
        wdir = os.path.dirname(inp_abs) or wdir

    if not remote and not os.path.isfile(inp_abs):
        return jsonify({"error": f"Input file not found: {inp_abs}"}), 400

    _state["working_dir"] = wdir
    log_path_arg = wdir.rstrip("/") + "/log.lammps"
    cmd = f"mpirun -np {np_val} {lmp_bin} -in {inp_abs} -log {log_path_arg}"
    if extra:
        cmd += f" {extra}"

    if remote and HAS_SSH and _ssh and _ssh.connected:
        def _run_remote():
            job = {"id": str(int(time.time())), "input_file": inp_abs, "working_dir": wdir,
                   "cmd": cmd, "start": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "status": "running", "returncode": None}
            _job_history.append(job); _save_job_history()
            _state["running"] = True
            socketio.emit("status", {"running": True, "cmd": cmd, "remote": True})
            _lv_hdrs = []; _lv_in = [False]
            def on_line(line):
                socketio.emit("log_line", {"line": line})
                s = line.strip()
                if re.match(r"^Step\b", s):
                    _lv_hdrs[:] = s.split(); _lv_in[0] = True
                elif _lv_in[0]:
                    if s.startswith("Loop time") or s.startswith("ERROR"):
                        _lv_in[0] = False
                    else:
                        parts = s.split()
                        if parts:
                            try:
                                vals = [float(v) for v in parts]
                                if len(vals) == len(_lv_hdrs):
                                    socketio.emit("thermo_live", {
                                        "headers": list(_lv_hdrs),
                                        "row": dict(zip(_lv_hdrs, vals))})
                            except ValueError: pass
            def on_done(rc):
                _state["running"] = False
                job["status"] = "done" if rc == 0 else "failed"
                job["returncode"] = rc; _save_job_history()
                socketio.emit("status", {"running": False, "returncode": rc})
                try:
                    content = _ssh.read_file(wdir.rstrip("/") + "/log.lammps")
                    t = _parse_thermo_str(content)
                    if t["headers"]:
                        socketio.emit("thermo_ready", t)
                except Exception:
                    pass
            try:
                _ssh.exec_stream(cmd, cwd=wdir, on_line=on_line, on_done=on_done)
            except Exception as exc:
                _state["running"] = False
                job["status"] = "failed"; job["returncode"] = -1; _save_job_history()
                socketio.emit("log_line", {"line": f"[ERROR] {exc}"})
                socketio.emit("status", {"running": False, "returncode": -1})
        threading.Thread(target=_run_remote, daemon=True).start()
    else:
        def _run_local():
            job = {"id": str(int(time.time())), "input_file": inp_abs, "working_dir": wdir,
                   "cmd": cmd, "start": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "status": "running", "returncode": None}
            _job_history.append(job); _save_job_history()
            try:
                _env = os.environ.copy()
                _env.pop("DISPLAY", None)
                proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, cwd=wdir, text=True, bufsize=1,
                    preexec_fn=os.setsid, env=_env)
                _state["process"] = proc
                _state["running"] = True
                socketio.emit("status", {"running": True, "pid": proc.pid, "cmd": cmd})
                _lv_hdrs = []; _lv_in = False
                for raw in iter(proc.stdout.readline, ""):
                    line = raw.rstrip()
                    socketio.emit("log_line", {"line": line})
                    s = line.strip()
                    if re.match(r"^Step\b", s):
                        _lv_hdrs = s.split(); _lv_in = True
                    elif _lv_in:
                        if s.startswith("Loop time") or s.startswith("ERROR"):
                            _lv_in = False
                        else:
                            parts = s.split()
                            if parts:
                                try:
                                    vals = [float(v) for v in parts]
                                    if len(vals) == len(_lv_hdrs):
                                        socketio.emit("thermo_live", {
                                            "headers": _lv_hdrs,
                                            "row": dict(zip(_lv_hdrs, vals))})
                                except ValueError: pass
                proc.wait()
                _state["running"] = False; _state["process"] = None
                job["status"] = "done" if proc.returncode == 0 else "failed"
                job["returncode"] = proc.returncode; _save_job_history()
                socketio.emit("status", {"running": False, "returncode": proc.returncode})
                log_path = os.path.join(wdir, "log.lammps")
                if os.path.exists(log_path):
                    t = _parse_thermo(log_path)
                    if t["headers"]:
                        socketio.emit("thermo_ready", t)
            except Exception as exc:
                _state["running"] = False; _state["process"] = None
                job["status"] = "failed"; job["returncode"] = -1; _save_job_history()
                socketio.emit("status", {"running": False, "returncode": -1})
                socketio.emit("log_line", {"line": f"[ERROR] {exc}"})
        threading.Thread(target=_run_local, daemon=True).start()
    return jsonify({"ok": True, "working_dir": wdir})

@app.route("/api/stop", methods=["POST"])
def stop_simulation():
    proc = _state.get("process")
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.terminate()
        _state["running"] = False
        _state["process"] = None
    if HAS_SSH and _ssh and _ssh.connected:
        _ssh.kill_remote("lmp")
    return jsonify({"ok": True})

@app.route("/api/status")
def get_status():
    return jsonify({"running": _state["running"], "working_dir": _state["working_dir"]})

# ═══════════════════════════════════════════════════════════════════════════════
# Log parsing
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_thermo_str(content: str) -> dict:
    all_headers, all_data, cur_headers, in_thermo = [], {}, [], False
    for raw in content.splitlines():
        line = raw.strip()
        if re.match(r"^Step\b", line):
            cur_headers = line.split()
            in_thermo = True
            if not all_headers:
                all_headers = cur_headers
                all_data = {h: [] for h in cur_headers}
            continue
        if in_thermo:
            if line.startswith("Loop time") or line.startswith("ERROR"):
                in_thermo = False; continue
            parts = line.split()
            if not parts: continue
            try:
                vals = [float(v) for v in parts]
                if len(vals) == len(cur_headers):
                    for h, v in zip(cur_headers, vals):
                        if h in all_data:
                            all_data[h].append(v)
            except ValueError:
                pass  # skip WARNING/info lines mid-thermo block
    return {"headers": all_headers, "data": all_data}

def _parse_thermo(path: str) -> dict:
    try:
        with open(path, "r", errors="replace") as f:
            return _parse_thermo_str(f.read())
    except Exception:
        return {"headers": [], "data": {}}

@app.route("/api/parse_log")
def parse_log():
    path   = request.args.get("path") or os.path.join(_state["working_dir"], "log.lammps")
    remote = request.args.get("remote", "false") == "true"
    try:
        if remote and HAS_SSH and _ssh and _ssh.connected:
            return jsonify(_parse_thermo_str(_ssh.read_file(path)))
        return jsonify(_parse_thermo(path))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

# ═══════════════════════════════════════════════════════════════════════════════
# HPC / SLURM
# ═══════════════════════════════════════════════════════════════════════════════

def _gen_script(c: dict) -> str:
    name    = c.get("name", "lammps_job")
    part    = c.get("partition", "medium")
    nodes   = c.get("nodes", 1)
    ntasks  = c.get("ntasks", 32)
    cpt     = c.get("cpus_per_task", 1)
    mem     = c.get("mem", "64G")
    wtime   = c.get("walltime", "5-00:00:00")
    base    = c.get("base_dir", "/scratch/data/USER/project")
    logdir  = c.get("log_dir") or f"{base}/slurm_logs"
    sif     = c.get("sif", "/scratch/data/USER/lammps/lammps.sif")
    sing    = c.get("singularity_bin", "singularity")
    bind    = c.get("bind", "$BASE:$BASE")
    rundir  = c.get("run_dir") or base
    inp     = c.get("input_file", "in.lammps")
    binary  = c.get("binary", "lmp")
    omp     = c.get("omp_threads", 1)
    extra   = c.get("lmp_extra", "")
    email   = c.get("email", "")
    use_sif = c.get("use_singularity", True)
    mail    = c.get("mail_types", [])
    sbatch_extra = c.get("extra_sbatch", [])
    modules = c.get("modules", [])

    L = [
        "#!/bin/bash",
        f"# {'=' * 61}",
        f"# SLURM job: {name}",
        "# Generated by LAMMPS Dashboard",
        f"# {'=' * 61}",
        f"#SBATCH --job-name={name}",
        f"#SBATCH --partition={part}",
        f"#SBATCH --nodes={nodes}",
        f"#SBATCH --ntasks={ntasks}",
        f"#SBATCH --cpus-per-task={cpt}",
        f"#SBATCH --mem={mem}",
        f"#SBATCH --time={wtime}",
        f"#SBATCH --output={logdir}/{name}_%j.out",
        f"#SBATCH --error={logdir}/{name}_%j.err",
    ]
    if mail and email:
        L += [f"#SBATCH --mail-type={','.join(mail)}",
              f"#SBATCH --mail-user={email}"]
    for ex in sbatch_extra:
        ex = ex.strip()
        if ex:
            L.append(ex if ex.startswith("#SBATCH") else f"#SBATCH {ex}")
    L += ["", "set -euo pipefail", "",
          "# ─── Paths ────────────────────────────────────────────────────────────",
          f"BASE={base}"]
    if use_sif:
        L += [f"SIF={sif}", f"SINGULARITY={sing}"]
    L += [
        "",
        f'RUN_DIR="${{RUN_DIR:-{rundir}}}"',
        f'INPUT_FILE="${{INPUT_FILE:-{inp}}}"',
        f"MPI_PROCS=${{SLURM_NTASKS:-{ntasks}}}",
        "", f"export OMP_NUM_THREADS={omp}", "",
        f'mkdir -p "{logdir}"', "",
        'echo "================================================================"',
        'echo " SLURM Job   : $SLURM_JOB_ID"',
        'echo " Host        : $(hostname)   Date: $(date)"',
        'echo " Partition   : $SLURM_JOB_PARTITION"',
        'echo " MPI procs   : $MPI_PROCS"',
        'echo " Run dir     : $RUN_DIR"',
        'echo " Input file  : $INPUT_FILE"',
        'echo "================================================================"', "",
        '[ -f "$RUN_DIR/$INPUT_FILE" ] || { echo "ERROR: $RUN_DIR/$INPUT_FILE not found"; exit 1; }',
    ]
    if use_sif:
        L.append('[ -f "$SIF" ]                  || { echo "ERROR: SIF not found: $SIF"; exit 1; }')
    if modules:
        L.append("")
        for mod in modules:
            L.append(f"module load {mod}")
    L.append("")
    if use_sif:
        bind_args = " \\\n    ".join(f"--bind {b.strip()}" for b in bind.split(","))
        last_line = f"        -screen none"
        if extra:
            last_line += f" \\\n        {extra}"
        L += [
            "$SINGULARITY exec --no-home \\",
            f"    {bind_args} \\",
            f'    --env "OMP_NUM_THREADS={omp}" \\',
            '    --pwd "$RUN_DIR" \\',
            '    "$SIF" \\',
            f'    mpirun -np "$MPI_PROCS" {binary} \\',
            f'        -in "$INPUT_FILE" \\',
            f'        -log "$RUN_DIR/log.lammps" \\',
            last_line,
        ]
    else:
        cmd = f'mpirun -np "$MPI_PROCS" {binary} -in "$INPUT_FILE" -log "$RUN_DIR/log.lammps" -screen none'
        if extra:
            cmd += f" {extra}"
        L.append(cmd)
    L += ["", "EXIT_CODE=$?",
          'echo "Job finished: $(date)   exit_code=$EXIT_CODE"',
          "exit $EXIT_CODE"]
    return "\n".join(L)

@app.route("/api/hpc/script", methods=["POST"])
def hpc_script():
    return jsonify({"script": _gen_script(request.get_json())})

@app.route("/api/hpc/submit", methods=["POST"])
def hpc_submit():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected to HPC via SSH"}), 400
    d = request.get_json()
    cfg = d.get("config", d)
    script = _gen_script(cfg)
    rundir = cfg.get("run_dir") or cfg.get("base_dir", "/tmp")
    name   = cfg.get("name", "lammps_job")
    remote_path = f"{rundir}/{name}.sh"
    try:
        _ssh.write_file(remote_path, script)
        out = []
        _ssh.exec_stream(f"sbatch {remote_path}", on_line=out.append, on_done=lambda rc: None)
        output = "\n".join(out)
        m = re.search(r"Submitted batch job (\d+)", output)
        return jsonify({"ok": True, "output": output, "job_id": m.group(1) if m else None})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/hpc/queue")
def hpc_queue():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected", "jobs": []}), 400
    user = _ssh.profile.username if _ssh.profile else "$USER"
    out = []
    try:
        _ssh.exec_stream(
            f"squeue -u {user} -o '%i|%j|%T|%R|%l|%P|%C|%m' --noheader 2>/dev/null",
            on_line=out.append, on_done=lambda rc: None)
        jobs = []
        for line in out:
            parts = line.split("|")
            if len(parts) >= 8:
                jobs.append({
                    "id":        parts[0].strip(),
                    "name":      parts[1].strip(),
                    "status":    parts[2].strip(),
                    "reason":    parts[3].strip(),
                    "time":      parts[4].strip(),
                    "partition": parts[5].strip(),
                    "cpus":      parts[6].strip(),
                    "mem":       parts[7].strip(),
                })
        return jsonify({"jobs": jobs})
    except Exception as exc:
        return jsonify({"error": str(exc), "jobs": []}), 400

@app.route("/api/hpc/cancel", methods=["POST"])
def hpc_cancel():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    job_id = request.get_json().get("job_id", "")
    out = []
    try:
        _ssh.exec_stream(f"scancel {job_id}", on_line=out.append, on_done=lambda rc: None)
        return jsonify({"ok": True, "output": "\n".join(out)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/hpc/output")
def hpc_output():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    path = request.args.get("path", "")
    try:
        return jsonify({"content": _ssh.read_file(path)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/hpc/sinfo")
def hpc_sinfo():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    out = []
    try:
        _ssh.exec_stream("sinfo 2>&1", on_line=out.append, on_done=lambda rc: None)
        return jsonify({"output": "\n".join(out)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/hpc/partitions")
def hpc_partitions():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    out = []
    try:
        _ssh.exec_stream("sinfo -h -o '%P' 2>/dev/null | tr -d '*'",
                         on_line=out.append, on_done=lambda rc: None)
        parts = [p.strip() for p in out if p.strip()]
        return jsonify({"partitions": parts})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/hpc/detect_singularity")
def hpc_detect_singularity():
    if not HAS_SSH or not _ssh or not _ssh.connected:
        return jsonify({"error": "Not connected"}), 400
    out = []
    try:
        _ssh.exec_stream("which singularity apptainer 2>/dev/null | head -1",
                         on_line=out.append, on_done=lambda rc: None)
        return jsonify({"binary": out[0].strip() if out else ""})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.route("/api/run/detect_binary")
def detect_binary():
    if HAS_SSH and _ssh and _ssh.connected:
        out = []
        try:
            _ssh.exec_stream("which lmp lmp_mpi lmp_serial lammps 2>/dev/null | head -1",
                             on_line=out.append, on_done=lambda rc: None)
            return jsonify({"binary": out[0].strip() if out else ""})
        except Exception as exc:
            return jsonify({"binary": "", "error": str(exc)})
    else:
        import shutil
        for name in ("lmp", "lmp_mpi", "lmp_serial", "lammps"):
            p = shutil.which(name)
            if p:
                return jsonify({"binary": p})
        return jsonify({"binary": ""})

# ═══════════════════════════════════════════════════════════════════════════════
# AI / Ollama
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ai/models")
def ai_models():
    if not HAS_OLLAMA:
        return jsonify({"models": [], "error": "ollama not installed"})
    try:
        resp = _ollama.list()
        # Handle both older dict-based API and newer object-based API
        if hasattr(resp, "models"):
            models = [getattr(m, "model", None) or getattr(m, "name", str(m)) for m in resp.models]
        else:
            models = [m.get("model", m.get("name", "")) for m in resp.get("models", [])]
        return jsonify({"models": [m for m in models if m]})
    except Exception as exc:
        return jsonify({"models": [], "error": str(exc)})

@app.route("/api/ai/history", methods=["DELETE"])
def ai_clear():
    global _ai_history
    _ai_history = []
    return jsonify({"ok": True})

@socketio.on("ai_send")
def on_ai_send(data):
    global _ai_history
    if not HAS_OLLAMA:
        emit("ai_error", {"message": "ollama not installed — run: pip install ollama"})
        return
    text     = data.get("message", "").strip()
    model    = data.get("model", "qwen3-coder:latest")
    cpu_mode = data.get("cpu_mode", True)
    if not text:
        return
    _ai_stop.clear()
    _ai_history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": LAMMPS_SYSTEM_PROMPT}] + _ai_history[-20:]

    def _stream():
        full = ""
        try:
            for chunk in _ollama.chat(model=model, messages=messages, stream=True,
                    options={"temperature": 0.3, "num_predict": 4096,
                             "num_gpu": 0 if cpu_mode else -1}):
                if _ai_stop.is_set():
                    break
                tok = chunk["message"]["content"]
                if tok:
                    full += tok
                    socketio.emit("ai_token", {"token": tok})
            _ai_history.append({"role": "assistant", "content": full})
            if len(_ai_history) > 40:
                _ai_history[:] = _ai_history[-40:]
            socketio.emit("ai_done", {})
        except Exception as exc:
            socketio.emit("ai_error", {"message": str(exc)})

    threading.Thread(target=_stream, daemon=True).start()

@socketio.on("ai_stop")
def on_ai_stop(data):
    _ai_stop.set()

@socketio.on("ai_pull")
def on_ai_pull(data):
    if not HAS_OLLAMA:
        emit("pull_done", {"success": False, "error": "ollama not installed"})
        return
    model = data.get("model", "")
    if not model:
        return
    _pull_stop.clear()

    def _pull():
        try:
            for chunk in _ollama.pull(model, stream=True):
                if _pull_stop.is_set():
                    break
                total     = chunk.get("total") or 0
                completed = chunk.get("completed") or 0
                pct = min(int(completed / total * 100), 99) if total > 0 else 0
                socketio.emit("pull_progress", {
                    "model": model, "status": chunk.get("status", ""),
                    "pct": pct,
                    "done_gb":  completed / 1_073_741_824 if total > 0 else 0.0,
                    "total_gb": total     / 1_073_741_824 if total > 0 else 0.0,
                })
            socketio.emit("pull_done", {"success": True, "model": model})
        except Exception as exc:
            socketio.emit("pull_done", {"success": False, "error": str(exc), "model": model})

    threading.Thread(target=_pull, daemon=True).start()

@socketio.on("pull_stop")
def on_pull_stop(data):
    _pull_stop.set()

# ═══════════════════════════════════════════════════════════════════════════════
# Job history
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/jobs")
def get_jobs():
    return jsonify({"jobs": list(reversed(_job_history[-50:]))})

@app.route("/api/jobs", methods=["DELETE"])
def clear_jobs():
    global _job_history
    _job_history = []
    _save_job_history()
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════════════════════
# Terminal (PTY)
# ═══════════════════════════════════════════════════════════════════════════════

def _term_kill():
    """Tear down any active terminal session."""
    _term["active"] = False
    ch = _term.pop("channel", None)
    if ch:
        try: ch.close()
        except Exception: pass
    proc = _term.pop("proc", None)
    if proc:
        try: proc.terminate()
        except Exception: pass
    master = _term.pop("master", None)
    if master is not None:
        try: os.close(master)
        except Exception: pass
    _term.update({"active": False, "master": None, "proc": None, "channel": None})


@socketio.on("term_start")
def on_term_start(data):
    rows = int(data.get("rows", 24))
    cols = int(data.get("cols", 80))
    remote = data.get("remote", False)
    cwd    = data.get("cwd", "") or _state["working_dir"] or os.path.expanduser("~")

    _term_kill()

    if remote and HAS_SSH and _ssh and _ssh.connected:
        try:
            chan = _ssh._client.invoke_shell(term="xterm-256color", width=cols, height=rows)
            _term["channel"] = chan
            _term["active"]  = True

            def _relay_ssh():
                while _term["active"]:
                    try:
                        r, _, _ = select.select([chan], [], [], 0.05)
                        if r:
                            chunk = chan.recv(4096)
                            if not chunk:
                                break
                            socketio.emit("term_output", {"data": chunk.decode("utf-8", errors="replace")})
                    except Exception:
                        break
                _term["active"] = False
                socketio.emit("term_exit", {})

            threading.Thread(target=_relay_ssh, daemon=True).start()
            # cd to working dir on remote
            time.sleep(0.3)
            if cwd and cwd != "/":
                chan.sendall(f"cd {cwd}\n".encode())
            emit("term_ready", {"remote": True})
        except Exception as exc:
            emit("term_error", {"message": str(exc)})
    else:
        try:
            import pty, fcntl, termios
            master, slave = pty.openpty()
            # set initial window size
            fcntl.ioctl(slave, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
            env = {**os.environ, "TERM": "xterm-256color"}
            env.pop("DISPLAY", None)
            proc = subprocess.Popen(
                [os.environ.get("SHELL", "/bin/bash")],
                stdin=slave, stdout=slave, stderr=slave,
                cwd=cwd, close_fds=True, env=env,
            )
            os.close(slave)
            _term["proc"]   = proc
            _term["master"] = master
            _term["active"] = True

            def _relay_local():
                while _term["active"]:
                    try:
                        r, _, _ = select.select([master], [], [], 0.05)
                        if r:
                            chunk = os.read(master, 4096)
                            if not chunk:
                                break
                            socketio.emit("term_output", {"data": chunk.decode("utf-8", errors="replace")})
                    except OSError:
                        break
                _term["active"] = False
                socketio.emit("term_exit", {})

            threading.Thread(target=_relay_local, daemon=True).start()
            emit("term_ready", {"remote": False})
        except Exception as exc:
            emit("term_error", {"message": str(exc)})


@socketio.on("term_input")
def on_term_input(data):
    text = data.get("data", "")
    if not text:
        return
    raw = text.encode("utf-8")
    chan = _term.get("channel")
    if chan:
        try: chan.sendall(raw)
        except Exception: pass
    elif _term.get("master") is not None:
        try: os.write(_term["master"], raw)
        except OSError: pass


@socketio.on("term_resize")
def on_term_resize(data):
    rows = int(data.get("rows", 24))
    cols = int(data.get("cols", 80))
    chan = _term.get("channel")
    if chan:
        try: chan.resize_pty(width=cols, height=rows)
        except Exception: pass
    master = _term.get("master")
    if master is not None:
        try:
            import fcntl, termios
            fcntl.ioctl(master, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except Exception: pass


@socketio.on("term_stop")
def on_term_stop(data):
    _term_kill()
    emit("term_exit", {})


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    print("LAMMPS Dashboard  →  http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)

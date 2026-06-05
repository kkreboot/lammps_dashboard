#!/usr/bin/env bash
# =============================================================================
# LAMMPS Dashboard — One-shot setup script
# Compatible with Ubuntu 20.04+ / Debian 11+ / any systemd Linux with apt
# Run: bash setup.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
ICON_PNG="$SCRIPT_DIR/icon.png"
DESKTOP_FILE="$HOME/.local/share/applications/lammps-dashboard.desktop"
CONFIG_DIR="$HOME/.lammps_dashboard"
BUNDLED_MODELS="$SCRIPT_DIR/ollama_models"
OLLAMA_MODEL_NAME="qwen3-coder:latest"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
banner()  { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

# ── Step 1: Python version check ──────────────────────────────────────────────
banner "Step 1/7 — Checking Python"

PYTHON=""
for cmd in python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info[:2])')
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
            PYTHON="$cmd"
            ok "Found $PYTHON ($ver)"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    error "Python 3.8+ not found."
    echo "Install with: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# ── Step 2: System dependencies ───────────────────────────────────────────────
banner "Step 2/7 — Checking system packages"

MISSING_APT=()
check_apt() {
    dpkg -s "$1" &>/dev/null || MISSING_APT+=("$1")
}

# PyQt5 needs these system libs
check_apt python3-pip
check_apt python3-venv
check_apt libgl1
check_apt libglib2.0-0
check_apt libdbus-1-3
check_apt libxcb-cursor0 2>/dev/null || true   # optional, suppresses Qt warning

if [[ ${#MISSING_APT[@]} -gt 0 ]]; then
    warn "Missing system packages: ${MISSING_APT[*]}"
    read -rp "  Install them now via apt? [Y/n] " ans
    ans="${ans:-Y}"
    if [[ "$ans" =~ ^[Yy] ]]; then
        sudo apt-get update -q
        sudo apt-get install -y "${MISSING_APT[@]}"
        ok "System packages installed."
    else
        warn "Skipping. The app may not start without these."
    fi
else
    ok "All system packages present."
fi

# ── Step 3: Python virtual environment ────────────────────────────────────────
banner "Step 3/7 — Python virtual environment"

if [[ -d "$VENV_DIR" ]]; then
    ok "Virtual environment already exists at $VENV_DIR"
else
    info "Creating venv at $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "venv created."
fi

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

"$PIP" install --upgrade pip --quiet

# ── Step 4: Python packages ───────────────────────────────────────────────────
banner "Step 4/7 — Installing Python packages"

install_pkg() {
    local pkg="$1"; shift
    local extra_args=("$@")
    if "$PY" -c "import ${pkg%%[>=<! ]*}" 2>/dev/null; then
        ok "$pkg already installed."
    else
        info "Installing $pkg ..."
        "$PIP" install "${extra_args[@]}" "$pkg" --quiet && ok "$pkg installed." || {
            error "Failed to install $pkg"
            return 1
        }
    fi
}

# PyQt5 — must use binary wheel (source build is fragile)
if "$PY" -c "from PyQt5.QtWidgets import QApplication" 2>/dev/null; then
    ok "PyQt5 already installed."
else
    info "Installing PyQt5 (binary wheel) ..."
    "$PIP" install --only-binary=:all: PyQt5 --quiet && ok "PyQt5 installed." || {
        error "PyQt5 install failed."
        echo "  Try manually: $PIP install --only-binary=:all: PyQt5"
        exit 1
    }
fi

install_pkg matplotlib
install_pkg paramiko

# Ollama Python client (optional — for AI assistant)
if "$PY" -c "import ollama" 2>/dev/null; then
    ok "ollama (Python client) already installed."
else
    info "Installing ollama Python client ..."
    "$PIP" install ollama --quiet && ok "ollama client installed." || warn "ollama Python client failed to install — AI assistant will be disabled."
fi

# ── Step 5: Generate icon ─────────────────────────────────────────────────────
banner "Step 5/7 — App icon"

if [[ -f "$ICON_PNG" ]]; then
    ok "icon.png already exists."
else
    info "Generating icon ..."
    "$PY" "$SCRIPT_DIR/make_icon.py" && ok "icon.png generated." || warn "Icon generation failed (display required). Using fallback."
fi

# Install icon to XDG icon path for desktop integration
ICON_DEST="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$ICON_DEST"
if [[ -f "$ICON_PNG" ]]; then
    cp "$ICON_PNG" "$ICON_DEST/lammps-dashboard.png"
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    fi
    ok "Icon installed to $ICON_DEST"
fi

# ── Step 6: Desktop entry ─────────────────────────────────────────────────────
banner "Step 6/7 — Desktop integration"

mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=LAMMPS Dashboard
GenericName=Molecular Dynamics GUI
Comment=GUI dashboard to run, monitor, and plot LAMMPS simulations
Exec=$VENV_DIR/bin/python $SCRIPT_DIR/gui.py
Icon=lammps-dashboard
Terminal=false
StartupNotify=true
StartupWMClass=lammps-dashboard
Categories=Science;Physics;Education;
Keywords=LAMMPS;molecular dynamics;simulation;MD;atomistic;
EOF

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi
ok "Desktop entry created: $DESKTOP_FILE"

# ── Step 7: run.sh launcher ───────────────────────────────────────────────────
banner "Step 7/7 — Launch script"

cat > "$SCRIPT_DIR/run.sh" <<EOF
#!/usr/bin/env bash
# Launch LAMMPS Dashboard
cd "\$(dirname "\$(realpath "\$0")")"
exec "$VENV_DIR/bin/python" gui.py "\$@"
EOF
chmod +x "$SCRIPT_DIR/run.sh"
ok "run.sh created."

# ── Config directory ──────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"

# ── Ollama installation + model setup ─────────────────────────────────────────
echo ""
echo -e "${BOLD}AI Assistant — Ollama + ${OLLAMA_MODEL_NAME}${NC}"
echo "  This enables the built-in AI coding assistant (runs fully offline)."
echo ""

# Install Ollama binary if missing
if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'found')"
    OLLAMA_INSTALLED=true
else
    read -rp "  Install Ollama now? [Y/n] " ans_ollama
    ans_ollama="${ans_ollama:-Y}"
    if [[ "$ans_ollama" =~ ^[Yy] ]]; then
        info "Downloading and installing Ollama ..."
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installed."
        OLLAMA_INSTALLED=true
    else
        warn "Skipping Ollama. AI assistant will be disabled in the dashboard."
        OLLAMA_INSTALLED=false
    fi
fi

if [[ "${OLLAMA_INSTALLED:-false}" == "true" ]]; then
    # Check if model is already registered with Ollama
    if ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL_NAME%%:*}"; then
        ok "Model '$OLLAMA_MODEL_NAME' already available in Ollama."
    elif [[ -d "$BUNDLED_MODELS/blobs" ]]; then
        # ── Install bundled model (no download needed) ──────────────────────
        info "Found bundled model in ollama_models/ — installing locally (no download) ..."
        OLLAMA_HOME="${HOME}/.ollama"
        DEST_BLOBS="$OLLAMA_HOME/models/blobs"
        DEST_MANIFESTS="$OLLAMA_HOME/models/manifests"
        mkdir -p "$DEST_BLOBS" "$DEST_MANIFESTS"

        # Hard-link blobs if same filesystem, else copy
        SRC_DEV=$(stat -c '%d' "$BUNDLED_MODELS/blobs")
        DEST_DEV=$(stat -c '%d' "$DEST_BLOBS")
        COPIED=0; LINKED=0; SKIPPED=0

        for blob in "$BUNDLED_MODELS/blobs"/sha256-*; do
            [[ -f "$blob" ]] || continue
            name=$(basename "$blob")
            dest="$DEST_BLOBS/$name"
            if [[ -e "$dest" ]]; then
                SKIPPED=$((SKIPPED+1))
                continue
            fi
            if [[ "$SRC_DEV" == "$DEST_DEV" ]]; then
                ln "$blob" "$dest" && LINKED=$((LINKED+1))
            else
                info "  Copying $name (this may take a while for the large model file) ..."
                cp "$blob" "$dest" && COPIED=$((COPIED+1))
            fi
        done

        # Copy manifest tree
        if [[ -d "$BUNDLED_MODELS/manifests" ]]; then
            cp -r "$BUNDLED_MODELS/manifests/." "$DEST_MANIFESTS/"
        fi

        ok "Model installed: $LINKED hardlinked, $COPIED copied, $SKIPPED already present."
        ok "Model '$OLLAMA_MODEL_NAME' ready — no internet download needed."
    else
        # ── No bundled model — offer to download ───────────────────────────
        warn "No bundled model found in ollama_models/."
        echo ""
        echo "  Available models to download:"
        echo "    1) qwen3-coder:latest  ~18 GB — best quality (same as bundled)"
        echo "    2) qwen2.5-coder:7b    ~4 GB  — faster, lower RAM"
        echo "    3) Skip"
        echo ""
        read -rp "  Download which model? [1/2/3]: " model_choice
        case "${model_choice:-3}" in
            1)
                info "Pulling qwen3-coder:latest (~18 GB) ..."
                ollama pull qwen3-coder:latest && ok "Model ready." || warn "Pull failed — run: ollama pull qwen3-coder:latest"
                ;;
            2)
                info "Pulling qwen2.5-coder:7b (~4 GB) ..."
                ollama pull qwen2.5-coder:7b && ok "Model ready." || warn "Pull failed — run: ollama pull qwen2.5-coder:7b"
                ;;
            *)
                warn "Skipping model. Pull manually later: ollama pull qwen3-coder:latest"
                ;;
        esac
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Setup complete!${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo ""
echo "  Launch the dashboard:"
echo -e "    ${CYAN}bash $SCRIPT_DIR/run.sh${NC}"
echo ""
echo "  Or find 'LAMMPS Dashboard' in your application menu."
echo ""

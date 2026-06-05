#!/usr/bin/env python3
"""LAMMPS Dashboard — PyQt5 desktop GUI."""

import os
import re
import sys
import queue
import signal
import subprocess
import threading
from pathlib import Path

# Strip ANSI/VT100 terminal escape codes from ollama log output
_ANSI_RE = re.compile(
    r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])'   # ESC sequences
    r'|[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]'       # other control chars
)

from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QTimer, QSize,
                           QFileSystemWatcher, QDir)
from PyQt5.QtGui import (QColor, QFont, QFontDatabase, QPalette,
                          QTextCharFormat, QSyntaxHighlighter, QIcon,
                          QTextCursor)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QTextEdit,
    QPlainTextEdit, QLabel, QPushButton, QLineEdit, QSpinBox,
    QCheckBox, QFileDialog, QMessageBox, QFrame, QScrollArea,
    QSizePolicy, QGroupBox, QInputDialog, QStatusBar, QToolButton,
    QComboBox, QGridLayout, QProgressBar, QDialog, QHeaderView,
    QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem,
    QAbstractItemView,
)

# ── Ollama (optional) ─────────────────────────────────────────────────────────
try:
    import ollama as _ollama_lib
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

# ── SSH manager ───────────────────────────────────────────────────────────────
try:
    from ssh_manager import SSHManager, SSHProfile, load_profiles, save_profiles, RemoteEntry
    HAS_SSH = True
except ImportError:
    HAS_SSH = False

# ── Try matplotlib ────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Qt5Agg")
    from matplotlib.backends.backend_qt5agg import (
        FigureCanvasQTAgg as FigureCanvas,
        NavigationToolbar2QT as NavToolbar,
    )
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = "#1e2227"
BG2     = "#23272b"
BG3     = "#111418"
BG_EDIT = "#16191e"
FG      = "#c8d0de"
FG2     = "#8892a4"
ACCENT  = "#4fc3f7"
GREEN   = "#81c784"
RED     = "#ef5350"
YELLOW  = "#ffb74d"
BORDER  = "#2d3340"
SEL     = "#1c2536"
ORANGE  = "#f9a825"

MONO_FONT = "Courier New"
UI_FONT   = "Segoe UI"


def _pal():
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(BG))
    p.setColor(QPalette.WindowText,      QColor(FG))
    p.setColor(QPalette.Base,            QColor(BG2))
    p.setColor(QPalette.AlternateBase,   QColor(BG3))
    p.setColor(QPalette.Text,            QColor(FG))
    p.setColor(QPalette.Button,          QColor(BG2))
    p.setColor(QPalette.ButtonText,      QColor(FG))
    p.setColor(QPalette.Highlight,       QColor(SEL))
    p.setColor(QPalette.HighlightedText, QColor(ACCENT))
    p.setColor(QPalette.Link,            QColor(ACCENT))
    p.setColor(QPalette.ToolTipBase,     QColor(BG2))
    p.setColor(QPalette.ToolTipText,     QColor(FG))
    return p


STYLE = f"""
/* ── Base ──────────────────────────────────────────────────────────────── */
* {{
    font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", system-ui, sans-serif;
    font-size: 10pt;
}}
QWidget {{
    background: {BG};
    color: {FG};
    selection-background-color: {SEL};
    selection-color: #e8f4ff;
}}
QMainWindow {{ background: {BG}; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; height: 1px; }}

/* ── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #2a2f3e, stop:1 #1e2230);
    color: {FG};
    border: 1px solid #363d52;
    border-bottom: 1px solid #191d28;
    border-radius: 6px;
    padding: 5px 16px;
    font-size: 9.5pt;
    min-width: 52px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #333a50, stop:1 #272c3c);
    border-color: #4a5270;
    color: #e4ecff;
}}
QPushButton:pressed {{
    background: #13161e;
    border-color: {ACCENT};
    color: {ACCENT};
    padding-top: 6px;
    padding-bottom: 4px;
}}
QPushButton:disabled {{ color: #3c4255; border-color: #252830; background: #181b22; }}

QPushButton#run {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #1c4228, stop:1 #122c1a);
    color: {GREEN};
    border: 1px solid #2e6040;
    border-bottom-color: #1a3d24;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QPushButton#run:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #245535, stop:1 #183822);
    border-color: {GREEN};
}}
QPushButton#run:pressed {{ background:#0f2018; border-color:{GREEN}; }}
QPushButton#run:disabled {{ background:#171e17; color:#2e4830; border-color:#252830; }}

QPushButton#stop {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #3c1a1a, stop:1 #281010);
    color: {RED};
    border: 1px solid #5c2828;
    border-bottom-color: #3a1818;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QPushButton#stop:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #502020, stop:1 #381818);
    border-color: {RED};
}}
QPushButton#stop:pressed {{ background:#1a0e0e; border-color:{RED}; }}
QPushButton#stop:disabled {{ background:#1c1515; color:#422020; border-color:#252830; }}

QPushButton#save {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #1a3050, stop:1 #102038);
    color: {ACCENT};
    border: 1px solid #284870;
    border-bottom-color: #162840;
    font-weight: 600;
}}
QPushButton#save:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #214068, stop:1 #162a48);
    border-color: {ACCENT};
}}

/* ── Tab bar ──────────────────────────────────────────────────────────── */
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{
    background: {BG2};
    border-bottom: 1px solid {BORDER};
}}
QTabBar::tab {{
    background: transparent;
    color: {FG2};
    padding: 10px 22px 8px 22px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 9.5pt;
    font-weight: 500;
    margin-right: 1px;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
    font-weight: 700;
    background: rgba(79,195,247,0.05);
}}
QTabBar::tab:hover:!selected {{
    color: #c8d8f0;
    background: rgba(255,255,255,0.03);
    border-bottom: 2px solid #2d3340;
}}

/* ── Plain/text editors ───────────────────────────────────────────────── */
QPlainTextEdit, QTextEdit {{
    background: {BG3};
    color: {FG};
    border: none;
    selection-background-color: {SEL};
    selection-color: #e8f4ff;
}}

/* ── Line / spin / combo inputs ───────────────────────────────────────── */
QLineEdit, QSpinBox, QComboBox {{
    background: {BG3};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 9.5pt;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
    background: #0c0f16;
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
    border-color: #3e4860;
}}
QLineEdit::placeholder {{ color: #4a5268; }}

QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: right center;
    width: 24px;
    border: none;
}}
QComboBox::down-arrow {{
    width: 0; height: 0;
    border-left:  5px solid transparent;
    border-right: 5px solid transparent;
    border-top:   6px solid {FG2};
    margin-right: 7px;
}}
QComboBox QAbstractItemView {{
    background: {BG2};
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    selection-background-color: {SEL};
    selection-color: {ACCENT};
    outline: none;
    padding: 4px 0;
}}
QComboBox QAbstractItemView::item {{ padding: 5px 12px; }}

QSpinBox::up-button, QSpinBox::down-button {{
    background: {BORDER};
    border: none;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #3a4260; }}
QSpinBox::up-arrow   {{ border-left:4px solid transparent; border-right:4px solid transparent;
                         border-bottom:5px solid {FG2}; }}
QSpinBox::down-arrow {{ border-left:4px solid transparent; border-right:4px solid transparent;
                         border-top:5px solid {FG2}; }}

/* ── Tree widget ──────────────────────────────────────────────────────── */
QTreeWidget {{
    background: {BG2};
    color: {FG};
    border: none;
    outline: none;
    show-decoration-selected: 1;
}}
QTreeWidget::item {{
    padding: 4px 6px;
    border-radius: 4px;
    min-height: 22px;
}}
QTreeWidget::item:selected {{
    background: {SEL};
    color: {ACCENT};
    border-radius: 4px;
}}
QTreeWidget::item:hover:!selected {{
    background: rgba(255,255,255,0.045);
    border-radius: 4px;
}}
QHeaderView::section {{
    background: {BG2};
    color: {FG2};
    border: none;
    padding: 4px 8px;
    font-size: 8pt;
    font-weight: 700;
}}

/* ── Scrollbars ───────────────────────────────────────────────────────── */
QScrollBar:vertical   {{ background: transparent; width: 8px; margin: 2px 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0 2px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #353b50;
    border-radius: 4px;
    min-height: 24px;
    min-width:  24px;
}}
QScrollBar::handle:hover {{ background: #4a5270; }}
QScrollBar::handle:pressed {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Progress bar ─────────────────────────────────────────────────────── */
QProgressBar {{
    background: {BG3};
    border: 1px solid {BORDER};
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #0077b8, stop:0.5 {ACCENT}, stop:1 #80d8ff);
    border-radius: 4px;
}}

/* ── Checkboxes ───────────────────────────────────────────────────────── */
QCheckBox {{ color: {FG}; spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG3};
}}
QCheckBox::indicator:hover  {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #1a80c0, stop:1 {ACCENT});
    border-color: {ACCENT};
}}

/* ── Group box ────────────────────────────────────────────────────────── */
QGroupBox {{
    color: {FG2};
    font-size: 8pt;
    font-weight: 700;
    border: 1px solid {BORDER};
    border-radius: 7px;
    margin-top: 14px;
    padding-top: 10px;
    background: rgba(255,255,255,0.01);
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    background: {BG};
    color: {FG2};
}}

/* ── Labels ───────────────────────────────────────────────────────────── */
QLabel#section {{
    color: {FG2};
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 0.8px;
}}

/* ── Status bar ───────────────────────────────────────────────────────── */
QStatusBar {{
    background: {BG2};
    color: {FG2};
    font-size: 8pt;
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{ border: none; }}

/* ── Tooltips ─────────────────────────────────────────────────────────── */
QToolTip {{
    background: #252a38;
    color: {FG};
    border: 1px solid #3a4058;
    border-radius: 5px;
    padding: 5px 10px;
    font-size: 9pt;
}}

/* ── Frame separators ─────────────────────────────────────────────────── */
QFrame[frameShape="4"] {{ background: {BORDER}; max-height: 1px; border: none; }}
QFrame[frameShape="5"] {{ background: {BORDER}; max-width:  1px; border: none; }}

/* ── Menu (right-click context) ───────────────────────────────────────── */
QMenu {{
    background: #20242f;
    color: {FG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SEL}; color: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
"""


# ── Syntax Highlighter ────────────────────────────────────────────────────────

class LammpsHighlighter(QSyntaxHighlighter):
    KEYWORDS = (
        r"\b(units|atom_style|atom_modify|boundary|dimension|lattice|region|create_box|"
        r"create_atoms|mass|pair_style|pair_coeff|kspace_style|bond_style|bond_coeff|"
        r"angle_style|angle_coeff|dihedral_style|dihedral_coeff|improper_style|improper_coeff|"
        r"neighbor|neigh_modify|group|fix|unfix|compute|variable|thermo|thermo_style|"
        r"thermo_modify|dump|dump_modify|undump|run|minimize|velocity|timestep|"
        r"read_data|read_restart|write_data|write_restart|write_dump|reset_timestep|"
        r"change_box|replicate|include|echo|log|print|if|then|else|label|jump|next|quit)\b"
    )

    def __init__(self, doc):
        super().__init__(doc)
        def fmt(color, bold=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(700)
            return f

        self._rules = [
            (re.compile(r"#.*"),              fmt("#6a8759")),        # comment
            (re.compile(self.KEYWORDS),        fmt(ACCENT, bold=True)),  # keyword
            (re.compile(r'"[^"]*"'),           fmt(GREEN)),            # string
            (re.compile(r"'[^']*'"),           fmt(GREEN)),
            (re.compile(r"\b-?\d+\.?\d*(?:[eE][+-]?\d+)?\b"), fmt(YELLOW)),  # number
            (re.compile(r"\$\{?\w+\}?"),       fmt(RED)),             # variable ref
        ]

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ── Log streaming thread ──────────────────────────────────────────────────────

class SimRunner(QThread):
    line_ready = pyqtSignal(str)
    finished   = pyqtSignal(int)   # return code
    error      = pyqtSignal(str)

    def __init__(self, cmd, cwd):
        super().__init__()
        self.cmd  = cmd
        self.cwd  = cwd
        self._proc = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                self.cmd, shell=True, cwd=self.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                preexec_fn=os.setsid,
            )
            for line in iter(self._proc.stdout.readline, ""):
                self.line_ready.emit(line.rstrip())
            self._proc.wait()
            self.finished.emit(self._proc.returncode)
        except Exception as exc:
            self.error.emit(str(exc))

    def kill(self):
        if self._proc:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except Exception:
                self._proc.terminate()


# ── Ollama streaming thread ───────────────────────────────────────────────────

LAMMPS_SYSTEM_PROMPT = """You are an expert LAMMPS (Large-scale Atomic/Massively Parallel Simulator) \
assistant embedded inside a simulation dashboard. You help with:
- Writing and debugging LAMMPS input scripts
- Explaining commands, fix styles, pair styles, and compute options
- Suggesting force-field parameters and potential files
- Interpreting log files, thermo output, and error messages
- Recommending best practices for NPT/NVT/NVE ensembles, minimization, and equilibration

Rules:
- Wrap any LAMMPS input script in ```lammps … ``` fenced blocks.
- Keep answers focused and practical.
- If given a log or error, identify the root cause first, then give the fix.
- When in doubt about a system-specific detail, say so clearly."""


_CUDA_ERR_PAT = re.compile(
    r"cuda error|device kernel image is invalid|llama-server.*terminated|"
    r"status code: 5\d\d|out of memory|CUDA",
    re.I,
)


class OllamaStreamer(QThread):
    token      = pyqtSignal(str)
    done       = pyqtSignal()
    error      = pyqtSignal(str)
    cuda_error = pyqtSignal()    # emitted when a GPU crash is detected

    def __init__(self, model: str, messages: list, num_gpu: int = 0):
        super().__init__()
        self._model    = model
        self._messages = messages
        self._num_gpu  = num_gpu   # 0 = CPU only, -1 = all layers on GPU
        self._stop     = False

    def run(self):
        if not HAS_OLLAMA:
            self.error.emit("ollama package not installed  (pip3 install ollama)")
            return
        try:
            stream = _ollama_lib.chat(
                model=self._model,
                messages=self._messages,
                stream=True,
                options={
                    "temperature": 0.3,
                    "num_predict": 4096,
                    "num_gpu": self._num_gpu,
                },
            )
            for chunk in stream:
                if self._stop:
                    break
                tok = chunk["message"]["content"]
                if tok:
                    self.token.emit(tok)
            self.done.emit()
        except Exception as exc:
            msg = str(exc)
            if _CUDA_ERR_PAT.search(msg):
                self.cuda_error.emit()
            self.error.emit(msg)

    def stop(self):
        self._stop = True


# ── Ollama model pull thread ──────────────────────────────────────────────────

class ModelPullThread(QThread):
    """Streams an `ollama pull` with real progress; no log-file polling needed."""
    progress = pyqtSignal(str, int, float, float)  # status, pct, done_gb, total_gb
    finished = pyqtSignal(bool, str)               # success, model_or_error

    def __init__(self, model: str):
        super().__init__()
        self._model = model
        self._stop  = False

    def run(self):
        if not HAS_OLLAMA:
            self.finished.emit(False, "ollama package not installed")
            return
        try:
            for chunk in _ollama_lib.pull(self._model, stream=True):
                if self._stop:
                    break
                status    = chunk.get("status", "")
                total     = chunk.get("total", 0)
                completed = chunk.get("completed", 0)
                if total > 0:
                    pct      = min(int(completed / total * 100), 99)
                    done_gb  = completed / 1_073_741_824
                    total_gb = total     / 1_073_741_824
                else:
                    pct, done_gb, total_gb = 0, 0.0, 0.0
                self.progress.emit(status, pct, done_gb, total_gb)
            self.finished.emit(True, self._model)
        except Exception as exc:
            self.finished.emit(False, str(exc))

    def stop(self):
        self._stop = True


# ── SFTP file / directory picker dialog ──────────────────────────────────────

class SFTPFilePicker(QDialog):
    """Minimal SFTP browser that returns a remote path."""

    def __init__(self, ssh_mgr, start_path: str = "/",
                 parent=None, mode: str = "file"):
        super().__init__(parent)
        self._ssh  = ssh_mgr
        self._cur  = start_path
        self._mode = mode          # "file" | "dir"
        self.selected_path: str = ""

        self.setWindowTitle("Browse Remote Files" if mode == "file"
                            else "Select Remote Directory")
        self.resize(560, 480)
        self.setStyleSheet(f"background:{BG}; color:{FG};")

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.setContentsMargins(10, 10, 10, 10)

        # ── Path bar ──────────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(4)
        lbl = QLabel("🖥")
        lbl.setFixedWidth(20)
        lbl.setStyleSheet("font-size:11pt; background:transparent;")
        self._path_edit = QLineEdit(start_path)
        self._path_edit.setStyleSheet(
            f"background:{BG3}; color:{ACCENT}; border:1px solid {BORDER};"
            f"border-radius:4px; padding:3px 8px; font-size:9pt;"
        )
        self._path_edit.returnPressed.connect(
            lambda: self._navigate(self._path_edit.text().strip()))
        go = QPushButton("➜")
        go.setFixedSize(28, 28)
        go.setStyleSheet(
            f"color:{ACCENT}; background:#1a2535; border:1px solid #284870;"
            f"border-radius:4px; font-size:11pt; padding:0;")
        go.clicked.connect(lambda: self._navigate(self._path_edit.text().strip()))
        bar.addWidget(lbl)
        bar.addWidget(self._path_edit, 1)
        bar.addWidget(go)
        lay.addLayout(bar)

        # ── File list ─────────────────────────────────────────────────────
        from PyQt5.QtWidgets import QHeaderView
        self._list = QTreeWidget()
        self._list.setHeaderLabels(["Name", "Size"])
        self._list.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._list.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._list.setRootIsDecorated(False)
        self._list.setStyleSheet(
            f"QTreeWidget{{background:{BG2};border:1px solid {BORDER};border-radius:5px;outline:none;}}"
            f"QTreeWidget::item{{padding:4px 6px;min-height:22px;}}"
            f"QTreeWidget::item:selected{{background:{SEL};color:{ACCENT};}}"
            f"QTreeWidget::item:hover:!selected{{background:rgba(255,255,255,0.04);}}"
            f"QHeaderView::section{{background:{BG2};color:{FG2};border:none;padding:4px 6px;}}"
        )
        self._list.itemDoubleClicked.connect(self._item_double)
        lay.addWidget(self._list, 1)

        # ── Bottom: selected path label + buttons ─────────────────────────
        sel_row = QHBoxLayout()
        self._sel_lbl = QLabel("Nothing selected")
        self._sel_lbl.setStyleSheet(f"color:{FG2}; font-size:8.5pt;")
        self._sel_lbl.setWordWrap(True)
        sel_row.addWidget(self._sel_lbl, 1)
        lay.addLayout(sel_row)

        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Select" if mode == "dir" else "Open")
        ok.setObjectName("run")
        ok.clicked.connect(self._confirm)
        btn_row.addStretch()
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        self._navigate(start_path)

    # ── Internal ──────────────────────────────────────────────────────────

    def _navigate(self, path: str):
        try:
            entries = self._ssh.list_dir(path)
        except Exception as exc:
            QMessageBox.warning(self, "SFTP Error", str(exc))
            return
        self._cur = path
        self._path_edit.setText(path)
        self._list.clear()

        parent = str(Path(path).parent)
        if parent != path:
            up = QTreeWidgetItem(["⬆   ..", ""])
            up.setForeground(0, QColor(ACCENT))
            up.setData(0, Qt.UserRole, ("dir", parent))
            self._list.addTopLevelItem(up)

        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir:
                item = QTreeWidgetItem([f"📁  {e.name}", ""])
                item.setForeground(0, QColor(ORANGE))
            else:
                sz = (f"{e.size/1048576:.1f} MB" if e.size >= 1048576
                      else f"{e.size/1024:.1f} KB")
                icon, col = "📄", FG
                if re.search(r"\.(in|lammps|lmp)$", e.name, re.I): icon, col = "⚙", ACCENT
                elif e.name == "log.lammps" or re.search(r"\.log$", e.name, re.I): icon, col = "📊", GREEN
                elif re.search(r"\.(dat|data)$", e.name, re.I): icon, col = "🗃", YELLOW
                item = QTreeWidgetItem([f"{icon}  {e.name}", sz])
                item.setForeground(0, QColor(col))
            item.setData(0, Qt.UserRole, ("dir" if e.is_dir else "file", e.path))
            self._list.addTopLevelItem(item)

        # In dir mode, selecting the current dir is always valid
        if self._mode == "dir":
            self.selected_path = path
            self._sel_lbl.setText(path)

    def _item_double(self, item):
        kind, path = item.data(0, Qt.UserRole)
        if kind == "dir":
            self._navigate(path)
        elif self._mode == "file":
            self.selected_path = path
            self.accept()

    def _confirm(self):
        items = self._list.selectedItems()
        if items:
            kind, path = items[0].data(0, Qt.UserRole)
            if self._mode == "dir":
                self.selected_path = path if kind == "dir" else self._cur
            else:
                self.selected_path = path
        else:
            self.selected_path = self._cur
        self.accept()


# ── SSH remote runner thread ──────────────────────────────────────────────────

class SSHRemoteRunner(QThread):
    line_ready = pyqtSignal(str)
    finished   = pyqtSignal(int)
    error      = pyqtSignal(str)

    def __init__(self, mgr: "SSHManager", cmd: str, cwd: str):
        super().__init__()
        self._mgr  = mgr
        self._cmd  = cmd
        self._cwd  = cwd
        self._stop = False

    def run(self):
        if not HAS_SSH:
            self.error.emit("ssh_manager not available")
            return
        try:
            self._mgr.exec_stream(
                self._cmd, self._cwd,
                on_line=self.line_ready.emit,
                on_done=self.finished.emit,
            )
        except Exception as exc:
            self.error.emit(str(exc))

    def kill(self):
        self._stop = True
        if HAS_SSH:
            try:
                self._mgr.kill_remote()
            except Exception:
                pass


# ── Main Window ───────────────────────────────────────────────────────────────

class LAMMPSDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAMMPS Dashboard")
        self.resize(1280, 820)

        self._cwd          = os.path.expanduser("~")
        self._current_file = None
        self._runner       = None
        self._log_lines    = 0
        self._thermo_data  = None
        # AI assistant state
        self._ai_streamer  = None
        self._ai_history   = []
        self._ai_partial        = ""
        self._ai_update_pending = False   # batched render flag
        self._dl_timer          = None
        self._pull_thread       = None    # ModelPullThread when active
        # SSH state
        self._ssh                = SSHManager() if HAS_SSH else None
        self._ssh_profiles       : list = load_profiles() if HAS_SSH else []
        self._ssh_remote_cwd     : str  = "~"
        self._remote_mode        : bool = False
        self._current_remote_path: str  = ""
        # HPC / SLURM state
        self._hpc_mode           : bool = False
        self._hpc_jobs           : list = []   # list of submitted job dicts

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_body(), 1)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        self._load_dir(self._cwd)

    # ── Header ────────────────────────────────────────────────────────────
    def _make_header(self):
        hdr = QFrame()
        hdr.setFixedHeight(54)
        hdr.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #181c28, stop:0.5 {BG2}, stop:1 #181c28);"
            f"border-bottom: 1px solid {BORDER};"
        )
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(14, 0, 18, 0)
        lay.setSpacing(0)

        # App icon (small, from make_icon)
        try:
            from make_icon import draw_icon
            icon_lbl = QLabel()
            icon_lbl.setPixmap(draw_icon(32))
            icon_lbl.setFixedSize(32, 32)
            lay.addWidget(icon_lbl)
            lay.addSpacing(10)
        except Exception:
            pass

        # Title
        title = QLabel()
        title.setTextFormat(Qt.RichText)
        title.setText(
            f"<span style='color:{ACCENT};font-size:14pt;font-weight:800;"
            f"letter-spacing:0.5px;'>LAMMPS</span>"
            f"<span style='color:{FG};font-size:14pt;font-weight:400;'> Dashboard</span>"
        )
        lay.addWidget(title)
        lay.addSpacing(18)

        # Status pill badge
        self._status_pill = QLabel("  ●  Idle  ")
        self._status_pill.setStyleSheet(
            f"color:{FG2}; font-size:8.5pt; font-weight:600;"
            f"background:#22263a; border:1px solid #333a55;"
            f"border-radius:10px; padding:2px 6px;"
        )
        lay.addWidget(self._status_pill)

        lay.addStretch()

        # SSH connection badge
        self._ssh_badge = QLabel("  🔗  No SSH  ")
        self._ssh_badge.setStyleSheet(
            f"color:#38415a; font-size:8.5pt; font-weight:600;"
            f"background:#191c26; border:1px solid #252a38;"
            f"border-radius:10px; padding:2px 8px;"
        )
        self._ssh_badge.setCursor(Qt.PointingHandCursor)
        self._ssh_badge.setToolTip("Click to go to SSH tab")
        self._ssh_badge.mousePressEvent = lambda _: self._tabs.setCurrentIndex(3)
        lay.addWidget(self._ssh_badge)
        lay.addSpacing(8)

        # Version badge
        ver = QLabel("v1.0")
        ver.setStyleSheet(
            f"color:#38415a; font-size:8pt; font-weight:700;"
            f"background:#191c26; border:1px solid #252a38;"
            f"border-radius:8px; padding:2px 8px;"
        )
        lay.addWidget(ver)
        return hdr

    # ── Body (sidebar + notebook) ─────────────────────────────────────────
    def _make_body(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._make_sidebar())
        splitter.addWidget(self._make_notebook())
        splitter.setSizes([240, 1040])
        splitter.setHandleWidth(4)
        return splitter

    # ── Sidebar ───────────────────────────────────────────────────────────
    def _make_sidebar(self):
        frame = QFrame()
        frame.setStyleSheet(f"background:{BG2};")
        frame.setMinimumWidth(170)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar row
        tb = QFrame()
        tb.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #212535, stop:1 {BG2});"
            f"border-bottom:1px solid {BORDER};"
        )
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(10, 7, 8, 7)
        lbl = QLabel("EXPLORER")
        lbl.setObjectName("section")
        tl.addWidget(lbl)
        tl.addStretch()
        for icon_txt, tip, cb, col in [
            ("⟳", "Refresh", lambda: self._load_dir(self._cwd), FG2),
            ("+", "New file", self._new_file, ACCENT),
        ]:
            btn = QPushButton(icon_txt)
            btn.setFixedSize(26, 26)
            btn.setToolTip(tip)
            btn.clicked.connect(cb)
            btn.setStyleSheet(
                f"padding:0; font-size:13pt; font-weight:700; color:{col};"
                f"background:transparent; border:none; border-radius:5px;"
            )
            tl.addWidget(btn)
        lay.addWidget(tb)

        # ── Path bar: editable directory input ───────────────────────────
        path_bar = QFrame()
        path_bar.setStyleSheet(
            f"background:{BG2}; border-bottom:1px solid {BORDER};"
        )
        pb_lay = QHBoxLayout(path_bar)
        pb_lay.setContentsMargins(6, 5, 6, 5)
        pb_lay.setSpacing(3)

        # Drive / path icon
        path_icon = QLabel("📂")
        path_icon.setFixedWidth(18)
        path_icon.setStyleSheet("background:transparent; font-size:10pt;")
        pb_lay.addWidget(path_icon)

        # Editable path field — also serves as self._cwd_lbl for compat
        self._cwd_lbl = QLineEdit(self._cwd)
        self._cwd_lbl.setStyleSheet(
            f"background:{BG3}; color:{ACCENT}; border:1px solid {BORDER};"
            f"border-radius:4px; padding:2px 6px; font-size:8pt; font-weight:600;"
        )
        self._cwd_lbl.setToolTip("Type a path and press Enter  (or click ➜)")
        self._cwd_lbl.returnPressed.connect(self._path_bar_navigate)
        self._cwd_lbl.setPlaceholderText("Type path…")
        pb_lay.addWidget(self._cwd_lbl, 1)

        # Go button
        go_btn = QPushButton("➜")
        go_btn.setFixedSize(26, 26)
        go_btn.setToolTip("Navigate to typed path")
        go_btn.clicked.connect(self._path_bar_navigate)
        go_btn.setStyleSheet(
            f"color:{ACCENT}; background:#1a2535; border:1px solid #284870;"
            f"border-radius:4px; font-size:11pt; padding:0;"
        )
        pb_lay.addWidget(go_btn)

        # Browse button
        browse_btn = QPushButton("…")
        browse_btn.setFixedSize(26, 26)
        browse_btn.setToolTip("Browse for directory")
        browse_btn.clicked.connect(self._change_dir)
        browse_btn.setStyleSheet(
            f"color:{FG2}; background:transparent; border:1px solid {BORDER};"
            f"border-radius:4px; font-size:10pt; font-weight:700; padding:0;"
        )
        pb_lay.addWidget(browse_btn)

        lay.addWidget(path_bar)

        # File tree
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemDoubleClicked.connect(self._tree_open)
        self._tree.setStyleSheet(
            f"QTreeWidget {{ background:{BG2}; border:none; outline:none; }}"
            f"QTreeWidget::item {{ padding:4px 8px; border-radius:4px; min-height:24px; }}"
            f"QTreeWidget::item:selected {{ background:{SEL}; color:{ACCENT}; }}"
            f"QTreeWidget::item:hover:!selected {{ background:rgba(255,255,255,0.04); }}"
        )
        lay.addWidget(self._tree, 1)

        # Footer hint
        hint = QLabel("  ↩ double-click to open")
        hint.setStyleSheet(
            f"color:#303848; font-size:7pt; font-style:italic;"
            f"padding:5px 10px; background:{BG2};"
            f"border-top:1px solid {BORDER};"
        )
        lay.addWidget(hint)
        return frame

    # ── Notebook ──────────────────────────────────────────────────────────
    def _make_notebook(self):
        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_editor_tab(),  "  ✎  Editor  ")
        self._tabs.addTab(self._make_run_tab(),     "  ▶  Run & Monitor  ")
        self._tabs.addTab(self._make_plots_tab(),   "  📈  Thermo Plots  ")
        self._tabs.addTab(self._make_ssh_tab(),     "  🔗  SSH  ")
        self._tabs.addTab(self._make_hpc_tab(),     "  ⚡  HPC Jobs  ")
        self._tabs.addTab(self._make_ai_tab(),      "  🤖  AI Assistant  ")
        return self._tabs

    # ── Editor Tab ────────────────────────────────────────────────────────
    def _make_editor_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar
        tb = QFrame()
        tb.setStyleSheet(f"background:{BG2}; border-bottom:1px solid {BORDER};")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(4)

        for text, tip, cb in [
            ("New",        "New file",          self._editor_new),
            ("Open…",      "Open file",         self._editor_open),
            ("Save",       "Save  Ctrl+S",       self._editor_save),
            ("Save As…",   "Save as new file",  self._editor_save_as),
        ]:
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(cb)
            tl.addWidget(btn)

        tl.addWidget(_vline())

        use_btn = QPushButton("▶  Use as Input")
        use_btn.setToolTip("Set this file as the Run tab input")
        use_btn.setObjectName("run")
        use_btn.clicked.connect(self._use_as_input)
        tl.addWidget(use_btn)

        tl.addStretch()
        self._editor_info = QLabel("No file open")
        self._editor_info.setStyleSheet(f"color:{FG2}; font-size:9pt;")
        tl.addWidget(self._editor_info)
        lay.addWidget(tb)

        # Editor
        self._editor = QPlainTextEdit()
        font = QFont(MONO_FONT, 11)
        font.setFixedPitch(True)
        self._editor.setFont(font)
        self._editor.setStyleSheet(f"background:{BG_EDIT}; color:{FG}; border:none;"
                                    f"selection-background-color:{SEL};")
        self._editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._hl = LammpsHighlighter(self._editor.document())

        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        QShortcut(QKeySequence("Ctrl+S"), self._editor, self._editor_save)

        lay.addWidget(self._editor, 1)
        return w

    # ── Run Tab ───────────────────────────────────────────────────────────
    def _make_run_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Controls panel
        ctrl = QFrame()
        ctrl.setStyleSheet(f"background:{BG2}; border-bottom:1px solid {BORDER};")
        ctrl_lay = QVBoxLayout(ctrl)
        ctrl_lay.setContentsMargins(14, 10, 14, 10)
        ctrl_lay.setSpacing(6)

        grid = QWidget()
        gl = QGridLayout(grid)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(6)

        def add_row(label, widget, row, col=0, browse_cb=None):
            lbl = QLabel(label)
            lbl.setObjectName("section")
            gl.addWidget(lbl, row * 2, col)
            gl.addWidget(widget, row * 2 + 1, col)
            if browse_cb:
                btn = QPushButton("Browse…")
                btn.setFixedWidth(70)
                btn.clicked.connect(browse_cb)
                inner = QHBoxLayout()
                inner.setContentsMargins(0, 0, 0, 0)
                inner.setSpacing(4)
                inner.addWidget(widget, 1)
                inner.addWidget(btn)
                container = QWidget()
                container.setLayout(inner)
                gl.addWidget(lbl, row * 2, col)
                gl.addWidget(container, row * 2 + 1, col)

        self._inp_file    = QLineEdit()
        self._inp_file.setPlaceholderText("e.g.  in.melt")
        self._inp_workdir = QLineEdit(self._cwd)
        self._inp_np      = QSpinBox(); self._inp_np.setRange(1, 1024); self._inp_np.setValue(4)
        self._inp_bin     = QLineEdit("lmp")
        self._inp_extra   = QLineEdit()
        self._inp_extra.setPlaceholderText("e.g.  -var T 300  -suffix gpu")

        add_row("Input File",           self._inp_file,    0, 0, self._browse_input)
        add_row("Working Directory",    self._inp_workdir, 0, 1, self._browse_workdir)
        add_row("MPI Processes  (–np)", self._inp_np,      1, 0)

        # Binary row with Detect button
        bin_lbl = QLabel("LAMMPS Binary")
        bin_lbl.setObjectName("section")
        gl.addWidget(bin_lbl, 2, 1)
        bin_inner = QWidget(); bin_inner.setStyleSheet("background:transparent;")
        bi_lay = QHBoxLayout(bin_inner)
        bi_lay.setContentsMargins(0, 0, 0, 0); bi_lay.setSpacing(4)
        bi_lay.addWidget(self._inp_bin, 1)
        detect_btn = QPushButton("Detect")
        detect_btn.setFixedWidth(58)
        detect_btn.setToolTip("Find lmp binary (local or remote)")
        detect_btn.clicked.connect(self._detect_binary)
        bi_lay.addWidget(detect_btn)
        gl.addWidget(bin_inner, 3, 1)

        gl.addWidget(QLabel("Extra Arguments"), 4, 0, 1, 2)
        gl.addWidget(self._inp_extra, 5, 0, 1, 2)
        gl.setColumnStretch(0, 1)
        gl.setColumnStretch(1, 2)
        ctrl_lay.addWidget(grid)

        # Run-target indicator (updates when SSH connects/disconnects)
        self._run_target_bar = QFrame()
        self._run_target_bar.setFixedHeight(28)
        self._run_target_bar.setStyleSheet(
            f"background:#131620; border-bottom:1px solid {BORDER};"
        )
        rt_lay = QHBoxLayout(self._run_target_bar)
        rt_lay.setContentsMargins(12, 0, 12, 0)
        rt_lay.setSpacing(8)
        self._run_target_lbl = QLabel("▶  Run target:  💻  Local machine")
        self._run_target_lbl.setStyleSheet(f"color:{FG2}; font-size:8.5pt;")
        rt_lay.addWidget(self._run_target_lbl)
        rt_lay.addStretch()
        ctrl_lay.addWidget(self._run_target_bar)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_run = QPushButton("▶   Run Simulation")
        self._btn_run.setObjectName("run")
        self._btn_run.clicked.connect(self._start_sim)
        self._btn_run.setToolTip("Run locally (or on SSH if connected)")

        self._btn_run_ssh = QPushButton("🔗  Run on SSH")  # kept for compat but hidden
        self._btn_run_ssh.setObjectName("save")
        self._btn_run_ssh.setVisible(False)
        self._btn_run_ssh.clicked.connect(self._start_remote_sim)

        self._btn_stop = QPushButton("■   Stop")
        self._btn_stop.setObjectName("stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._stop_sim)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self._clear_log)

        self._run_info_lbl = QLabel()
        self._run_info_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt;")

        self._autoscroll_chk = QCheckBox("Auto-scroll")
        self._autoscroll_chk.setChecked(True)
        self._autoscroll_chk.setStyleSheet(f"color:{FG2};")

        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_run_ssh)
        btn_row.addWidget(self._btn_stop)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(self._run_info_lbl)
        btn_row.addStretch()
        btn_row.addWidget(self._autoscroll_chk)
        ctrl_lay.addLayout(btn_row)
        lay.addWidget(ctrl)

        # Log terminal
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        log_font = QFont(MONO_FONT, 10)
        log_font.setFixedPitch(True)
        self._log.setFont(log_font)
        self._log.setStyleSheet(f"background:{BG3}; color:{FG}; border:none;"
                                 f"selection-background-color:{SEL};")
        self._log.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self._log, 1)

        # Log status bar
        log_sb = QFrame()
        log_sb.setFixedHeight(22)
        log_sb.setStyleSheet(f"background:{BG2}; border-top:1px solid {BORDER};")
        lsb_lay = QHBoxLayout(log_sb)
        lsb_lay.setContentsMargins(8, 0, 8, 0)
        self._log_count_lbl = QLabel("0 lines")
        self._log_count_lbl.setStyleSheet(f"color:{FG2}; font-size:8pt;")
        lsb_lay.addWidget(self._log_count_lbl)
        lsb_lay.addStretch()
        lay.addWidget(log_sb)

        return w

    # ── Plots Tab ─────────────────────────────────────────────────────────
    def _make_plots_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Controls
        ctrl = QFrame()
        ctrl.setStyleSheet(f"background:{BG2}; border-bottom:1px solid {BORDER};")
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(8)

        cl.addWidget(QLabel("Log file:", styleSheet=f"color:{FG2}; font-size:9pt;"))
        self._plot_log_path = QLineEdit()
        self._plot_log_path.setPlaceholderText("path to log.lammps")
        cl.addWidget(self._plot_log_path, 1)

        browse_log = QPushButton("Browse…")
        browse_log.clicked.connect(self._browse_log)
        cl.addWidget(browse_log)

        load_btn = QPushButton("Load & Plot")
        load_btn.setObjectName("save")
        load_btn.clicked.connect(lambda: self._load_and_plot(self._plot_log_path.text()))
        cl.addWidget(load_btn)
        lay.addWidget(ctrl)

        # Column checkboxes frame
        self._col_scroll = QScrollArea()
        self._col_scroll.setWidgetResizable(True)
        self._col_scroll.setFixedHeight(46)
        self._col_scroll.setStyleSheet(f"background:{BG2}; border:none;"
                                        f"border-bottom:1px solid {BORDER};")
        self._col_widget = QWidget()
        self._col_widget.setStyleSheet(f"background:{BG2};")
        self._col_layout = QHBoxLayout(self._col_widget)
        self._col_layout.setContentsMargins(10, 4, 10, 4)
        self._col_layout.setSpacing(12)
        self._col_layout.addStretch()
        self._col_scroll.setWidget(self._col_widget)
        lay.addWidget(self._col_scroll)

        if not HAS_MPL:
            lbl = QLabel("matplotlib not installed.\nRun:  pip3 install matplotlib")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color:{FG2}; font-size:11pt;")
            lay.addWidget(lbl, 1)
        else:
            self._fig = Figure(facecolor="#1a1d21")
            self._canvas = FigureCanvas(self._fig)
            self._canvas.setStyleSheet("background:#1a1d21;")

            nav = NavToolbar(self._canvas, w)
            nav.setStyleSheet(f"background:{BG2}; color:{FG}; border-top:1px solid {BORDER};")
            lay.addWidget(self._canvas, 1)
            lay.addWidget(nav)

            ax = self._fig.add_subplot(111)
            ax.set_facecolor("#1a1d21")
            ax.text(0.5, 0.5, "Run a simulation or load a log file\nto see thermo plots.",
                    transform=ax.transAxes, ha="center", va="center",
                    color="#4a5568", fontsize=13)
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values(): sp.set_color(BORDER)

        return w

    # ── File Browser ──────────────────────────────────────────────────────
    def _load_dir(self, path):
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return
        self._cwd = path
        self._cwd_lbl.setText(path)
        self._tree.clear()

        parent = str(Path(path).parent)
        if parent != path:
            up = QTreeWidgetItem(["⬆  .."])
            up.setForeground(0, QColor(ACCENT))
            up.setData(0, Qt.UserRole, ("dir", parent))
            self._tree.addTopLevelItem(up)

        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
            for e in entries:
                if e.name.startswith("."):
                    continue
                if e.is_dir():
                    item = QTreeWidgetItem([f"📁  {e.name}"])
                    item.setForeground(0, QColor(ORANGE))
                    item.setData(0, Qt.UserRole, ("dir", e.path))
                else:
                    icon, color = "📄", FG
                    if re.search(r"\.(in|lammps|lmp)$", e.name, re.I):
                        icon, color = "⚙ ", ACCENT
                    elif e.name == "log.lammps" or re.search(r"\.log$", e.name, re.I):
                        icon, color = "📊", GREEN
                    elif re.search(r"\.(dat|data)$", e.name, re.I):
                        icon, color = "🗃", YELLOW
                    item = QTreeWidgetItem([f"{icon}  {e.name}"])
                    item.setForeground(0, QColor(color))
                    item.setData(0, Qt.UserRole, ("file", e.path))
                self._tree.addTopLevelItem(item)
        except PermissionError:
            pass

    def _tree_open(self, item):
        kind, path = item.data(0, Qt.UserRole)
        if kind == "dir":
            self._load_dir(path)
        elif kind == "remote_dir":
            self._load_remote_dir(path)
        elif kind == "remote_file":
            self._open_remote_file(path)
        else:
            self._open_file(path)

    def _path_bar_navigate(self):
        """Navigate to whatever is typed in the path bar."""
        raw = self._cwd_lbl.text().strip()
        if not raw:
            return

        # Strip the "🖥  host: /path" display prefix set by _load_remote_dir
        m = re.match(r'^🖥\s+[^:]+:\s*(.+)$', raw)
        if m:
            raw = m.group(1).strip()

        # If SSH is connected, always route to remote — regardless of _remote_mode flag
        if self._ssh and self._ssh.connected:
            self._remote_mode = True
            self._load_remote_dir(raw)
            return

        # Local navigation
        path = os.path.expanduser(raw)
        if os.path.isdir(path):
            self._load_dir(path)
        elif os.path.isfile(path):
            self._open_file(path)
        else:
            orig = self._cwd_lbl.styleSheet()
            self._cwd_lbl.setStyleSheet(
                f"background:{BG3}; color:{RED}; border:1px solid {RED}55;"
                f"border-radius:4px; padding:2px 6px; font-size:8pt; font-weight:600;"
            )
            QTimer.singleShot(1400, lambda: self._cwd_lbl.setStyleSheet(orig))

    def _change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose Directory", self._cwd)
        if d:
            self._load_dir(d)

    def _new_file(self):
        name, ok = QInputDialog.getText(self, "New File", "File name:", text="in.lammps")
        if not ok or not name:
            return
        path = os.path.join(self._cwd, name)
        if os.path.exists(path):
            QMessageBox.warning(self, "Exists", "File already exists.")
            return
        open(path, "w").close()
        self._load_dir(self._cwd)
        self._open_file(path)

    # ── Editor ────────────────────────────────────────────────────────────
    def _open_file(self, path):
        try:
            with open(path, "r", errors="replace") as f:
                content = f.read()
            self._editor.setPlainText(content)
            self._current_file = path
            self._editor_info.setText(f"  {os.path.basename(path)}")
            self._tabs.setCurrentIndex(0)
            self._status_bar.showMessage(f"Opened: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _editor_new(self):
        self._editor.setPlainText(
            "# LAMMPS Input Script\nunits metal\natom_style atomic\n\n"
        )
        self._current_file = None
        self._editor_info.setText("Unsaved file")

    def _editor_open(self):
        if self._is_remote():
            path = self._sftp_pick_file("Open Remote File")
            if path:
                self._open_remote_file(path)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open File", self._cwd,
                "LAMMPS Input (*.in *.lammps *.lmp);;Data Files (*.dat *.data);;All Files (*)"
            )
            if path:
                self._open_file(path)

    def _editor_save(self):
        # Remote file: save back to server via SFTP
        if not self._current_file and hasattr(self, "_current_remote_path") and self._current_remote_path:
            self._ssh_save_remote(self._current_remote_path)
            return
        if not self._current_file:
            self._editor_save_as()
            return
        self._do_save(self._current_file)

    def _editor_save_as(self):
        if self._is_remote():
            # Ask for remote path via simple input dialog
            default = (self._current_remote_path
                       or (self._ssh_remote_cwd + "/in.lammps"))
            path, ok = QInputDialog.getText(
                self, "Save to Remote", "Remote file path:", text=default)
            if ok and path.strip():
                self._ssh_save_remote(path.strip())
                self._current_remote_path = path.strip()
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save As", self._cwd,
                "LAMMPS Input (*.in *.lammps);;All Files (*)"
            )
            if path:
                self._do_save(path)

    def _do_save(self, path):
        try:
            with open(path, "w") as f:
                f.write(self._editor.toPlainText())
            self._current_file = path
            self._editor_info.setText(f"  Saved: {os.path.basename(path)}")
            self._load_dir(self._cwd)
            self._status_bar.showMessage(f"Saved: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _use_as_input(self):
        if not self._current_file:
            QMessageBox.warning(self, "No File", "Save the file first.")
            return
        self._inp_file.setText(os.path.basename(self._current_file))
        self._inp_workdir.setText(os.path.dirname(self._current_file))
        self._tabs.setCurrentIndex(1)

    # ── Simulation ────────────────────────────────────────────────────────
    def _start_sim(self):
        # Auto-route: if SSH connected, run on the server
        if self._is_remote():
            self._start_remote_sim()
            return

        inp  = self._inp_file.text().strip()
        if not inp:
            QMessageBox.warning(self, "No Input", "Enter an input file name.")
            return
        np_   = self._inp_np.value()
        wd    = os.path.expanduser(self._inp_workdir.text().strip() or self._cwd)
        bin_  = self._inp_bin.text().strip() or "lmp"
        extra = self._inp_extra.text().strip()

        cmd = f"mpirun -np {np_} {bin_} -in {inp}"
        if extra:
            cmd += f" {extra}"

        self._append_log(f"\n▶ {cmd}", ACCENT)
        self._append_log(f"  dir: {wd}\n", FG2)

        self._runner = SimRunner(cmd, wd)
        self._runner.line_ready.connect(self._on_log_line)
        self._runner.finished.connect(self._on_sim_done)
        self._runner.error.connect(lambda msg: self._append_log(f"[ERROR] {msg}", RED))
        self._runner.start()

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._set_status("● Running", GREEN)
        self._run_info_lbl.setText(f"np={np_}  |  {inp}")
        self._status_bar.showMessage(f"Running: {cmd}")

    def _detect_binary(self):
        """Find lmp binary — on remote if SSH connected, else local."""
        if self._is_remote():
            try:
                _, out, _ = self._ssh._client.exec_command(
                    "which lmp lmp_mpi lmp_serial lammps 2>/dev/null | head -1"
                )
                found = out.read().decode().strip()
            except Exception as exc:
                found = ""
                self._status_bar.showMessage(f"Binary detect failed: {exc}")
        else:
            import shutil
            found = ""
            for name in ("lmp", "lmp_mpi", "lmp_serial", "lammps"):
                p = shutil.which(name)
                if p:
                    found = p
                    break

        if found:
            self._inp_bin.setText(found)
            self._status_bar.showMessage(f"Found: {found}")
        else:
            self._status_bar.showMessage("lmp binary not found — set manually")

    def _stop_sim(self):
        if self._runner:
            self._runner.kill()
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._set_status("● Stopped", YELLOW)
        self._append_log("\n[STOPPED by user]", YELLOW)
        self._status_bar.showMessage("Simulation stopped")

    def _on_log_line(self, line):
        color = FG
        if re.search(r"WARNING", line, re.I): color = YELLOW
        elif re.search(r"ERROR|FATAL", line, re.I): color = RED
        elif re.match(r"\s*\d+\s+[\d\.\-e]+", line): color = GREEN
        self._append_log(line, color)

    def _on_sim_done(self, rc):
        self._btn_run.setEnabled(True)
        self._btn_stop.setEnabled(False)
        color = GREEN if rc == 0 else RED
        self._set_status(f"● Done  (rc={rc})", color)
        self._append_log(f"\n[DONE]  Exit code: {rc}", color)
        self._status_bar.showMessage(f"Simulation finished  |  Exit code: {rc}")

        wd = self._inp_workdir.text().strip()
        if self._is_remote():
            # Download log.lammps from remote for thermo plotting
            remote_log = wd.rstrip("/") + "/log.lammps"
            local_log  = os.path.join("/tmp", "remote_log.lammps")
            try:
                self._ssh.download(remote_log, local_log)
                self._plot_log_path.setText(local_log)
                self._load_and_plot(local_log)
            except Exception:
                pass  # log might not exist yet
        else:
            wd = os.path.expanduser(wd or self._cwd)
            log_path = os.path.join(wd, "log.lammps")
            if os.path.exists(log_path):
                self._plot_log_path.setText(log_path)
                self._load_and_plot(log_path)

    def _append_log(self, text, color=FG):
        cur = self._log.textCursor()
        from PyQt5.QtGui import QTextCursor
        cur.movePosition(QTextCursor.End)
        self._log.setTextCursor(cur)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(text + "\n", fmt)

        self._log_lines += 1
        self._log_count_lbl.setText(f"{self._log_lines} lines")

        if self._autoscroll_chk.isChecked():
            self._log.ensureCursorVisible()

    def _clear_log(self):
        self._log.clear()
        self._log_lines = 0
        self._log_count_lbl.setText("0 lines")

    # ── Thermo Plots ──────────────────────────────────────────────────────
    def _browse_input(self):
        if self._is_remote():
            path = self._sftp_pick_file("Select Remote Input File")
            if path:
                self._inp_file.setText(os.path.basename(path))
                self._inp_workdir.setText(os.path.dirname(path))
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Input File", self._inp_workdir.text() or self._cwd,
                "LAMMPS Input (*.in *.lammps *.lmp);;All Files (*)"
            )
            if path:
                self._inp_file.setText(os.path.basename(path))
                self._inp_workdir.setText(os.path.dirname(path))

    def _browse_workdir(self):
        if self._is_remote():
            d = self._sftp_pick_dir("Select Remote Working Directory")
            if d:
                self._inp_workdir.setText(d)
        else:
            d = QFileDialog.getExistingDirectory(self, "Working Directory", self._cwd)
            if d:
                self._inp_workdir.setText(d)

    def _browse_log(self):
        if self._is_remote():
            path = self._sftp_pick_file("Select Remote Log File")
            if path:
                self._plot_log_path.setText(path)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Log File", self._cwd,
                "LAMMPS Log (log.lammps *.log);;All Files (*)"
            )
            if path:
                self._plot_log_path.setText(path)

    def _load_and_plot(self, log_path):
        if not HAS_MPL:
            return
        if not log_path or not os.path.exists(log_path):
            QMessageBox.warning(self, "Not Found", f"Log file not found:\n{log_path}")
            return

        thermo = self._parse_thermo(log_path)
        if not thermo["headers"]:
            QMessageBox.information(self, "No Data", "No thermo data found in log file.")
            return

        self._thermo_data = thermo
        self._build_col_checkboxes(thermo["headers"])
        self._render_plots()
        self._tabs.setCurrentIndex(2)

    def _build_col_checkboxes(self, headers):
        # Clear old
        while self._col_layout.count():
            item = self._col_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._col_vars = {}
        skip = {"Step"}
        lbl = QLabel("Columns:")
        lbl.setStyleSheet(f"color:{FG2}; font-size:8pt; font-weight:bold;")
        self._col_layout.addWidget(lbl)

        COLORS = [ACCENT, GREEN, YELLOW, RED, "#b39ddb", "#80cbc4", "#fff176"]
        for i, h in enumerate(headers):
            if h in skip:
                continue
            chk = QCheckBox(h)
            chk.setChecked(True)
            chk.setStyleSheet(f"color:{COLORS[i % len(COLORS)]}; font-size:9pt;")
            chk.toggled.connect(lambda _: self._render_plots())
            self._col_vars[h] = chk
            self._col_layout.addWidget(chk)

        self._col_layout.addStretch()

    def _render_plots(self):
        if not HAS_MPL or not self._thermo_data:
            return
        cols = [h for h, chk in self._col_vars.items() if chk.isChecked()]
        if not cols:
            return

        self._fig.clear()
        xs = self._thermo_data["data"].get("Step", [])
        n = len(cols)
        ncols = min(n, 2)
        nrows = (n + ncols - 1) // ncols

        COLORS = [ACCENT, GREEN, YELLOW, RED, "#b39ddb", "#80cbc4", "#fff176", "#ef9a9a"]
        self._fig.patch.set_facecolor("#1a1d21")

        for i, col in enumerate(cols):
            ax = self._fig.add_subplot(nrows, ncols, i + 1)
            ax.set_facecolor("#1a1d21")
            ys = self._thermo_data["data"].get(col, [])
            ax.plot(xs, ys, color=COLORS[i % len(COLORS)], linewidth=1.3)
            ax.set_title(col, color=FG, fontsize=9, pad=4)
            ax.set_xlabel("Step", color=FG2, fontsize=8)
            ax.tick_params(colors=FG2, labelsize=8)
            ax.grid(True, color=BORDER, alpha=0.6, linewidth=0.5)
            for sp in ax.spines.values():
                sp.set_color(BORDER)

        self._fig.tight_layout(pad=1.5)
        self._canvas.draw()

    @staticmethod
    def _parse_thermo(log_path):
        headers, data = [], {}
        cur_headers = []
        in_thermo = False
        with open(log_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if re.match(r"^Step\b", line):
                    cur_headers = line.split()
                    in_thermo = True
                    if not headers:
                        headers = cur_headers
                        data = {h: [] for h in headers}
                    continue
                if in_thermo:
                    if not line or line.startswith("Loop time") or line.startswith("ERROR"):
                        if not line:
                            continue
                        in_thermo = False
                        continue
                    try:
                        vals = [float(v) for v in line.split()]
                        if len(vals) == len(cur_headers):
                            for h, v in zip(cur_headers, vals):
                                if h in data:
                                    data[h].append(v)
                    except ValueError:
                        in_thermo = False
        return {"headers": headers, "data": data}

    # ══════════════════════════════════════════════════════════════════════
    # SSH Tab
    # ══════════════════════════════════════════════════════════════════════

    def _make_ssh_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if not HAS_SSH:
            lbl = QLabel("paramiko not installed.\nRun:  pip3 install paramiko")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"color:{FG2}; font-size:11pt;")
            root.addWidget(lbl)
            return w

        # ── Status bar at top ─────────────────────────────────────────────
        status_bar = QFrame()
        status_bar.setFixedHeight(40)
        status_bar.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #181c28, stop:1 {BG2}); border-bottom:1px solid {BORDER};"
        )
        sb_lay = QHBoxLayout(status_bar)
        sb_lay.setContentsMargins(14, 0, 14, 0)

        self._ssh_status_lbl = QLabel("🔗  Not connected")
        self._ssh_status_lbl.setStyleSheet(f"color:{FG2}; font-size:9.5pt; font-weight:600;")
        sb_lay.addWidget(self._ssh_status_lbl)
        sb_lay.addStretch()

        self._ssh_disconnect_btn = QPushButton("Disconnect")
        self._ssh_disconnect_btn.setEnabled(False)
        self._ssh_disconnect_btn.clicked.connect(self._ssh_do_disconnect)
        sb_lay.addWidget(self._ssh_disconnect_btn)

        remote_browse_btn = QPushButton("📁  Browse Remote")
        remote_browse_btn.setToolTip("Show remote files in the sidebar")
        remote_browse_btn.clicked.connect(self._ssh_browse_remote)
        sb_lay.addWidget(remote_browse_btn)
        root.addWidget(status_bar)

        # ── Main split: profiles list (left) | form (right) ──────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        # ── Left: saved profiles ──────────────────────────────────────────
        left = QFrame()
        left.setStyleSheet(f"background:{BG2};")
        left.setMinimumWidth(190)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        prof_hdr = QFrame()
        prof_hdr.setStyleSheet(
            f"background:#212535; border-bottom:1px solid {BORDER};"
        )
        ph_lay = QHBoxLayout(prof_hdr)
        ph_lay.setContentsMargins(10, 7, 8, 7)
        ph_lbl = QLabel("SAVED PROFILES")
        ph_lbl.setObjectName("section")
        ph_lay.addWidget(ph_lbl)
        ph_lay.addStretch()
        for icon_t, tip, cb in [
            ("+", "Add profile",    self._ssh_add_profile),
            ("✕", "Delete profile", self._ssh_del_profile),
        ]:
            b = QPushButton(icon_t)
            b.setFixedSize(26, 26)
            b.setToolTip(tip)
            b.clicked.connect(cb)
            b.setStyleSheet("padding:0; font-size:12pt; background:transparent; border:none;")
            ph_lay.addWidget(b)
        ll.addWidget(prof_hdr)

        self._ssh_profile_list = QTreeWidget()
        self._ssh_profile_list.setHeaderHidden(True)
        self._ssh_profile_list.setIndentation(0)
        self._ssh_profile_list.setStyleSheet(
            f"QTreeWidget{{background:{BG2};border:none;outline:none;}}"
            f"QTreeWidget::item{{padding:8px 10px; min-height:28px;}}"
            f"QTreeWidget::item:selected{{background:{SEL};color:{ACCENT};}}"
            f"QTreeWidget::item:hover:!selected{{background:rgba(255,255,255,0.04);}}"
        )
        self._ssh_profile_list.itemClicked.connect(self._ssh_profile_selected)
        ll.addWidget(self._ssh_profile_list, 1)

        # Quick-connect button
        conn_btn = QPushButton("  ▶  Connect to Selected")
        conn_btn.setObjectName("run")
        conn_btn.clicked.connect(self._ssh_connect_selected)
        ll.addWidget(conn_btn)

        splitter.addWidget(left)

        # ── Right: connection form ────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{BG};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(20, 16, 20, 16)
        rl.setSpacing(10)

        form_title = QLabel("Connection Details")
        form_title.setStyleSheet(
            f"color:{FG}; font-size:12pt; font-weight:700; margin-bottom:4px;"
        )
        rl.addWidget(form_title)

        def _row(label: str, widget):
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label)
            lbl.setFixedWidth(110)
            lbl.setStyleSheet(f"color:{FG2}; font-size:9pt; font-weight:600;")
            hl.addWidget(lbl)
            hl.addWidget(widget, 1)
            rl.addWidget(row)

        self._f_name = QLineEdit(); self._f_name.setPlaceholderText("My HPC Cluster")
        self._f_host = QLineEdit(); self._f_host.setPlaceholderText("login.cluster.edu  or  192.168.1.x")
        self._f_port = QSpinBox();  self._f_port.setRange(1, 65535); self._f_port.setValue(22)
        self._f_user = QLineEdit(); self._f_user.setPlaceholderText("username")

        _row("Profile name:", self._f_name)
        _row("Host / IP:",    self._f_host)
        _row("Port:",         self._f_port)
        _row("Username:",     self._f_user)

        # Auth selector
        auth_row = QWidget()
        auth_row.setStyleSheet("background:transparent;")
        ar_lay = QHBoxLayout(auth_row)
        ar_lay.setContentsMargins(0, 0, 0, 0)
        auth_lbl = QLabel("Auth method:")
        auth_lbl.setFixedWidth(110)
        auth_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt; font-weight:600;")
        ar_lay.addWidget(auth_lbl)
        self._f_auth_pass = QCheckBox("Password")
        self._f_auth_key  = QCheckBox("SSH Key")
        self._f_auth_pass.setChecked(True)
        self._f_auth_pass.toggled.connect(self._ssh_auth_toggled)
        self._f_auth_key.toggled.connect(lambda c: self._f_auth_pass.setChecked(not c))
        ar_lay.addWidget(self._f_auth_pass)
        ar_lay.addWidget(self._f_auth_key)
        ar_lay.addStretch()
        rl.addWidget(auth_row)

        # Password field
        self._f_pass = QLineEdit()
        self._f_pass.setPlaceholderText("Password (not saved to disk)")
        self._f_pass.setEchoMode(QLineEdit.Password)
        _row("Password:", self._f_pass)

        # Key file
        self._f_key_row = QWidget()
        self._f_key_row.setStyleSheet("background:transparent;")
        kr_lay = QHBoxLayout(self._f_key_row)
        kr_lay.setContentsMargins(0, 0, 0, 0)
        key_lbl = QLabel("Private key:")
        key_lbl.setFixedWidth(110)
        key_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt; font-weight:600;")
        self._f_key = QLineEdit()
        self._f_key.setPlaceholderText("~/.ssh/id_rsa")
        browse_key = QPushButton("Browse…")
        browse_key.setFixedWidth(75)
        browse_key.clicked.connect(self._browse_key_file)
        kr_lay.addWidget(key_lbl)
        kr_lay.addWidget(self._f_key, 1)
        kr_lay.addWidget(browse_key)
        self._f_key_row.setVisible(False)
        rl.addWidget(self._f_key_row)

        # Buttons row
        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾  Save Profile")
        save_btn.setObjectName("save")
        save_btn.clicked.connect(self._ssh_save_profile)
        test_btn = QPushButton("🔌  Test Connection")
        test_btn.clicked.connect(self._ssh_test)
        conn_btn2 = QPushButton("▶  Connect")
        conn_btn2.setObjectName("run")
        conn_btn2.clicked.connect(self._ssh_connect_form)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()
        btn_row.addWidget(conn_btn2)
        rl.addLayout(btn_row)

        # Result label
        self._ssh_result_lbl = QLabel()
        self._ssh_result_lbl.setWordWrap(True)
        self._ssh_result_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt; margin-top:6px;")
        rl.addWidget(self._ssh_result_lbl)
        rl.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([220, 700])
        root.addWidget(splitter, 1)

        self._ssh_refresh_profile_list()
        return w

    # ── SSH helpers ───────────────────────────────────────────────────────

    def _ssh_auth_toggled(self, checked: bool):
        self._f_auth_key.setChecked(not checked)
        self._f_pass.parentWidget().setVisible(checked)
        self._f_key_row.setVisible(not checked)

    def _browse_key_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Private Key", os.path.expanduser("~/.ssh"), "All Files (*)"
        )
        if path:
            self._f_key.setText(path)

    def _ssh_refresh_profile_list(self):
        self._ssh_profile_list.clear()
        for p in self._ssh_profiles:
            item = QTreeWidgetItem([f"  🖥  {p.name}\n     {p.username}@{p.host}:{p.port}"])
            item.setData(0, Qt.UserRole, p)
            item.setForeground(0, QColor(FG))
            self._ssh_profile_list.addTopLevelItem(item)

    def _ssh_profile_selected(self, item):
        p: SSHProfile = item.data(0, Qt.UserRole)
        self._f_name.setText(p.name)
        self._f_host.setText(p.host)
        self._f_port.setValue(p.port)
        self._f_user.setText(p.username)
        if p.auth == "key":
            self._f_auth_key.setChecked(True)
            self._f_key.setText(p.key_path)
        else:
            self._f_auth_pass.setChecked(True)

    def _ssh_add_profile(self):
        self._f_name.setText("New Server")
        self._f_host.clear(); self._f_user.clear(); self._f_port.setValue(22)
        self._f_auth_pass.setChecked(True)

    def _ssh_del_profile(self):
        items = self._ssh_profile_list.selectedItems()
        if not items:
            return
        p: SSHProfile = items[0].data(0, Qt.UserRole)
        ans = QMessageBox.question(self, "Delete", f"Delete profile '{p.name}'?")
        if ans == QMessageBox.Yes:
            self._ssh_profiles = [x for x in self._ssh_profiles if x is not p]
            save_profiles(self._ssh_profiles)
            self._ssh_refresh_profile_list()

    def _ssh_save_profile(self):
        name = self._f_name.text().strip() or "Unnamed"
        # Update existing or create new
        existing = next((p for p in self._ssh_profiles if p.name == name), None)
        if existing:
            p = existing
        else:
            p = SSHProfile()
            self._ssh_profiles.append(p)
        p.name     = name
        p.host     = self._f_host.text().strip()
        p.port     = self._f_port.value()
        p.username = self._f_user.text().strip()
        p.auth     = "key" if self._f_auth_key.isChecked() else "password"
        p.key_path = self._f_key.text().strip()
        save_profiles(self._ssh_profiles)
        self._ssh_refresh_profile_list()
        self._ssh_result_lbl.setStyleSheet(f"color:{GREEN}; font-size:9pt;")
        self._ssh_result_lbl.setText(f"✔  Profile '{name}' saved.")

    def _ssh_build_profile_from_form(self) -> SSHProfile:
        p = SSHProfile(
            name     = self._f_name.text().strip() or "Unnamed",
            host     = self._f_host.text().strip(),
            port     = self._f_port.value(),
            username = self._f_user.text().strip(),
            auth     = "key" if self._f_auth_key.isChecked() else "password",
            password = self._f_pass.text(),
            key_path = self._f_key.text().strip(),
        )
        return p

    def _ssh_test(self):
        p = self._ssh_build_profile_from_form()
        self._ssh_result_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")
        self._ssh_result_lbl.setText("Testing connection…")
        QApplication.processEvents()

        def _do():
            err = SSHManager.test(p)
            return err

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_do)
            err = fut.result(timeout=20)

        if err is None:
            self._ssh_result_lbl.setStyleSheet(f"color:{GREEN}; font-size:9pt;")
            self._ssh_result_lbl.setText(f"✔  Connected to {p.display()} successfully.")
        else:
            self._ssh_result_lbl.setStyleSheet(f"color:{RED}; font-size:9pt;")
            self._ssh_result_lbl.setText(f"✘  {err}")

    def _ssh_connect_form(self):
        self._do_ssh_connect(self._ssh_build_profile_from_form())

    def _ssh_connect_selected(self):
        items = self._ssh_profile_list.selectedItems()
        if not items:
            QMessageBox.information(self, "SSH", "Select a profile first.")
            return
        p: SSHProfile = items[0].data(0, Qt.UserRole)
        # Inject password from form if auth=password
        p.password = self._f_pass.text()
        self._do_ssh_connect(p)

    def _do_ssh_connect(self, profile: SSHProfile):
        self._ssh_result_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")
        self._ssh_result_lbl.setText(f"Connecting to {profile.display()}…")
        QApplication.processEvents()

        def _worker():
            try:
                self._ssh.connect(profile)
                return None
            except Exception as exc:
                return str(exc)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            err = ex.submit(_worker).result(timeout=20)

        if err is None:
            home = self._ssh.get_home()
            self._ssh_remote_cwd = home
            self._ssh_result_lbl.setStyleSheet(f"color:{GREEN}; font-size:9pt;")
            self._ssh_result_lbl.setText(f"✔  Connected — {profile.display()}")
            self._ssh_update_badge(connected=True, profile=profile)
            self._ssh_disconnect_btn.setEnabled(True)
            self._status_bar.showMessage(f"SSH connected: {profile.display()}")
            # ── Auto-configure Run tab for remote ─────────────────────────
            self._inp_workdir.setText(home)
            self._update_run_target()
            self._detect_binary()
            # ── HPC auto-detect ───────────────────────────────────────────
            self._hpc_on_connect(profile)
        else:
            self._ssh_result_lbl.setStyleSheet(f"color:{RED}; font-size:9pt;")
            self._ssh_result_lbl.setText(f"✘  {err}")
            self._ssh_update_badge(connected=False)

    def _ssh_do_disconnect(self):
        self._ssh.disconnect()
        self._ssh_update_badge(connected=False)
        self._ssh_disconnect_btn.setEnabled(False)
        self._ssh_result_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt;")
        self._ssh_result_lbl.setText("Disconnected.")
        self._status_bar.showMessage("SSH disconnected")
        # Restore local defaults
        self._remote_mode = False
        self._cwd_lbl.setToolTip("Type a path and press Enter  (or click ➜)")
        self._inp_workdir.setText(self._cwd)
        self._inp_bin.setText("lmp")
        self._update_run_target()
        self._hpc_on_disconnect()
        self._load_dir(self._cwd)

    def _ssh_update_badge(self, connected: bool, profile: SSHProfile = None):
        if connected and profile:
            txt   = f"  🟢  {profile.username}@{profile.host}  "
            style = (f"color:{GREEN}; font-size:8.5pt; font-weight:600;"
                     f"background:#152015; border:1px solid {GREEN}55;"
                     f"border-radius:10px; padding:2px 8px;")
            self._ssh_status_lbl.setText(f"🟢  Connected — {profile.display()}")
            self._ssh_status_lbl.setStyleSheet(f"color:{GREEN}; font-size:9.5pt; font-weight:600;")
        else:
            txt   = "  🔗  No SSH  "
            style = (f"color:#38415a; font-size:8.5pt; font-weight:600;"
                     f"background:#191c26; border:1px solid #252a38;"
                     f"border-radius:10px; padding:2px 8px;")
            self._ssh_status_lbl.setText("🔗  Not connected")
            self._ssh_status_lbl.setStyleSheet(f"color:{FG2}; font-size:9.5pt;")
        self._ssh_badge.setText(txt)
        self._ssh_badge.setStyleSheet(style)

    # ── Remote file browser ───────────────────────────────────────────────

    def _ssh_browse_remote(self):
        if not HAS_SSH or not self._ssh.connected:
            QMessageBox.warning(self, "SSH", "Not connected. Connect to a server first.")
            return
        self._remote_mode = True
        self._load_remote_dir(self._ssh_remote_cwd)

    def _load_remote_dir(self, path: str):
        path = path.strip()
        if not self._ssh or not self._ssh.connected:
            return
        try:
            entries = self._ssh.list_dir(path)
        except Exception as exc:
            QMessageBox.warning(self, "SFTP", str(exc))
            return

        self._ssh_remote_cwd = path
        # Show bare path in the editable field so the user can edit it directly;
        # host info goes in the tooltip
        self._cwd_lbl.setText(path)
        self._cwd_lbl.setToolTip(
            f"Remote — {self._ssh.profile.username}@{self._ssh.profile.host}\n"
            f"Type a remote path and press Enter"
        )

        self._tree.clear()
        parent = str(Path(path).parent)
        if parent != path:
            up = QTreeWidgetItem(["⬆  .."])
            up.setForeground(0, QColor(ACCENT))
            up.setData(0, Qt.UserRole, ("remote_dir", parent))
            self._tree.addTopLevelItem(up)

        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir:
                item = QTreeWidgetItem([f"📁  {e.name}"])
                item.setForeground(0, QColor(ORANGE))
                item.setData(0, Qt.UserRole, ("remote_dir", e.path))
            else:
                icon, color = "📄", FG
                if re.search(r"\.(in|lammps|lmp)$", e.name, re.I): icon, color = "⚙ ", ACCENT
                elif e.name == "log.lammps" or re.search(r"\.log$", e.name, re.I): icon, color = "📊", GREEN
                elif re.search(r"\.(dat|data)$", e.name, re.I): icon, color = "🗃", YELLOW
                item = QTreeWidgetItem([f"{icon}  {e.name}"])
                item.setForeground(0, QColor(color))
                item.setData(0, Qt.UserRole, ("remote_file", e.path))
            self._tree.addTopLevelItem(item)

    def _open_remote_file(self, remote_path: str):
        try:
            content = self._ssh.read_file(remote_path)
        except Exception as exc:
            QMessageBox.critical(self, "SFTP Error", str(exc))
            return
        self._editor.setPlainText(content)
        self._current_file = None
        self._current_remote_path = remote_path
        self._editor_info.setText(f"  🖥  {remote_path}")
        self._tabs.setCurrentIndex(0)
        self._status_bar.showMessage(f"Remote file: {remote_path}")

    def _ssh_save_remote(self, remote_path: str):
        try:
            self._ssh.write_file(remote_path, self._editor.toPlainText())
            self._editor_info.setText(f"  🖥  Saved: {os.path.basename(remote_path)}")
            self._status_bar.showMessage(f"Saved to remote: {remote_path}")
        except Exception as exc:
            QMessageBox.critical(self, "SFTP Error", str(exc))

    # ── Remote LAMMPS run ─────────────────────────────────────────────────

    def _start_remote_sim(self):
        if not self._ssh or not self._ssh.connected:
            QMessageBox.warning(self, "SSH", "Not connected to any SSH server.")
            return
        # HPC mode: route to sbatch instead of direct mpirun
        if self._hpc_mode:
            # Sync form fields from Run tab into HPC form
            if self._inp_file.text():
                self._h_input.setText(self._inp_file.text())
            if self._inp_workdir.text():
                self._h_workdir.setText(self._inp_workdir.text())
            if self._inp_bin.text():
                self._h_binary.setText(self._inp_bin.text())
            self._tabs.setCurrentIndex(4)   # switch to HPC tab
            QMessageBox.information(
                self, "HPC Mode Active",
                "Direct mpirun on the login node is not allowed on this HPC.\n\n"
                "Your job settings have been copied to the HPC tab.\n"
                "Review the SLURM script and click  ⚡ Submit Job via sbatch."
            )
            return
        inp   = self._inp_file.text().strip()
        np_   = self._inp_np.value()
        wd    = self._inp_workdir.text().strip() or self._ssh_remote_cwd
        bin_  = self._inp_bin.text().strip() or "lmp"
        extra = self._inp_extra.text().strip()
        if not inp:
            QMessageBox.warning(self, "No Input", "Enter an input file name.")
            return

        cmd = f"mpirun -np {np_} {bin_} -in {inp}"
        if extra:
            cmd += f" {extra}"

        self._append_log(f"\n▶ [SSH] {self._ssh.profile.display()}", ACCENT)
        self._append_log(f"  cmd: {cmd}  |  dir: {wd}\n", FG2)

        self._runner = SSHRemoteRunner(self._ssh, cmd, wd)
        self._runner.line_ready.connect(self._on_log_line)
        self._runner.finished.connect(self._on_sim_done)
        self._runner.error.connect(lambda msg: self._append_log(f"[SSH ERROR] {msg}", RED))
        self._runner.start()

        self._btn_run.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._set_status("● Running (SSH)", GREEN)
        self._run_info_lbl.setText(f"SSH:{self._ssh.profile.host}  np={np_}  |  {inp}")
        self._status_bar.showMessage(f"[SSH] Running: {cmd}")

    # ══════════════════════════════════════════════════════════════════════
    # HPC / SLURM Tab
    # ══════════════════════════════════════════════════════════════════════
    # HPC / SLURM — IITJ-style professional script generator
    # ══════════════════════════════════════════════════════════════════════

    def _make_hpc_tab(self):
        import json as _json
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────
        top = QFrame()
        top.setFixedHeight(44)
        top.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 #181c28,stop:1 {BG2}); border-bottom:1px solid {BORDER};"
        )
        tl = QHBoxLayout(top)
        tl.setContentsMargins(14, 0, 14, 0); tl.setSpacing(10)

        tl.addWidget(QLabel("⚡", styleSheet="font-size:14pt; background:transparent;"))
        tl.addWidget(QLabel("HPC Job Scheduler — SLURM  (IITJ)",
                             styleSheet=f"color:{FG}; font-size:10pt; font-weight:700;"))
        tl.addWidget(_vline())

        self._hpc_toggle = QCheckBox("HPC Mode")
        self._hpc_toggle.setToolTip(
            "When ON: ▶ Run routes to sbatch instead of direct mpirun.\n"
            "Required on IITJ HPC — running on the login node is forbidden."
        )
        self._hpc_toggle.setStyleSheet(f"color:{YELLOW}; font-weight:700;")
        self._hpc_toggle.toggled.connect(self._hpc_mode_changed)
        tl.addWidget(self._hpc_toggle)
        tl.addWidget(_vline())

        self._hpc_status_lbl = QLabel("● SSH not connected")
        self._hpc_status_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt;")
        tl.addWidget(self._hpc_status_lbl)
        tl.addStretch()

        for txt, tip, cb in [
            ("sinfo",        "Query partitions",      self._hpc_query_partitions),
            ("⟳ Queue",      "Refresh squeue",        self._hpc_refresh_queue),
            ("💾 Save Config","Save form to JSON",     self._hpc_save_config),
            ("📂 Load Config","Load config from JSON", self._hpc_load_config),
        ]:
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(cb)
            b.setFixedHeight(28); tl.addWidget(b)
        root.addWidget(top)

        # ── Body: form (left) | preview + queue (right) ──────────────────
        body = QSplitter(Qt.Horizontal); body.setHandleWidth(1)

        # ── Left form in a scroll area ────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea{{background:{BG2}; border:none;}}")

        fc = QWidget(); fc.setStyleSheet(f"background:{BG2};")
        fl = QVBoxLayout(fc)
        fl.setContentsMargins(14, 12, 14, 12); fl.setSpacing(6)
        scroll.setWidget(fc)

        def _sec(txt):
            l = QLabel(txt); l.setObjectName("section"); return l

        def _inp(placeholder="", value="", cb=True):
            e = QLineEdit(value); e.setPlaceholderText(placeholder)
            if cb: e.textChanged.connect(self._hpc_update_preview)
            return e

        def _spin(lo, hi, val):
            s = QSpinBox(); s.setRange(lo, hi); s.setValue(val)
            s.valueChanged.connect(self._hpc_update_preview); return s

        def _browse_remote(field, mode="dir"):
            def cb():
                if self._is_remote():
                    p = self._sftp_pick_dir() if mode == "dir" else self._sftp_pick_file()
                    if p: field.setText(p)
                else:
                    if mode == "dir":
                        d = QFileDialog.getExistingDirectory(self, "Select", field.text())
                        if d: field.setText(d)
                    else:
                        p, _ = QFileDialog.getOpenFileName(self, "Select", field.text())
                        if p: field.setText(p)
            return cb

        def _row(label, *widgets):
            fl.addWidget(_sec(label))
            row = QHBoxLayout(); row.setSpacing(4)
            for w in widgets: row.addWidget(w, 1) if isinstance(w, QLineEdit) or isinstance(w, QComboBox) or isinstance(w, QSpinBox) else row.addWidget(w)
            fl.addLayout(row)

        # ── Section: Job Settings ─────────────────────────────────────────
        fl.addWidget(QLabel("━━  Job Settings",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700;"))

        fl.addWidget(_sec("Job Name  (#SBATCH --job-name)"))
        self._h_name = _inp("e.g. cr_lammps", "lammps_job")
        fl.addWidget(self._h_name)

        fl.addWidget(_sec("Partition  (#SBATCH --partition)"))
        ph = QHBoxLayout(); ph.setSpacing(4)
        self._h_partition = QComboBox(); self._h_partition.setEditable(True)
        self._h_partition.addItems(["small", "medium", "large", "gpu"])
        self._h_partition.currentTextChanged.connect(self._hpc_update_preview)
        ph.addWidget(self._h_partition, 1)
        qb = QPushButton("Query"); qb.setFixedWidth(52); qb.clicked.connect(self._hpc_query_partitions)
        ph.addWidget(qb); fl.addLayout(ph)

        fl.addWidget(_sec("Nodes  /  Tasks (--ntasks)  /  CPUs-per-task"))
        ntnc = QHBoxLayout(); ntnc.setSpacing(6)
        self._h_nodes        = _spin(1, 64, 1)
        self._h_ntasks       = _spin(1, 1024, 32)
        self._h_cpus_per_task= _spin(1, 128, 1)
        for s, t in [(self._h_nodes,"nodes"),(self._h_ntasks,"tasks"),(self._h_cpus_per_task,"cpus/task")]:
            ntnc.addWidget(s, 1)
            lbl = QLabel(t); lbl.setStyleSheet(f"color:{FG2}; font-size:8pt;")
            ntnc.addWidget(lbl)
        fl.addLayout(ntnc)

        fl.addWidget(_sec("Memory  (#SBATCH --mem)  /  Walltime  (#SBATCH --time)"))
        mw = QHBoxLayout(); mw.setSpacing(6)
        self._h_mem      = _inp("e.g. 64G", "64G")
        self._h_walltime = _inp("D-HH:MM:SS", "5-00:00:00")
        mw.addWidget(self._h_mem, 1)
        mw.addWidget(QLabel("/", styleSheet=f"color:{FG2};"))
        mw.addWidget(self._h_walltime, 1)
        fl.addLayout(mw)

        # ── Section: Paths ────────────────────────────────────────────────
        fl.addWidget(QLabel("━━  Paths",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700; margin-top:6px;"))

        fl.addWidget(_sec("Base Directory  ($BASE)"))
        bd = QHBoxLayout(); bd.setSpacing(4)
        self._h_base_dir = _inp("/scratch/data/USERNAME/project")
        self._h_base_dir_browse = QPushButton("Browse"); self._h_base_dir_browse.setFixedWidth(58)
        self._h_base_dir_browse.clicked.connect(_browse_remote(self._h_base_dir))
        bd.addWidget(self._h_base_dir, 1); bd.addWidget(self._h_base_dir_browse)
        fl.addLayout(bd)

        fl.addWidget(_sec("Log Directory  (--output / --error)"))
        ld = QHBoxLayout(); ld.setSpacing(4)
        self._h_log_dir = _inp("$BASE/slurm_logs")
        ld_b = QPushButton("Browse"); ld_b.setFixedWidth(58)
        ld_b.clicked.connect(_browse_remote(self._h_log_dir))
        ld.addWidget(self._h_log_dir, 1); ld.addWidget(ld_b)
        fl.addLayout(ld)

        # ── Section: Container ────────────────────────────────────────────
        fl.addWidget(QLabel("━━  Singularity Container",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700; margin-top:6px;"))

        self._h_use_sif = QCheckBox("Use Singularity/Apptainer container")
        self._h_use_sif.setChecked(True)
        self._h_use_sif.setStyleSheet(f"color:{FG}; font-weight:600;")
        self._h_use_sif.toggled.connect(self._hpc_update_preview)
        fl.addWidget(self._h_use_sif)

        fl.addWidget(_sec("SIF Image Path  ($SIF)"))
        sf = QHBoxLayout(); sf.setSpacing(4)
        self._h_sif = _inp("/scratch/data/USERNAME/lammps/lammps.sif")
        sf_b = QPushButton("Browse"); sf_b.setFixedWidth(58)
        sf_b.clicked.connect(_browse_remote(self._h_sif, mode="file"))
        sf.addWidget(self._h_sif, 1); sf.addWidget(sf_b)
        fl.addLayout(sf)

        fl.addWidget(_sec("Singularity Binary  ($SINGULARITY)"))
        sg = QHBoxLayout(); sg.setSpacing(4)
        self._h_sing_bin = _inp("/opt/ohpc/pub/libs/singularity/3.7.1/bin/singularity",
                                "/opt/ohpc/pub/libs/singularity/3.7.1/bin/singularity")
        sg_b = QPushButton("which"); sg_b.setFixedWidth(44)
        sg_b.setToolTip("Find singularity binary on remote")
        sg_b.clicked.connect(self._hpc_detect_singularity)
        sg.addWidget(self._h_sing_bin, 1); sg.addWidget(sg_b)
        fl.addLayout(sg)

        fl.addWidget(_sec("Bind Mounts  (--bind, comma-separated)"))
        self._h_bind = _inp("$BASE:$BASE", "$BASE:$BASE")
        fl.addWidget(self._h_bind)

        # ── Section: LAMMPS ───────────────────────────────────────────────
        fl.addWidget(QLabel("━━  LAMMPS Options",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700; margin-top:6px;"))

        fl.addWidget(_sec("Run Directory  (overrides $BASE via RUN_DIR env var)"))
        rd = QHBoxLayout(); rd.setSpacing(4)
        self._h_workdir = _inp("$BASE  (or override per-run)")
        rd_b = QPushButton("Browse"); rd_b.setFixedWidth(58)
        rd_b.clicked.connect(_browse_remote(self._h_workdir))
        rd.addWidget(self._h_workdir, 1); rd.addWidget(rd_b)
        fl.addLayout(rd)

        fl.addWidget(_sec("Input File  /  LAMMPS binary inside container"))
        ib = QHBoxLayout(); ib.setSpacing(6)
        self._h_input  = _inp("in.lammps", "in.lammps")
        self._h_binary = _inp("lmp", "lmp")
        ib.addWidget(self._h_input, 2); ib.addWidget(self._h_binary, 1)
        fl.addLayout(ib)

        fl.addWidget(_sec("OMP Threads  /  Extra LAMMPS args"))
        oa = QHBoxLayout(); oa.setSpacing(6)
        self._h_omp   = _spin(1, 64, 1)
        self._h_lmp_extra = _inp("-screen none", "-screen none")
        oa.addWidget(QLabel("OMP:", styleSheet=f"color:{FG2};"))
        oa.addWidget(self._h_omp)
        oa.addWidget(self._h_lmp_extra, 1)
        fl.addLayout(oa)

        # ── Section: Email notifications ──────────────────────────────────
        fl.addWidget(QLabel("━━  Email Notifications",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700; margin-top:6px;"))

        fl.addWidget(_sec("Email Address  (#SBATCH --mail-user)"))
        self._h_email = _inp("user@iitj.ac.in")
        fl.addWidget(self._h_email)

        fl.addWidget(_sec("Notify on  (#SBATCH --mail-type)"))
        mail_row = QHBoxLayout(); mail_row.setSpacing(12)
        self._h_mail_begin  = QCheckBox("BEGIN")
        self._h_mail_end    = QCheckBox("END")
        self._h_mail_fail   = QCheckBox("FAIL")
        self._h_mail_requeue= QCheckBox("REQUEUE")
        for chk in (self._h_mail_begin, self._h_mail_end, self._h_mail_fail, self._h_mail_requeue):
            chk.setChecked(chk.text() in ("BEGIN","END","FAIL"))
            chk.setStyleSheet(f"color:{FG};")
            chk.toggled.connect(self._hpc_update_preview)
            mail_row.addWidget(chk)
        mail_row.addStretch()
        fl.addLayout(mail_row)

        # ── Section: Modules ──────────────────────────────────────────────
        fl.addWidget(QLabel("━━  Load Modules",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700; margin-top:6px;"))
        mod_row = QHBoxLayout(); mod_row.setSpacing(4)
        self._h_mod_input = QLineEdit()
        self._h_mod_input.setPlaceholderText("e.g. openmpi/4.1  or  lammps/3Mar2020")
        add_m = QPushButton("+"); add_m.setFixedSize(26,26)
        add_m.setStyleSheet(f"color:{ACCENT}; font-size:13pt; background:transparent; border:none;")
        add_m.clicked.connect(self._hpc_add_module)
        rm_m = QPushButton("✕"); rm_m.setFixedSize(26,26)
        rm_m.setStyleSheet(f"color:{RED}; font-size:11pt; background:transparent; border:none;")
        rm_m.clicked.connect(self._hpc_remove_module)
        mod_row.addWidget(self._h_mod_input, 1); mod_row.addWidget(add_m); mod_row.addWidget(rm_m)
        fl.addLayout(mod_row)
        self._h_modules = QListWidget()
        self._h_modules.setMaximumHeight(68)
        self._h_modules.setStyleSheet(
            f"background:{BG3}; border:1px solid {BORDER}; border-radius:4px; color:{FG}; font-size:9pt;")
        self._h_modules.model().rowsInserted.connect(self._hpc_update_preview)
        self._h_modules.model().rowsRemoved.connect(self._hpc_update_preview)
        fl.addWidget(self._h_modules)

        # ── Section: Extra #SBATCH ────────────────────────────────────────
        fl.addWidget(QLabel("━━  Extra #SBATCH Directives",
                             styleSheet=f"color:{ACCENT}; font-size:9.5pt; font-weight:700; margin-top:6px;"))
        self._h_extra = QPlainTextEdit()
        self._h_extra.setMaximumHeight(68)
        self._h_extra.setPlaceholderText("--constraint=infiniband\n--exclusive")
        self._h_extra.setStyleSheet(
            f"background:{BG3}; color:{FG}; border:1px solid {BORDER}; border-radius:4px;"
            f"font-family:Courier New; font-size:9pt;")
        self._h_extra.textChanged.connect(self._hpc_update_preview)
        fl.addWidget(self._h_extra)

        fl.addSpacing(8)
        self._hpc_submit_btn = QPushButton("  ⚡  Submit Job via sbatch  ")
        self._hpc_submit_btn.setObjectName("run")
        self._hpc_submit_btn.setMinimumHeight(38)
        self._hpc_submit_btn.setEnabled(False)
        self._hpc_submit_btn.clicked.connect(self._hpc_submit)
        fl.addWidget(self._hpc_submit_btn)
        fl.addStretch()

        body.addWidget(scroll)

        # ── Right: preview + queue ────────────────────────────────────────
        right = QSplitter(Qt.Vertical); right.setHandleWidth(1)

        pf = QFrame(); pf.setStyleSheet(f"background:{BG};")
        pfl = QVBoxLayout(pf); pfl.setContentsMargins(10,8,10,8); pfl.setSpacing(5)
        ph2 = QHBoxLayout()
        ph2.addWidget(QLabel("Generated SLURM Script",
                               styleSheet=f"color:{FG}; font-size:10pt; font-weight:700;"))
        ph2.addStretch()
        cp = QPushButton("Copy"); cp.setFixedWidth(52)
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self._hpc_script_preview.toPlainText()))
        ph2.addWidget(cp)
        pfl.addLayout(ph2)
        self._hpc_script_preview = QPlainTextEdit()
        self._hpc_script_preview.setReadOnly(True)
        self._hpc_script_preview.setFont(QFont("Courier New", 10))
        self._hpc_script_preview.setStyleSheet(
            f"background:{BG3}; color:#c8e8f0; border:1px solid {BORDER}; border-radius:5px;")
        pfl.addWidget(self._hpc_script_preview, 1)
        right.addWidget(pf)

        qf = QFrame(); qf.setStyleSheet(f"background:{BG2}; border-top:1px solid {BORDER};")
        qfl = QVBoxLayout(qf); qfl.setContentsMargins(10,8,10,8); qfl.setSpacing(5)
        qh = QHBoxLayout()
        qh.addWidget(QLabel("Job Queue  (squeue)",
                              styleSheet=f"color:{FG}; font-size:10pt; font-weight:700;"))
        qh.addStretch()
        for txt, tip, cb in [
            ("⟳ Refresh","Refresh squeue", self._hpc_refresh_queue),
            ("✕ Cancel", "scancel selected", self._hpc_cancel_job),
            ("📄 Output", "View .out file",  self._hpc_view_output),
        ]:
            b = QPushButton(txt); b.setToolTip(tip); b.clicked.connect(cb)
            b.setFixedHeight(26); qh.addWidget(b)
        qfl.addLayout(qh)

        self._hpc_queue_table = QTableWidget(0, 8)
        self._hpc_queue_table.setHorizontalHeaderLabels(
            ["Job ID","Name","Status","Reason","Time","Partition","CPUs","Mem"])
        hdr = self._hpc_queue_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self._hpc_queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hpc_queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hpc_queue_table.setAlternatingRowColors(True)
        self._hpc_queue_table.setStyleSheet(
            f"QTableWidget{{background:{BG2};color:{FG};border:none;gridline-color:{BORDER};"
            f"alternate-background-color:#1e2230;outline:none;}}"
            f"QTableWidget::item{{padding:3px 8px;}}"
            f"QTableWidget::item:selected{{background:{SEL};color:{ACCENT};}}"
            f"QHeaderView::section{{background:#212535;color:{FG2};border:none;"
            f"border-bottom:1px solid {BORDER};padding:4px 8px;font-weight:700;}}"
        )
        qfl.addWidget(self._hpc_queue_table, 1)
        self._hpc_info_lbl = QLabel("No jobs submitted this session.")
        self._hpc_info_lbl.setStyleSheet(f"color:{FG2}; font-size:8.5pt;")
        qfl.addWidget(self._hpc_info_lbl)

        right.addWidget(qf)
        right.setSizes([420, 220])
        body.addWidget(right)
        body.setSizes([380, 760])
        root.addWidget(body, 1)

        self._hpc_update_preview()
        return w

    # ── HPC helpers ───────────────────────────────────────────────────────

    def _hpc_mode_changed(self, enabled: bool):
        self._hpc_mode = enabled
        self._hpc_submit_btn.setEnabled(enabled and self._is_remote())
        self._update_run_target()
        color = YELLOW if enabled else FG2
        self._hpc_status_lbl.setText(
            "⚡ HPC mode ON — jobs go via sbatch" if enabled
            else ("● SSH not connected" if not self._is_remote()
                  else f"● Connected — {self._ssh.profile.display()}")
        )
        self._hpc_status_lbl.setStyleSheet(f"color:{color}; font-size:9pt; font-weight:600;")

    def _hpc_generate_script(self) -> str:
        name      = self._h_name.text().strip()         or "lammps_job"
        part      = self._h_partition.currentText()     or "medium"
        nodes     = self._h_nodes.value()
        ntasks    = self._h_ntasks.value()
        cpus_pt   = self._h_cpus_per_task.value()
        mem       = self._h_mem.text().strip()           or "64G"
        wtime     = self._h_walltime.text().strip()      or "5-00:00:00"
        base_dir  = self._h_base_dir.text().strip()      or "/scratch/data/USER/project"
        log_dir   = self._h_log_dir.text().strip()       or f"{base_dir}/slurm_logs"
        sif       = self._h_sif.text().strip()           or "/scratch/data/USER/lammps/lammps.sif"
        sing_bin  = self._h_sing_bin.text().strip()      or "singularity"
        bind      = self._h_bind.text().strip()          or "$BASE:$BASE"
        run_dir   = self._h_workdir.text().strip()       or base_dir
        inp_file  = self._h_input.text().strip()         or "in.lammps"
        binary    = self._h_binary.text().strip()        or "lmp"
        omp       = self._h_omp.value()
        lmp_extra = self._h_lmp_extra.text().strip()
        email     = self._h_email.text().strip()
        use_sif   = self._h_use_sif.isChecked()

        mail_types = [t for chk, t in [
            (self._h_mail_begin, "BEGIN"), (self._h_mail_end, "END"),
            (self._h_mail_fail, "FAIL"),   (self._h_mail_requeue, "REQUEUE"),
        ] if chk.isChecked()]

        extra_lines = [
            (l if l.startswith("#SBATCH") else f"#SBATCH {l}")
            for l in self._h_extra.toPlainText().splitlines()
            if l.strip()
        ]

        modules = [self._h_modules.item(i).text()
                   for i in range(self._h_modules.count())]

        L = []   # script lines

        L += [
            "#!/bin/bash",
            f"# {'=' * 61}",
            f"# IITJ HPC — SLURM job: {name}",
            f"# Generated by LAMMPS Dashboard",
            f"# {'=' * 61}",
            f"#SBATCH --job-name={name}",
            f"#SBATCH --partition={part}",
            f"#SBATCH --nodes={nodes}",
            f"#SBATCH --ntasks={ntasks}",
            f"#SBATCH --cpus-per-task={cpus_pt}",
            f"#SBATCH --mem={mem}",
            f"#SBATCH --time={wtime}",
            f"#SBATCH --output={log_dir}/{name}_%j.out",
            f"#SBATCH --error={log_dir}/{name}_%j.err",
        ]
        if mail_types and email:
            L += [
                f"#SBATCH --mail-type={','.join(mail_types)}",
                f"#SBATCH --mail-user={email}",
            ]
        L += extra_lines
        L += [
            "",
            "set -euo pipefail",
            "",
            "# ─── Paths ────────────────────────────────────────────────────────────",
            f"BASE={base_dir}",
        ]
        if use_sif:
            L += [
                f"SIF={sif}",
                f"SINGULARITY={sing_bin}",
            ]
        L += [
            "",
            f"# Override via environment:  RUN_DIR=/path/to/case sbatch {name}.sh",
            f'RUN_DIR="${{RUN_DIR:-{run_dir}}}"',
            f'INPUT_FILE="${{INPUT_FILE:-{inp_file}}}"',
            f"MPI_PROCS=${{SLURM_NTASKS:-{ntasks}}}",
            "",
            f"export OMP_NUM_THREADS={omp}",
            "",
            f'mkdir -p "{log_dir}"',
            "",
            'echo "================================================================"',
            'echo " SLURM Job   : $SLURM_JOB_ID"',
            'echo " Host        : $(hostname)   Date: $(date)"',
            'echo " Partition   : $SLURM_JOB_PARTITION"',
            'echo " MPI procs   : $MPI_PROCS"',
            'echo " Run dir     : $RUN_DIR"',
            'echo " Input file  : $INPUT_FILE"',
            'echo "================================================================"',
            "",
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
            lmp_cmd = f"lmp \\\n        -in \"$INPUT_FILE\" \\\n        -log \"$RUN_DIR/log.lammps\""
            if lmp_extra:
                lmp_cmd += f" \\\n        {lmp_extra}"
            L += [
                "$SINGULARITY exec --no-home \\",
                f"    {bind_args} \\",
                f"    --env \"OMP_NUM_THREADS={omp}\" \\",
                '    --pwd "$RUN_DIR" \\',
                '    "$SIF" \\',
                f"    mpirun -np \"$MPI_PROCS\" {binary} \\",
                f"        -in \"$INPUT_FILE\" \\",
                f"        -log \"$RUN_DIR/log.lammps\" \\",
                f"        -screen none",
            ]
            if lmp_extra:
                L[-1] += f" \\\n        {lmp_extra}"
        else:
            cmd = f"mpirun -np \"$MPI_PROCS\" {binary} -in \"$INPUT_FILE\" -log \"$RUN_DIR/log.lammps\" -screen none"
            if lmp_extra: cmd += f" {lmp_extra}"
            L.append(cmd)

        L += [
            "",
            "EXIT_CODE=$?",
            'echo "Job finished: $(date)   exit_code=$EXIT_CODE"',
            "exit $EXIT_CODE",
        ]
        return "\n".join(L)

    def _hpc_update_preview(self):
        if hasattr(self, "_hpc_script_preview"):
            self._hpc_script_preview.setPlainText(self._hpc_generate_script())

    def _hpc_add_module(self):
        mod = self._h_mod_input.text().strip()
        if mod:
            self._h_modules.addItem(mod)
            self._h_mod_input.clear()

    def _hpc_remove_module(self):
        for item in self._h_modules.selectedItems():
            self._h_modules.takeItem(self._h_modules.row(item))

    def _hpc_detect_singularity(self):
        """Find singularity / apptainer binary on the remote."""
        if not self._is_remote():
            return
        try:
            _, out, _ = self._ssh._client.exec_command(
                "which singularity apptainer 2>/dev/null | head -1"
            )
            found = out.read().decode().strip()
            if found:
                self._h_sing_bin.setText(found)
                self._status_bar.showMessage(f"Found: {found}")
        except Exception as exc:
            self._status_bar.showMessage(f"which singularity failed: {exc}")

    def _hpc_save_config(self):
        import json as _json
        cfg = {
            "job_name":      self._h_name.text(),
            "partition":     self._h_partition.currentText(),
            "nodes":         self._h_nodes.value(),
            "ntasks":        self._h_ntasks.value(),
            "cpus_per_task": self._h_cpus_per_task.value(),
            "mem":           self._h_mem.text(),
            "walltime":      self._h_walltime.text(),
            "base_dir":      self._h_base_dir.text(),
            "log_dir":       self._h_log_dir.text(),
            "use_sif":       self._h_use_sif.isChecked(),
            "sif":           self._h_sif.text(),
            "singularity":   self._h_sing_bin.text(),
            "bind":          self._h_bind.text(),
            "workdir":       self._h_workdir.text(),
            "input_file":    self._h_input.text(),
            "binary":        self._h_binary.text(),
            "omp":           self._h_omp.value(),
            "lmp_extra":     self._h_lmp_extra.text(),
            "email":         self._h_email.text(),
            "mail_begin":    self._h_mail_begin.isChecked(),
            "mail_end":      self._h_mail_end.isChecked(),
            "mail_fail":     self._h_mail_fail.isChecked(),
            "mail_requeue":  self._h_mail_requeue.isChecked(),
            "modules":       [self._h_modules.item(i).text()
                              for i in range(self._h_modules.count())],
            "extra_sbatch":  self._h_extra.toPlainText(),
        }
        path = Path.home() / ".lammps_dashboard" / "hpc_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            _json.dump(cfg, f, indent=2)
        self._status_bar.showMessage(f"HPC config saved → {path}")

    def _hpc_load_config(self):
        import json as _json
        path = Path.home() / ".lammps_dashboard" / "hpc_config.json"
        if not path.exists():
            QMessageBox.information(self, "Load Config", f"No config found at:\n{path}")
            return
        try:
            with open(path) as f:
                cfg = _json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            return

        self._h_name.setText(cfg.get("job_name", ""))
        idx = self._h_partition.findText(cfg.get("partition", ""))
        if idx >= 0: self._h_partition.setCurrentIndex(idx)
        else:        self._h_partition.setCurrentText(cfg.get("partition", ""))
        self._h_nodes.setValue(cfg.get("nodes", 1))
        self._h_ntasks.setValue(cfg.get("ntasks", 32))
        self._h_cpus_per_task.setValue(cfg.get("cpus_per_task", 1))
        self._h_mem.setText(cfg.get("mem", "64G"))
        self._h_walltime.setText(cfg.get("walltime", "5-00:00:00"))
        self._h_base_dir.setText(cfg.get("base_dir", ""))
        self._h_log_dir.setText(cfg.get("log_dir", ""))
        self._h_use_sif.setChecked(cfg.get("use_sif", True))
        self._h_sif.setText(cfg.get("sif", ""))
        self._h_sing_bin.setText(cfg.get("singularity", ""))
        self._h_bind.setText(cfg.get("bind", "$BASE:$BASE"))
        self._h_workdir.setText(cfg.get("workdir", ""))
        self._h_input.setText(cfg.get("input_file", "in.lammps"))
        self._h_binary.setText(cfg.get("binary", "lmp"))
        self._h_omp.setValue(cfg.get("omp", 1))
        self._h_lmp_extra.setText(cfg.get("lmp_extra", "-screen none"))
        self._h_email.setText(cfg.get("email", ""))
        self._h_mail_begin.setChecked(cfg.get("mail_begin", True))
        self._h_mail_end.setChecked(cfg.get("mail_end", True))
        self._h_mail_fail.setChecked(cfg.get("mail_fail", True))
        self._h_mail_requeue.setChecked(cfg.get("mail_requeue", False))
        self._h_modules.clear()
        for mod in cfg.get("modules", []):
            self._h_modules.addItem(mod)
        self._h_extra.setPlainText(cfg.get("extra_sbatch", ""))
        self._status_bar.showMessage(f"HPC config loaded from {path}")

    def _hpc_query_partitions(self):
        if not self._is_remote():
            self._hpc_status_lbl.setText("● Not connected"); return
        try:
            _, out, _ = self._ssh._client.exec_command(
                "sinfo -h -o '%P' 2>/dev/null | tr -d '*'")
            parts = [p.strip() for p in out.read().decode().splitlines() if p.strip()]
        except Exception as exc:
            self._hpc_status_lbl.setText(f"sinfo error: {exc}"); return
        if parts:
            cur = self._h_partition.currentText()
            self._h_partition.clear(); self._h_partition.addItems(parts)
            idx = self._h_partition.findText(cur)
            if idx >= 0: self._h_partition.setCurrentIndex(idx)
            self._hpc_status_lbl.setText(f"⚡ {len(parts)} partition(s) — {', '.join(parts[:4])}")
            self._hpc_status_lbl.setStyleSheet(f"color:{GREEN}; font-size:9pt;")

    def _hpc_submit(self):
        if not self._is_remote():
            QMessageBox.warning(self, "HPC", "Not connected."); return
        workdir = self._h_workdir.text().strip() or self._h_base_dir.text().strip()
        if not workdir:
            QMessageBox.warning(self, "HPC", "Set a working / base directory."); return

        script      = self._hpc_generate_script()
        job_name    = self._h_name.text().strip() or "lammps_job"
        script_name = f"{job_name}.sh"
        remote_path = workdir.rstrip("/") + "/" + script_name

        try:
            self._ssh.write_file(remote_path, script)
        except Exception as exc:
            QMessageBox.critical(self, "Upload Error", str(exc)); return

        try:
            _, stdout, stderr = self._ssh._client.exec_command(
                f"cd {workdir!r} && chmod +x {script_name} && sbatch {script_name}"
            )
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
        except Exception as exc:
            QMessageBox.critical(self, "sbatch Error", str(exc)); return

        m = re.search(r"Submitted batch job (\d+)", out)
        if m:
            job_id = m.group(1)
            self._hpc_jobs.append({"id": job_id, "name": job_name, "workdir": workdir})
            self._hpc_info_lbl.setText(
                f"✔  {job_name}  →  Job ID {job_id}  ({self._ssh.profile.host})")
            self._hpc_info_lbl.setStyleSheet(f"color:{GREEN}; font-size:8.5pt;")
            self._status_bar.showMessage(f"[HPC] Job {job_id} submitted: {job_name}")
            self._append_log(
                f"\n[HPC] Submitted: {job_name}\n"
                f"  Job ID : {job_id}\n  Script : {remote_path}\n"
                f"  Dir    : {workdir}", ACCENT)
            self._hpc_save_config()
            self._hpc_refresh_queue()
        else:
            msg = out or err or "Unknown sbatch error"
            QMessageBox.critical(self, "sbatch Failed", msg)
            self._hpc_info_lbl.setText(f"✘  {msg[:120]}")
            self._hpc_info_lbl.setStyleSheet(f"color:{RED}; font-size:8.5pt;")

    def _hpc_refresh_queue(self):
        if not self._is_remote(): return
        try:
            _, stdout, _ = self._ssh._client.exec_command(
                "squeue -u $USER -o '%i|%j|%T|%R|%l|%P|%C|%m' --noheader 2>/dev/null")
            lines = stdout.read().decode().strip().splitlines()
        except Exception as exc:
            self._hpc_status_lbl.setText(f"squeue error: {exc}"); return
        t = self._hpc_queue_table; t.setRowCount(0)
        colors = {"RUNNING": GREEN, "PENDING": YELLOW,
                  "FAILED": RED, "COMPLETED": FG2, "CANCELLED": RED}
        for line in lines:
            parts = line.split("|")
            if len(parts) < 8: continue
            row = t.rowCount(); t.insertRow(row)
            for col, val in enumerate(parts[:8]):
                item = QTableWidgetItem(val.strip())
                if col == 2:
                    item.setForeground(QColor(colors.get(val.strip(), FG)))
                t.setItem(row, col, item)
        n = t.rowCount()
        self._hpc_info_lbl.setText(
            f"{'No active jobs' if not n else f'{n} job(s) in queue'} — refreshed just now")
        self._hpc_info_lbl.setStyleSheet(f"color:{FG2}; font-size:8.5pt;")

    def _hpc_cancel_job(self):
        row = self._hpc_queue_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "HPC", "Select a job row first."); return
        job_id = self._hpc_queue_table.item(row, 0).text()
        if QMessageBox.question(self, "Cancel", f"scancel {job_id}?") != QMessageBox.Yes: return
        try:
            self._ssh._client.exec_command(f"scancel {job_id}")
            self._status_bar.showMessage(f"scancel {job_id} sent")
            QTimer.singleShot(1500, self._hpc_refresh_queue)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _hpc_view_output(self):
        row = self._hpc_queue_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "HPC", "Select a job row first."); return
        job_id   = self._hpc_queue_table.item(row, 0).text()
        job_name = self._hpc_queue_table.item(row, 1).text()
        log_dir  = self._h_log_dir.text().strip() or self._ssh_remote_cwd
        for out_file in [
            f"{log_dir}/{job_name}_{job_id}.out",
            f"{log_dir}/{job_id}.out",
        ]:
            try:
                content = self._ssh.read_file(out_file)
                self._editor.setPlainText(content)
                self._editor_info.setText(f"  📋 {os.path.basename(out_file)}  (job {job_id})")
                self._tabs.setCurrentIndex(0)
                self._append_log(f"\n[HPC] Output: {out_file}", ACCENT)
                return
            except Exception:
                continue
        QMessageBox.warning(self, "Not Found",
                            f"Could not find output file for job {job_id} in:\n{log_dir}")

    def _hpc_on_connect(self, profile):
        hpc_kw = ("hpc", "cluster", "slurm", "login", "hpclogin", "iitj", "iiser", "iisc")
        if any(kw in profile.host.lower() for kw in hpc_kw):
            self._hpc_toggle.setChecked(True)
            self._hpc_status_lbl.setText(
                f"⚡ HPC detected — {profile.host}  (jobs go via sbatch)")
            self._hpc_status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt; font-weight:700;")
            self._hpc_submit_btn.setEnabled(True)
            # Auto-fill paths from username
            home = self._ssh_remote_cwd
            self._h_workdir.setText(home)
            self._h_base_dir.setText(home)
            self._h_log_dir.setText(home + "/slurm_logs")
            # Try to load saved config
            self._hpc_load_config()
            QTimer.singleShot(600, self._hpc_query_partitions)
            QTimer.singleShot(800, self._hpc_detect_singularity)
        else:
            self._hpc_status_lbl.setText(f"● Connected — {profile.display()} (not HPC)")
            self._hpc_status_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt;")

    def _hpc_on_disconnect(self):
        self._hpc_toggle.setChecked(False)
        self._hpc_submit_btn.setEnabled(False)
        self._hpc_status_lbl.setText("● SSH not connected")
        self._hpc_status_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt;")

    # ── AI Assistant Tab ──────────────────────────────────────────────────
    def _make_ai_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Top toolbar ───────────────────────────────────────────────────
        tb = QFrame()
        tb.setStyleSheet(f"background:{BG2}; border-bottom:1px solid {BORDER};")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(10, 7, 10, 7)
        tl.setSpacing(8)

        tl.addWidget(QLabel("Model:", styleSheet=f"color:{FG2}; font-size:9pt;"))
        self._ai_model_cb = QComboBox()
        self._ai_model_cb.setMinimumWidth(220)
        self._ai_model_cb.setStyleSheet(
            f"background:{BG3}; color:{ACCENT}; border:1px solid {BORDER};"
            f"border-radius:4px; padding:3px 8px; font-weight:bold;")
        self._ai_model_cb.setToolTip("Select local Ollama model")
        tl.addWidget(self._ai_model_cb)

        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(26, 26)
        refresh_btn.setToolTip("Refresh model list")
        refresh_btn.setStyleSheet("padding:0; font-size:12pt;")
        refresh_btn.clicked.connect(self._ai_refresh_models)
        tl.addWidget(refresh_btn)

        get_model_btn = QPushButton("⬇ Get Model")
        get_model_btn.setToolTip("Download an Ollama model")
        get_model_btn.setStyleSheet(
            f"background:#1a3a1a; color:{GREEN}; border:1px solid {GREEN};"
            f"border-radius:4px; padding:3px 10px; font-size:9pt;")
        get_model_btn.clicked.connect(self._ai_download_model)
        tl.addWidget(get_model_btn)

        tl.addWidget(_vline())

        # CPU / GPU toggle  (default CPU — GPU needs Ampere+ for this Ollama build)
        self._ai_cpu_chk = QCheckBox("CPU mode")
        self._ai_cpu_chk.setChecked(True)   # safe default for T1000 / Turing GPUs
        self._ai_cpu_chk.setToolTip(
            "Checked  → num_gpu=0  (CPU only — reliable on all machines)\n"
            "Unchecked → let Ollama decide GPU layers\n\n"
            "If you see a CUDA / 'device kernel image invalid' error, keep this checked."
        )
        self._ai_cpu_chk.setStyleSheet(f"color:{FG2}; font-size:9pt;")
        tl.addWidget(self._ai_cpu_chk)

        tl.addWidget(_vline())

        self._ai_status_lbl = QLabel("● Not connected")
        self._ai_status_lbl.setStyleSheet(f"color:{FG2}; font-size:9pt;")
        tl.addWidget(self._ai_status_lbl)

        tl.addStretch()

        clear_btn = QPushButton("Clear Chat")
        clear_btn.clicked.connect(self._ai_clear_chat)
        tl.addWidget(clear_btn)
        lay.addWidget(tb)

        # ── Download progress bar (hidden until needed) ────────────────────
        self._dl_frame = QFrame()
        self._dl_frame.setStyleSheet(f"background:{BG2}; border-bottom:1px solid {BORDER};")
        dl_lay = QHBoxLayout(self._dl_frame)
        dl_lay.setContentsMargins(10, 6, 10, 6)
        dl_lay.setSpacing(8)
        self._dl_label = QLabel("Downloading qwen3-coder:latest…")
        self._dl_label.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")
        self._dl_bar = QProgressBar()
        self._dl_bar.setRange(0, 100)
        self._dl_bar.setValue(0)
        self._dl_bar.setFixedHeight(10)
        self._dl_bar.setTextVisible(False)
        self._dl_bar.setStyleSheet(
            f"QProgressBar{{background:{BG3}; border:1px solid {BORDER}; border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{ACCENT}; border-radius:3px;}}")
        self._dl_pct_lbl = QLabel("0%")
        self._dl_pct_lbl.setStyleSheet(f"color:{ACCENT}; font-size:9pt; min-width:36px;")
        dl_lay.addWidget(self._dl_label)
        dl_lay.addWidget(self._dl_bar, 1)
        dl_lay.addWidget(self._dl_pct_lbl)
        self._dl_frame.setVisible(False)
        lay.addWidget(self._dl_frame)

        # ── Chat display ──────────────────────────────────────────────────
        self._chat_view = QTextEdit()
        self._chat_view.setReadOnly(True)
        self._chat_view.setStyleSheet(
            f"background:{BG3}; color:{FG}; border:none;"
            f"selection-background-color:{SEL};")
        self._chat_view.setFont(QFont(UI_FONT, 10))
        self._chat_view.document().setDefaultStyleSheet(f"""
            body  {{
                background:{BG3}; color:{FG};
                font-family:'{UI_FONT}','Segoe UI',sans-serif;
                font-size:10pt; margin:0; padding:8px 4px;
            }}

            /* ── User bubble ── */
            .user {{
                background:#101c2c;
                border-left: 3px solid {ACCENT};
                border-radius: 0 6px 6px 0;
                padding: 10px 14px 10px 12px;
                margin: 8px 48px 8px 6px;
            }}
            .user .role {{ color:{ACCENT}; font-size:8pt; font-weight:700;
                           margin-bottom:5px; letter-spacing:0.5px; }}

            /* ── AI bubble ── */
            .ai {{
                background:#101a14;
                border-left: 3px solid {GREEN};
                border-radius: 0 6px 6px 0;
                padding: 10px 14px 10px 12px;
                margin: 8px 6px 8px 6px;
            }}
            .ai .role {{ color:{GREEN}; font-size:8pt; font-weight:700;
                         margin-bottom:6px; letter-spacing:0.5px; }}

            /* ── Thinking block (inside .ai) ── */
            .thinking {{
                background: #0c0e14;
                border: 1px solid #252a3a;
                border-left: 3px solid #3a4060;
                border-radius: 4px;
                margin: 6px 0 10px 0;
                padding: 0;
            }}
            .think-hdr {{
                color: #4a5278;
                font-size: 8pt;
                font-weight: 700;
                font-style: normal;
                padding: 5px 10px 4px 10px;
                border-bottom: 1px solid #1e2230;
                letter-spacing: 0.3px;
            }}
            .think-body {{
                color: #505878;
                font-size: 8.5pt;
                font-style: italic;
                padding: 7px 10px 8px 10px;
                line-height: 1.55;
                white-space: pre-wrap;
                word-wrap: break-word;
            }}

            /* ── System / error notice ── */
            .sys {{
                background:#1c1a14; border-left:3px solid {YELLOW};
                border-radius:0 6px 6px 0;
                padding:8px 12px; margin:8px 6px;
                font-size:8.5pt; color:{YELLOW};
            }}

            /* ── Code ── */
            pre {{
                background:#090c12;
                padding:12px 14px;
                border-radius:5px;
                font-family:'Courier New','Consolas',monospace;
                font-size:9pt;
                color:#c8e0f0;
                border:1px solid #1a2030;
                margin:8px 0;
                white-space:pre-wrap;
                word-wrap:break-word;
            }}
            code {{
                font-family:'Courier New','Consolas',monospace;
                font-size:9pt;
                background:#0d1220;
                color:#ffd080;
                padding:1px 5px;
                border-radius:3px;
                border:1px solid #242e42;
            }}

            b     {{ color:#e8f0ff; }}
            i     {{ color:#a8b8d0; }}
            p     {{ margin:5px 0; line-height:1.65; }}
            ul    {{ margin:6px 0 6px 16px; padding:0; }}
            li    {{ margin:3px 0; line-height:1.5; }}
        """)
        self._chat_view.setHtml(
            f"<body><p style='color:{FG2};text-align:center;margin-top:40px;font-size:10pt;'>"
            f"🤖  <b style='color:{ACCENT}'>Qwen3-Coder</b> is ready to help with your LAMMPS simulations.<br>"
            f"<span style='font-size:9pt;color:{FG2}'>Ask anything — paste errors, request scripts, explain commands.</span>"
            f"</p></body>")
        lay.addWidget(self._chat_view, 1)

        # ── Context injection row ─────────────────────────────────────────
        ctx = QFrame()
        ctx.setStyleSheet(f"background:{BG2}; border-top:1px solid {BORDER};")
        cl = QHBoxLayout(ctx)
        cl.setContentsMargins(10, 6, 10, 6)
        cl.setSpacing(6)

        send_editor_btn = QPushButton("📄 Send Input Script")
        send_editor_btn.setToolTip("Attach the current editor content to your next message")
        send_editor_btn.clicked.connect(self._ai_attach_editor)
        cl.addWidget(send_editor_btn)

        send_log_btn = QPushButton("📋 Send Error Log")
        send_log_btn.setToolTip("Attach the last 120 lines of the run log to your next message")
        send_log_btn.clicked.connect(self._ai_attach_log)
        cl.addWidget(send_log_btn)

        send_thermo_btn = QPushButton("📊 Send Thermo Data")
        send_thermo_btn.setToolTip("Attach parsed thermo statistics to your next message")
        send_thermo_btn.clicked.connect(self._ai_attach_thermo)
        cl.addWidget(send_thermo_btn)

        cl.addStretch()

        self._ai_attach_lbl = QLabel("")
        self._ai_attach_lbl.setStyleSheet(f"color:{YELLOW}; font-size:8pt;")
        cl.addWidget(self._ai_attach_lbl)

        self._ai_clear_attach_btn = QPushButton("✕ Clear")
        self._ai_clear_attach_btn.setFixedWidth(60)
        self._ai_clear_attach_btn.setVisible(False)
        self._ai_clear_attach_btn.clicked.connect(self._ai_clear_attachment)
        cl.addWidget(self._ai_clear_attach_btn)

        lay.addWidget(ctx)

        # ── Input row ─────────────────────────────────────────────────────
        inp_frame = QFrame()
        inp_frame.setStyleSheet(f"background:{BG2}; border-top:1px solid {BORDER};")
        il = QHBoxLayout(inp_frame)
        il.setContentsMargins(10, 8, 10, 8)
        il.setSpacing(8)

        self._ai_input = QPlainTextEdit()
        self._ai_input.setPlaceholderText(
            "Ask about LAMMPS input scripts, force fields, errors, simulation setup…  "
            "(Shift+Enter for newline, Enter to send)")
        self._ai_input.setFixedHeight(72)
        self._ai_input.setFont(QFont(UI_FONT, 10))
        self._ai_input.setStyleSheet(
            f"background:{BG3}; color:{FG}; border:1px solid {BORDER};"
            f"border-radius:5px; padding:6px;")
        # Enter → send, Shift+Enter → newline
        self._ai_input.installEventFilter(self)
        il.addWidget(self._ai_input, 1)

        send_col = QVBoxLayout()
        send_col.setSpacing(4)

        self._ai_send_btn = QPushButton("Send ▶")
        self._ai_send_btn.setObjectName("run")
        self._ai_send_btn.setFixedWidth(80)
        self._ai_send_btn.clicked.connect(self._ai_send)
        send_col.addWidget(self._ai_send_btn)

        self._ai_stop_btn = QPushButton("■ Stop")
        self._ai_stop_btn.setObjectName("stop")
        self._ai_stop_btn.setFixedWidth(80)
        self._ai_stop_btn.setEnabled(False)
        self._ai_stop_btn.clicked.connect(self._ai_stop)
        send_col.addWidget(self._ai_stop_btn)
        send_col.addStretch()

        il.addLayout(send_col)
        lay.addWidget(inp_frame)

        # internal state
        self._ai_pending_attachment = ""

        # start model-list refresh + download-progress poll
        self._ai_refresh_models()
        self._start_dl_poll()

        return w

    # ── AI helpers ────────────────────────────────────────────────────────

    def _ai_refresh_models(self, prefer_model: str = ""):
        """Populate model combo from running Ollama instance."""
        if not HAS_OLLAMA:
            self._ai_status_lbl.setText("● ollama package missing")
            self._ai_status_lbl.setStyleSheet(f"color:{RED}; font-size:9pt;")
            return
        try:
            resp = _ollama_lib.list()
            models = ([m.model for m in resp.models] if hasattr(resp, "models")
                      else [m.get("model", m.get("name", "")) for m in resp.get("models", [])])
            models = [m for m in models if m]
            prev   = self._ai_model_cb.currentText()
            self._ai_model_cb.clear()
            if models:
                self._ai_model_cb.addItems(models)
                # priority: explicit prefer (after download) → previous → qwen3-coder → first
                target = next(
                    (m for m in [prefer_model, prev,
                                 next((m for m in models if "qwen3-coder" in m), None),
                                 models[0]]
                     if m and m in models), None)
                if target:
                    self._ai_model_cb.setCurrentIndex(models.index(target))
                self._ai_status_lbl.setText(
                    f"● {len(models)} model(s) — {self._ai_model_cb.currentText()}")
                self._ai_status_lbl.setStyleSheet(f"color:{GREEN}; font-size:9pt;")
            else:
                self._ai_model_cb.addItem("(no models — click ⬇ Get Model)")
                self._ai_status_lbl.setText("● No models downloaded")
                self._ai_status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")
        except Exception as exc:
            self._ai_status_lbl.setText(f"● Ollama not running: {exc}")
            self._ai_status_lbl.setStyleSheet(f"color:{RED}; font-size:9pt;")

    # ── Download model dialog + pull thread ───────────────────────────────

    _PRESET_MODELS = [
        ("qwen3-coder:latest",   "18 GB", "Best quality — same as bundled"),
        ("qwen2.5-coder:7b",      "4 GB", "Fast, good balance — recommended for most"),
        ("qwen2.5-coder:14b",     "9 GB", "Better quality, needs 12+ GB RAM"),
        ("qwen2.5-coder:32b",    "18 GB", "Highest quality, needs 32+ GB RAM"),
        ("llama3.2:3b",           "2 GB", "Tiny general model, very fast"),
        ("codellama:7b",          "4 GB", "Meta CodeLlama — good for C/Python"),
    ]

    def _ai_download_model(self):
        """Show model-picker dialog then start pulling."""
        if self._pull_thread and self._pull_thread.isRunning():
            QMessageBox.information(self, "Download in progress",
                "A model is already downloading. Please wait for it to finish.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Download Ollama Model")
        dlg.setMinimumWidth(500)
        dlg.setStyleSheet(f"background:{BG2}; color:{FG};")
        vl = QVBoxLayout(dlg)
        vl.setSpacing(10)
        vl.setContentsMargins(16, 16, 16, 16)

        vl.addWidget(QLabel(
            "Select a model to download, or type a custom model name.",
            styleSheet=f"color:{FG2}; font-size:9pt;"))

        # Preset table
        table = QTableWidget(len(self._PRESET_MODELS), 3)
        table.setHorizontalHeaderLabels(["Model", "Size", "Description"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setStyleSheet(
            f"background:{BG3}; color:{FG}; gridline-color:{BORDER};"
            f"selection-background-color:#1a3a5a;")
        table.horizontalHeader().setStyleSheet(
            f"background:{BG2}; color:{FG2}; font-size:9pt;")
        table.setFixedHeight(185)

        for row, (name, size, desc) in enumerate(self._PRESET_MODELS):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(size))
            table.setItem(row, 2, QTableWidgetItem(desc))
            # mark recommended
            if "recommended" in desc:
                for col in range(3):
                    table.item(row, col).setForeground(QColor(GREEN))
        table.selectRow(1)   # default: qwen2.5-coder:7b
        vl.addWidget(table)

        # Custom model name entry
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom:", styleSheet=f"color:{FG2};"))
        custom_edit = QLineEdit()
        custom_edit.setPlaceholderText("e.g. mistral:7b  or  phi3:mini")
        custom_edit.setStyleSheet(
            f"background:{BG3}; color:{FG}; border:1px solid {BORDER};"
            f"border-radius:4px; padding:4px 8px;")
        custom_row.addWidget(custom_edit)
        vl.addLayout(custom_row)

        vl.addWidget(QLabel(
            "💡 Custom names are passed directly to `ollama pull`. "
            "Browse all models at ollama.com/library",
            styleSheet=f"color:{FG2}; font-size:8pt;"))

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        dl_btn = QPushButton("⬇  Download")
        dl_btn.setStyleSheet(
            f"background:#1a3a1a; color:{GREEN}; border:1px solid {GREEN};"
            f"border-radius:4px; padding:5px 18px; font-weight:bold;")
        dl_btn.setDefault(True)
        dl_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(dl_btn)
        vl.addLayout(btn_row)

        if dlg.exec_() != QDialog.Accepted:
            return

        # Determine model name
        model = custom_edit.text().strip()
        if not model:
            row = table.currentRow()
            if row < 0:
                return
            model = self._PRESET_MODELS[row][0]

        self._start_pull(model)

    def _start_pull(self, model: str):
        """Begin pulling `model` via ModelPullThread and show progress bar."""
        if not HAS_OLLAMA:
            QMessageBox.warning(self, "Ollama missing",
                "The ollama Python package is not installed.\n"
                "Run:  pip install ollama")
            return

        self._dl_label.setText(f"⬇  Pulling {model}…")
        self._dl_bar.setValue(0)
        self._dl_pct_lbl.setText("…")
        self._dl_frame.setVisible(True)
        self._ai_status_lbl.setText(f"● Downloading {model}…")
        self._ai_status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")

        self._pull_thread = ModelPullThread(model)
        self._pull_thread.progress.connect(self._on_pull_progress)
        self._pull_thread.finished.connect(self._on_pull_finished)
        self._pull_thread.start()

    def _on_pull_progress(self, status: str, pct: int, done_gb: float, total_gb: float):
        if done_gb > 0 and total_gb > 0:
            label = (f"⬇  {self._pull_thread._model} — "
                     f"{done_gb:.2f} / {total_gb:.1f} GB")
        else:
            label = f"⬇  {status}…"
        self._dl_label.setText(label)
        self._dl_bar.setValue(pct)
        self._dl_pct_lbl.setText(f"{pct}%" if pct > 0 else "…")

    def _on_pull_finished(self, success: bool, model_or_err: str):
        self._dl_frame.setVisible(False)
        if success:
            self._ai_refresh_models(prefer_model=model_or_err)
        else:
            self._ai_status_lbl.setText(f"● Download failed")
            self._ai_status_lbl.setStyleSheet(f"color:{RED}; font-size:9pt;")
            QMessageBox.warning(self, "Download failed",
                f"Could not pull model:\n{model_or_err}")

    def _start_dl_poll(self):
        """Poll for a model download that was started outside the app (setup.sh)."""
        timer = QTimer(self)
        timer.timeout.connect(self._poll_download)
        timer.start(2000)
        self._dl_timer = timer
        self._poll_download()

    def _poll_download(self):
        """Legacy poller: watches /tmp/qwen3_pull.log for downloads started by setup.sh."""
        # Skip if we have an active in-app pull thread
        if self._pull_thread and self._pull_thread.isRunning():
            return

        log = "/tmp/qwen3_pull.log"

        # If any model is already available, hide bar and stop polling
        if HAS_OLLAMA:
            try:
                resp   = _ollama_lib.list()
                models = ([m.model for m in resp.models] if hasattr(resp, "models")
                          else [m.get("model", "") for m in resp.get("models", [])])
                models = [m for m in models if m]
                if models:
                    self._dl_frame.setVisible(False)
                    if self._dl_timer:
                        self._dl_timer.stop()
                    self._ai_refresh_models()
                    return
            except Exception:
                pass

        if not os.path.exists(log):
            return

        try:
            with open(log, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 6144))
                raw = f.read()
        except Exception:
            return

        content = _ANSI_RE.sub(" ", raw.decode("utf-8", errors="replace"))

        if "success" in content.lower():
            self._dl_frame.setVisible(False)
            if self._dl_timer:
                self._dl_timer.stop()
            self._ai_refresh_models()
            return

        size_matches = re.findall(
            r'(\d+(?:\.\d+)?)\s*(KB|MB|GB)\s*/\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB)',
            content)
        pct_matches  = re.findall(r'\b(\d{1,3})%', content)
        speed_match  = re.findall(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB)/s', content)
        eta_match    = re.findall(r'(\d+h\d+m|\d+m\d+s|\d+s)', content)

        if size_matches:
            def _to_gb(val, unit):
                v = float(val)
                return v if unit == "GB" else (v / 1024 if unit == "MB" else v / 1048576)
            dv, du, tv, tu = size_matches[-1]
            done_gb  = _to_gb(dv, du)
            total_gb = _to_gb(tv, tu)
            pct = int(pct_matches[-1]) if pct_matches else (
                min(int(done_gb / total_gb * 100), 99) if total_gb else 0)
            speed_str = (f"  {speed_match[-1][0]} {speed_match[-1][1]}/s"
                         if speed_match else "")
            eta_str   = f"  ETA {eta_match[-1]}" if eta_match else ""
            self._dl_frame.setVisible(True)
            self._dl_bar.setValue(min(pct, 99))
            self._dl_pct_lbl.setText(f"{pct}%")
            self._dl_label.setText(
                f"⬇  qwen3-coder — {done_gb:.2f} / {total_gb:.1f} GB"
                f"{speed_str}{eta_str}")
        elif "pulling" in content.lower():
            self._dl_frame.setVisible(True)
            self._dl_bar.setValue(0)
            self._dl_pct_lbl.setText("…")
            self._dl_label.setText("⬇  Pulling qwen3-coder manifest…")

        if re.search(r'\berror\b', content, re.I) and "pulling" not in content.lower():
            self._dl_bar.setValue(0)
            self._dl_label.setText("⚠  Download error — check terminal")
            if self._dl_timer:
                self._dl_timer.stop()

    # ── Send / stop ───────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """Intercept Enter in AI input to send the message."""
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QKeyEvent
        if obj is self._ai_input and event.type() == QEvent.KeyPress:
            if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and not (event.modifiers() & Qt.ShiftModifier)):
                self._ai_send()
                return True
        return super().eventFilter(obj, event)

    def _ai_send(self):
        text = self._ai_input.toPlainText().strip()
        if not text:
            return
        if self._ai_streamer and self._ai_streamer.isRunning():
            return

        model = self._ai_model_cb.currentText()
        if not model or "no models" in model:
            self._append_chat("system",
                "⚠ No model available yet. Wait for the download to finish "
                "or run:  ollama pull qwen3-coder:latest")
            return

        # Prepend any attachment
        full_text = text
        if self._ai_pending_attachment:
            full_text = self._ai_pending_attachment + "\n\n" + text
            self._ai_clear_attachment()

        self._ai_input.clear()

        # Show user bubble
        self._append_chat("user", text)

        # Build message list (system prompt + history + new message)
        messages = [{"role": "system", "content": LAMMPS_SYSTEM_PROMPT}]
        messages += self._ai_history
        messages.append({"role": "user", "content": full_text})
        self._ai_history.append({"role": "user", "content": full_text})

        # Start streaming
        self._ai_partial = ""
        self._append_chat("ai", "")          # placeholder bubble
        self._ai_send_btn.setEnabled(False)
        self._ai_stop_btn.setEnabled(True)
        self._ai_status_lbl.setText("● Thinking…")
        self._ai_status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")

        num_gpu = 0 if self._ai_cpu_chk.isChecked() else -1
        mode_txt = "CPU" if num_gpu == 0 else "GPU"
        self._ai_status_lbl.setText(f"● Thinking… [{mode_txt}]")

        self._ai_streamer = OllamaStreamer(model, messages, num_gpu=num_gpu)
        self._ai_streamer.token.connect(self._ai_on_token)
        self._ai_streamer.done.connect(self._ai_on_done)
        self._ai_streamer.error.connect(self._ai_on_error)
        self._ai_streamer.cuda_error.connect(self._ai_on_cuda_error)
        self._ai_streamer.start()

    def _ai_stop(self):
        if self._ai_streamer:
            self._ai_streamer.stop()

    def _ai_on_token(self, tok: str):
        self._ai_partial += tok

        # Update status label to show think vs. write phase
        if "<think>" in self._ai_partial and "</think>" not in self._ai_partial:
            self._ai_status_lbl.setText("● 💭 Thinking…")
            self._ai_status_lbl.setStyleSheet(f"color:#a0a8c0; font-size:9pt;")
        else:
            think, resp = self._split_think(self._ai_partial)
            if resp:
                self._ai_status_lbl.setText("● ✍ Writing…")
                self._ai_status_lbl.setStyleSheet(f"color:{ACCENT}; font-size:9pt;")

        # Batch display updates — at most once every 150 ms
        if not self._ai_update_pending:
            self._ai_update_pending = True
            QTimer.singleShot(150, self._ai_flush_display)

    def _ai_flush_display(self):
        """Called by QTimer — does the actual HTML update."""
        self._ai_update_pending = False
        self._chat_view.setHtml(self._build_full_html(streaming=True))
        sb = self._chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _ai_on_done(self):
        reply = self._ai_partial.strip()
        self._ai_history.append({"role": "assistant", "content": reply})
        if len(self._ai_history) > 40:
            self._ai_history = self._ai_history[-40:]
        self._ai_partial = ""
        self._ai_update_pending = False
        # Final render (no streaming cursor)
        self._chat_view.setHtml(self._build_full_html(streaming=False))
        sb = self._chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._ai_send_btn.setEnabled(True)
        self._ai_stop_btn.setEnabled(False)
        model = self._ai_model_cb.currentText().split(":")[0]
        self._ai_status_lbl.setText(f"● {model}  ready")
        self._ai_status_lbl.setStyleSheet(f"color:{GREEN}; font-size:9pt;")

    def _ai_on_cuda_error(self):
        """Fired when a GPU/CUDA crash is detected — auto-switch to CPU mode."""
        self._ai_cpu_chk.setChecked(True)
        self._ai_status_lbl.setText("● Switched to CPU mode")
        self._ai_status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")

    def _ai_on_error(self, msg: str):
        self._ai_partial = ""
        self._ai_send_btn.setEnabled(True)
        self._ai_stop_btn.setEnabled(False)

        if _CUDA_ERR_PAT.search(msg):
            # GPU failure — show friendly guidance, don't pollute history
            friendly = (
                "⚠ GPU error: the Ollama CUDA kernels require Ampere+ (SM 8.0+), "
                "but this GPU is Turing (SM 7.5).\n\n"
                "✔ CPU mode has been enabled automatically — click Send again."
            )
            self._append_chat("system", friendly)
            self._ai_status_lbl.setText("● GPU error — CPU mode on")
            self._ai_status_lbl.setStyleSheet(f"color:{YELLOW}; font-size:9pt;")
        else:
            self._ai_history.append({"role": "assistant", "content": f"[Error: {msg}]"})
            self._append_chat("system", f"⚠ Error: {msg}")
            self._ai_status_lbl.setText("● Error")
            self._ai_status_lbl.setStyleSheet(f"color:{RED}; font-size:9pt;")

    # ── Context attachment ────────────────────────────────────────────────

    def _ai_attach_editor(self):
        content = self._editor.toPlainText().strip()
        if not content:
            self._ai_status_lbl.setText("● Editor is empty")
            return
        fname = os.path.basename(self._current_file) if self._current_file else "input_script"
        self._ai_pending_attachment = (
            f"[Attached LAMMPS input file: {fname}]\n```lammps\n{content}\n```"
        )
        self._ai_attach_lbl.setText(f"📄 {fname} attached")
        self._ai_clear_attach_btn.setVisible(True)

    def _ai_attach_log(self):
        log_text = self._log.toPlainText().strip()
        if not log_text:
            self._ai_status_lbl.setText("● Log is empty — run a simulation first")
            return
        # Last 120 lines
        lines = log_text.splitlines()[-120:]
        self._ai_pending_attachment = (
            "[Attached LAMMPS run log (last 120 lines)]\n```\n"
            + "\n".join(lines)
            + "\n```"
        )
        self._ai_attach_lbl.setText("📋 Run log attached")
        self._ai_clear_attach_btn.setVisible(True)

    def _ai_attach_thermo(self):
        if not self._thermo_data or not self._thermo_data.get("headers"):
            self._ai_status_lbl.setText("● No thermo data — load a log file first")
            return
        headers = self._thermo_data["headers"]
        data    = self._thermo_data["data"]
        n       = len(data.get(headers[0], []))
        lines   = ["\t".join(headers)]
        # Show first 5, last 5 rows
        indices = list(range(min(5, n))) + (list(range(max(5, n - 5), n)) if n > 10 else [])
        for i in indices:
            lines.append("\t".join(f"{data[h][i]:.4g}" if i < len(data.get(h, [])) else "—"
                                   for h in headers))
        self._ai_pending_attachment = (
            f"[Attached thermo data ({n} steps, {len(headers)} columns)]\n```\n"
            + "\n".join(lines) + "\n```"
        )
        self._ai_attach_lbl.setText("📊 Thermo data attached")
        self._ai_clear_attach_btn.setVisible(True)

    def _ai_clear_attachment(self):
        self._ai_pending_attachment = ""
        self._ai_attach_lbl.setText("")
        self._ai_clear_attach_btn.setVisible(False)

    # ── Chat rendering ────────────────────────────────────────────────────

    @staticmethod
    def _split_think(text: str):
        """Return (thinking_text, response_text) parsed from Qwen3 <think> tags."""
        # Completed thinking block
        m = re.match(r"^<think>(.*?)</think>(.*)", text, re.DOTALL)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        # Still inside thinking (no closing tag yet)
        m = re.match(r"^<think>(.*)", text, re.DOTALL)
        if m:
            return m.group(1).strip(), ""
        # No thinking tags — everything is the response
        return "", text

    def _append_chat(self, role: str, text: str):
        """Re-render the full chat (used for system messages and one-shot additions)."""
        self._chat_view.setHtml(self._build_full_html(streaming=False, extra_sys=text if role == "system" else None))
        sb = self._chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _build_full_html(self, streaming: bool = False, extra_sys: str = None) -> str:
        """Render the full conversation as HTML, think-aware."""
        model_name = self._ai_model_cb.currentText().split(":")[0] if hasattr(self, "_ai_model_cb") else "AI"
        parts = ["<body>"]

        for msg in self._ai_history:
            role    = msg["role"]
            content = msg["content"]
            if role == "user":
                parts.append(self._render_user_bubble(content))
            elif role == "assistant":
                parts.append(self._render_ai_bubble(content, model_name, streaming=False))

        # Live streaming partial
        if streaming and self._ai_partial:
            parts.append(self._render_ai_bubble(self._ai_partial, model_name, streaming=True))

        # One-off system message (errors, notices)
        if extra_sys:
            import html as _html
            safe = _html.escape(extra_sys).replace("\n", "<br>")
            parts.append(f'<div class="sys">{safe}</div>')

        parts.append("</body>")
        return "\n".join(parts)

    def _render_user_bubble(self, text: str) -> str:
        return (f'<div class="user"><div class="role">👤 You</div>'
                f'{self._md_to_html(text)}</div>')

    def _render_ai_bubble(self, raw: str, model_name: str, streaming: bool) -> str:
        thinking, response = self._split_think(raw)
        import html as _hl
        parts = [f'<div class="ai"><div class="role">🤖 {model_name}</div>']

        if thinking:
            escaped_think = _hl.escape(thinking).replace("\n", "<br>")
            still_thinking = streaming and not response
            hdr = "💭 Thinking…" if still_thinking else "💭 Thinking  (done)"
            cursor_span = '<span style="color:#505878;">▌</span>' if still_thinking else ""
            parts.append(
                f'<div class="thinking">'
                f'<div class="think-hdr">{hdr}</div>'
                f'<div class="think-body">{escaped_think}{cursor_span}</div>'
                f'</div>'
            )

        if response:
            parts.append(self._md_to_html(response))
            if streaming:
                parts.append(f'<span style="color:{ACCENT}; font-size:11pt;">▌</span>')
        elif not thinking:
            # No think tags at all — everything is the response
            parts.append(self._md_to_html(raw))
            if streaming:
                parts.append(f'<span style="color:{ACCENT}; font-size:11pt;">▌</span>')

        parts.append('</div>')
        return "".join(parts)

    @staticmethod
    def _md_to_html(text: str) -> str:
        """Markdown → HTML: fenced code blocks, inline code, bold, italic, newlines."""
        import html as _html

        def _code_block(m):
            lang = m.group(1) or ""
            code = _html.escape(m.group(2))
            return f'<pre><code class="lang-{lang}">{code}</code></pre>'

        # Fenced code blocks  ```lang\n…\n```
        text = re.sub(r"```(\w*)\n(.*?)```", _code_block, text, flags=re.DOTALL)
        # Inline code
        text = re.sub(r"`([^`\n]+)`",
                      lambda m: f"<code>{_html.escape(m.group(1))}</code>", text)
        # Bold / italic
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
        text = re.sub(r"\*\*(.+?)\*\*",     r"<b>\1</b>",         text)
        text = re.sub(r"\*(.+?)\*",          r"<i>\1</i>",         text)
        # Markdown bullet lists: "- item" → <li>
        lines, in_list = [], False
        for line in text.splitlines():
            if re.match(r"^\s*[-*]\s+", line):
                if not in_list:
                    lines.append("<ul>"); in_list = True
                lines.append(f"<li>{line.lstrip('- *').strip()}</li>")
            else:
                if in_list:
                    lines.append("</ul>"); in_list = False
                lines.append(line)
        if in_list:
            lines.append("</ul>")
        text = "\n".join(lines)
        # Newlines → <br> (outside pre blocks — re.sub limited)
        text = re.sub(r"(?<!>)\n", "<br>", text)
        return f"<p>{text}</p>"

    def _ai_clear_chat(self):
        self._ai_history  = []
        self._ai_partial  = ""
        self._ai_update_pending = False
        self._chat_view.setHtml(
            f"<body><p style='color:{FG2};text-align:center;margin-top:40px;font-size:10pt;'>"
            f"Chat cleared. Start a new conversation.</p></body>")

    # ── Remote helpers ────────────────────────────────────────────────────

    def _is_remote(self) -> bool:
        """True when an SSH session is active — all I/O should go to server."""
        return bool(self._ssh and self._ssh.connected)

    def _update_run_target(self):
        """Refresh the run-target indicator bar in the Run tab."""
        if not hasattr(self, "_run_target_lbl"):
            return
        if self._is_remote():
            p = self._ssh.profile
            if self._hpc_mode:
                self._run_target_lbl.setText(
                    f"⚡  HPC mode — jobs submit via  sbatch  on  {p.host}"
                )
                self._run_target_lbl.setStyleSheet(f"color:{YELLOW}; font-size:8.5pt; font-weight:700;")
                self._run_target_bar.setStyleSheet(
                    f"background:#1c1a0e; border-bottom:1px solid #5a4a00;"
                )
                self._btn_run.setText("⚡   Go to HPC Submit")
                self._btn_run.setToolTip("Opens HPC tab to configure and submit SLURM job")
            else:
                self._run_target_lbl.setText(
                    f"▶  Run target:  🟢  SSH — {p.username}@{p.host}:{p.port}"
                )
                self._run_target_lbl.setStyleSheet(f"color:{GREEN}; font-size:8.5pt; font-weight:600;")
                self._run_target_bar.setStyleSheet(
                    f"background:#111c14; border-bottom:1px solid #2a5535;"
                )
                self._btn_run.setText("▶   Run on SSH")
                self._btn_run.setToolTip(f"Run on {p.host} via SSH")
        else:
            self._run_target_lbl.setText("▶  Run target:  💻  Local machine")
            self._run_target_lbl.setStyleSheet(f"color:{FG2}; font-size:8.5pt;")
            self._run_target_bar.setStyleSheet(
                f"background:#131620; border-bottom:1px solid {BORDER};"
            )
            self._btn_run.setText("▶   Run Simulation")
            self._btn_run.setToolTip("Run locally")

    def _sftp_pick_file(self, title="Open Remote File") -> str:
        """Open SFTPFilePicker; return selected path or ''."""
        start = self._ssh_remote_cwd or self._ssh.get_home()
        dlg   = SFTPFilePicker(self._ssh, start, self, mode="file")
        dlg.setWindowTitle(title)
        return dlg.selected_path if dlg.exec_() else ""

    def _sftp_pick_dir(self, title="Select Remote Directory") -> str:
        start = self._ssh_remote_cwd or self._ssh.get_home()
        dlg   = SFTPFilePicker(self._ssh, start, self, mode="dir")
        dlg.setWindowTitle(title)
        return dlg.selected_path if dlg.exec_() else ""

    # ── Misc ──────────────────────────────────────────────────────────────
    def _set_status(self, text, color):
        self._status_pill.setText(f"  {text}  ")
        self._status_pill.setStyleSheet(
            f"color:{color}; font-size:8.5pt; font-weight:600;"
            f"background:#22263a; border:1px solid {color}44;"
            f"border-radius:10px; padding:2px 6px;"
        )

    def closeEvent(self, event):
        if self._runner and self._runner.isRunning():
            ans = QMessageBox.question(
                self, "Quit",
                "A simulation is running. Kill it and exit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self._runner.kill()
            else:
                event.ignore()
                return
        event.accept()


def _vline():
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setStyleSheet(f"color:{BORDER}; max-width:1px;")
    return line


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(_pal())
    app.setStyleSheet(STYLE)

    # Load icon (multi-resolution via make_icon, fallback to PNG)
    try:
        from make_icon import build_icon
        icon = build_icon()
    except Exception:
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        icon = QIcon(_icon_path)

    app.setWindowIcon(icon)

    win = LAMMPSDashboard()
    win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec_())

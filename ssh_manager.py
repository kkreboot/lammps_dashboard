"""SSH / SFTP manager for the LAMMPS Dashboard."""

from __future__ import annotations
import json
import os
import stat
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterator, List, Optional

import paramiko

PROFILES_PATH = Path.home() / ".lammps_dashboard" / "ssh_profiles.json"


# ── Profile ────────────────────────────────────────────────────────────────────

@dataclass
class SSHProfile:
    name:     str   = "New Server"
    host:     str   = ""
    port:     int   = 22
    username: str   = ""
    auth:     str   = "password"   # "password" | "key"
    password: str   = ""           # stored in memory only (not saved to disk)
    key_path: str   = ""

    def display(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("password", None)    # never persist passwords
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SSHProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Profile store ──────────────────────────────────────────────────────────────

def load_profiles() -> List[SSHProfile]:
    try:
        with open(PROFILES_PATH) as f:
            data = json.load(f)
        return [SSHProfile.from_dict(p) for p in data.get("profiles", [])]
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return []


def save_profiles(profiles: List[SSHProfile]) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_PATH, "w") as f:
        json.dump({"profiles": [p.to_dict() for p in profiles]}, f, indent=2)


# ── Remote file entry ──────────────────────────────────────────────────────────

@dataclass
class RemoteEntry:
    name:   str
    path:   str
    is_dir: bool
    size:   int = 0


# ── SSH Manager ────────────────────────────────────────────────────────────────

class SSHManager:
    """Wraps a single Paramiko SSH + SFTP session."""

    def __init__(self):
        self._client:  Optional[paramiko.SSHClient] = None
        self._sftp:    Optional[paramiko.SFTPClient] = None
        self._profile: Optional[SSHProfile]         = None
        self._lock     = threading.Lock()

    # ── Connection ─────────────────────────────────────────────────────────

    def connect(self, profile: SSHProfile) -> None:
        """Raise on failure."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kw: dict = dict(
            hostname=profile.host,
            port=profile.port,
            username=profile.username,
            timeout=15,
            banner_timeout=30,
        )
        if profile.auth == "key" and profile.key_path:
            kw["key_filename"] = os.path.expanduser(profile.key_path)
        else:
            kw["password"] = profile.password

        client.connect(**kw)

        with self._lock:
            if self._sftp:
                self._sftp.close()
            if self._client:
                self._client.close()
            self._client  = client
            self._sftp    = client.open_sftp()
            self._profile = profile

    def disconnect(self) -> None:
        with self._lock:
            if self._sftp:
                try: self._sftp.close()
                except Exception: pass
                self._sftp = None
            if self._client:
                try: self._client.close()
                except Exception: pass
                self._client = None
            self._profile = None

    @property
    def connected(self) -> bool:
        with self._lock:
            if not self._client:
                return False
            transport = self._client.get_transport()
            return transport is not None and transport.is_active()

    @property
    def profile(self) -> Optional[SSHProfile]:
        return self._profile

    # ── SFTP file operations ───────────────────────────────────────────────

    def list_dir(self, path: str) -> List[RemoteEntry]:
        entries: List[RemoteEntry] = []
        with self._lock:
            for attr in self._sftp.listdir_attr(path):
                name   = attr.filename
                is_dir = stat.S_ISDIR(attr.st_mode or 0)
                entries.append(RemoteEntry(
                    name=name,
                    path=path.rstrip("/") + "/" + name,
                    is_dir=is_dir,
                    size=attr.st_size or 0,
                ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def read_file(self, remote_path: str) -> str:
        with self._lock:
            with self._sftp.open(remote_path, "r") as f:
                return f.read().decode("utf-8", errors="replace")

    def write_file(self, remote_path: str, content: str) -> None:
        with self._lock:
            with self._sftp.open(remote_path, "w") as f:
                f.write(content.encode("utf-8"))

    def mkdir(self, remote_path: str) -> None:
        with self._lock:
            self._sftp.mkdir(remote_path)

    def get_home(self) -> str:
        _, stdout, _ = self._client.exec_command("echo $HOME")
        return stdout.read().decode().strip() or "/"

    def upload(self, local_path: str, remote_path: str) -> None:
        with self._lock:
            self._sftp.put(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> None:
        with self._lock:
            self._sftp.get(remote_path, local_path)

    # ── Remote command execution (streaming) ───────────────────────────────

    def exec_stream(
        self,
        cmd: str,
        cwd: str = "",
        on_line: Callable[[str], None] = lambda _: None,
        on_done: Callable[[int], None]  = lambda _: None,
    ) -> None:
        """Run cmd on the remote host; call on_line for each stdout line.

        This is blocking — call from a worker thread.
        """
        full_cmd = f"cd {cwd!r} && {cmd}" if cwd else cmd
        transport = self._client.get_transport()
        channel   = transport.open_session()
        channel.get_pty()
        channel.set_combine_stderr(True)
        channel.exec_command(full_cmd)

        buf = b""
        while True:
            chunk = channel.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                on_line(line.decode("utf-8", errors="replace").rstrip())

        if buf:
            on_line(buf.decode("utf-8", errors="replace").rstrip())

        rc = channel.recv_exit_status()
        channel.close()
        on_done(rc)

    def kill_remote(self, pattern: str = "lmp") -> None:
        """Best-effort kill of remote lmp / mpirun processes."""
        try:
            self._client.exec_command(f"pkill -f {pattern}")
        except Exception:
            pass

    # ── Test connection (returns error string or None) ─────────────────────

    @staticmethod
    def test(profile: SSHProfile) -> Optional[str]:
        try:
            mgr = SSHManager()
            mgr.connect(profile)
            mgr.disconnect()
            return None
        except Exception as exc:
            return str(exc)

import os, sys, json, ctypes, subprocess, tempfile, shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

APP_DIR = Path(os.environ.get("APPDATA", r".")) / "WSLCompact"
APP_DIR.mkdir(parents=True, exist_ok=True)
CFG_PATH = APP_DIR / "config.json"

# ---------- helpers ----------
def is_windows():
    return os.name == "nt"

def is_admin():
    if not is_windows():
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def relaunch_elevated():
    """Relaunch current script with admin rights (for local runs)."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

def run(cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, text=True,
                          capture_output=capture)

def wsl_root(distro, bash_cmd, check=True):
    """Run a bash command as root inside the distro."""
    return run(["wsl","-d",distro,"-u","root","-e","bash","-lc",bash_cmd], check=check, capture=True)

def get_default_distro():
    cp = run(["wsl","-l","-v"], capture=True)
    for line in cp.stdout.splitlines():
        if line.strip().startswith("*"):
            parts = line.strip().split()
            # "* Ubuntu-22.04   Running ..."
            return parts[1]
    cp2 = run(["wsl","-l","-q"], capture=True)
    names = [l.strip() for l in cp2.stdout.splitlines() if l.strip()]
    if not names:
        raise RuntimeError("No WSL distros found.")
    return names[0]

def get_vhd_for_distro(distro):
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i); i += 1
            except OSError:
                break
            with winreg.OpenKey(k, sub) as sk:
                try:
                    name, _ = winreg.QueryValueEx(sk, "DistributionName")
                    if name == distro:
                        base_path, _ = winreg.QueryValueEx(sk, "BasePath")
                        p = Path(base_path) / "ext4.vhdx"
                        if p.exists():
                            return p
                except FileNotFoundError:
                    continue
    raise FileNotFoundError(f"VHD not found for distro {distro}")

def user_active(distro, username):
    """
    Return True if any process exists for the user (best-effort).
    """
    # If user doesn't exist, treat as inactive.
    cmd = f'if id -u {username} >/dev/null 2>&1; then pgrep -u {username} >/dev/null 2>&1; echo $?; else echo 1; fi'
    cp = wsl_root(distro, cmd, check=False)
    return cp.stdout.strip().endswith("0")

def logout_user(distro, username):
    """
    Force logout by killing all processes of the user. Best-effort and safe to run even if no procs.
    """
    wsl_root(distro, f'if id -u {username} >/dev/null 2>&1; then pkill -KILL -u {username} || true; fi', check=False)

def terminate_wsl(distro):
    run(["wsl","--terminate",distro], check=False)
    run(["wsl","--shutdown"], check=False)

def run_diskpart_compact(vhd_path: Path):
    script = f"""select vdisk file="{vhd_path}"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as tf:
        tf.write(script)
        p = tf.name
    try:
        cp = run(["diskpart.exe","/s",p], check=True, capture=True)
        return cp.stdout
    finally:
        try: os.remove(p)
        except OSError: pass

def relaunch_distro(distro, username):
    # Non-interactive background start so the distro is "up" for that user.
    subprocess.Popen(["wsl","-d",distro,"-u",username])

# ---------- worker ----------
class Worker(QThread):
    log = Signal(str)
    done = Signal(str, bool)  # message, ok?

    def __init__(self, distro, username, vhd_path, relaunch_after):
        super().__init__()
        self.distro = distro
        self.username = username
        self.vhd_path = Path(vhd_path)
        self.relaunch_after = relaunch_after

    def emit(self, msg):  # convenience
        self.log.emit(msg)

    def run(self):
        try:
            self.emit(f"Target distro: {self.distro}")
            self.emit(f"Target user: {self.username}")
            self.emit(f"VHDX: {self.vhd_path}")

            if not self.vhd_path.exists():
                self.done.emit(f"VHD file not found: {self.vhd_path}", False)
                return

            # 1) Detect activity
            self.emit("Checking for active user processes…")
            active = False
            try:
                active = user_active(self.distro, self.username)
            except Exception as e:
                self.emit(f"Warning: activity check failed ({e}); continuing.")

            # 2) Log out (force)
            if active:
                self.emit("User appears active; logging out (killing all processes)…")
            else:
                self.emit("No active processes detected for user; proceeding to shutdown.")

            try:
                logout_user(self.distro, self.username)
            except Exception as e:
                self.emit(f"Warning: logout attempt failed ({e}); continuing.")

            # Re-check
            try:
                still_active = user_active(self.distro, self.username)
                self.emit("Logout verification: " + ("FAILED (still active)" if still_active else "OK"))
            except Exception as e:
                self.emit(f"Warning: could not re-verify logout ({e}).")

            # 3) Clean shutdown
            self.emit("Stopping WSL…")
            terminate_wsl(self.distro)

            # 4) Compact
            self.emit("Compacting VHD (DiskPart)…")
            out = run_diskpart_compact(self.vhd_path)
            self.emit(out if out else "DiskPart finished.")

            # 5) Optional relaunch
            if self.relaunch_after:
                self.emit("Relaunching distro…")
                try:
                    relaunch_distro(self.distro, self.username)
                    self.emit("Relaunch requested.")
                except Exception as e:
                    self.emit(f"Warning: relaunch failed ({e})")

            self.done.emit("Done.", True)
        except Exception as e:
            self.done.emit(f"Error: {e}", False)

# ---------- UI ----------
class MainWin(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WSL Compact (PySide6)")

        form = QFormLayout()
        self.distro = QLineEdit("Ubuntu")
        self.username = QLineEdit("ubuntu")
        self.vhd = QLineEdit("")
        self.relaunch = QCheckBox("Relaunch distro after compaction")
        self.relaunch.setChecked(True)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self.pick_vhd)

        form.addRow("Distro:", self.distro)
        form.addRow("Username:", self.username)
        # VHD field + browse stacked
        vhd_row = QWidget(); vbox = QVBoxLayout(vhd_row); vbox.setContentsMargins(0,0,0,0)
        vbox.addWidget(self.vhd); vbox.addWidget(browse)
        form.addRow("VHDX:", vhd_row)
        form.addRow("", self.relaunch)

        self.runbtn = QPushButton("Run")
        self.runbtn.clicked.connect(self.run_clicked)
        self.log = QTextEdit(); self.log.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.runbtn)
        layout.addWidget(self.log)

        # Load config
        if CFG_PATH.exists():
            try:
                cfg = json.loads(CFG_PATH.read_text())
                self.distro.setText(cfg.get("distro","Ubuntu"))
                self.username.setText(cfg.get("username","ubuntu"))
                self.vhd.setText(cfg.get("vhd",""))
                self.relaunch.setChecked(bool(cfg.get("relaunch", True)))
            except: pass

        # Best-effort auto-detect VHD on first run
        if not self.vhd.text() and is_windows():
            try:
                self.vhd.setText(str(get_vhd_for_distro(self.distro.text().strip() or "Ubuntu")))
            except: pass

    def pick_vhd(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select ext4.vhdx", str(Path.home()), "VHDX (*.vhdx)")
        if p: self.vhd.setText(p)

    def run_clicked(self):
        # Save config
        CFG_PATH.write_text(json.dumps({
            "distro": self.distro.text().strip() or "Ubuntu",
            "username": self.username.text().strip() or "ubuntu",
            "vhd": self.vhd.text().strip(),
            "relaunch": self.relaunch.isChecked()
        }, indent=2))

        if not is_windows():
            QMessageBox.critical(self, "Error", "This tool must run on Windows.")
            return

        # If not admin (e.g., running from source), relaunch elevated
        if not is_admin():
            relaunch_elevated()

        distro = self.distro.text().strip() or "Ubuntu"
        username = self.username.text().strip() or "ubuntu"
        vhd = self.vhd.text().strip()

        if not vhd:
            try:
                vhd = str(get_vhd_for_distro(distro))
                self.vhd.setText(vhd)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"VHD not found: {e}")
                return

        self.runbtn.setEnabled(False)
        self.worker = Worker(distro, username, vhd, self.relaunch.isChecked())
        self.worker.log.connect(lambda s: self.log.append(s))
        self.worker.done.connect(self.finish)
        self.worker.start()

    def finish(self, msg, ok):
        self.log.append(msg)
        if not ok:
            QMessageBox.critical(self, "Result", msg)
        else:
            QMessageBox.information(self, "Result", msg)
        self.runbtn.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWin(); w.resize(600, 440); w.show()
    sys.exit(app.exec())

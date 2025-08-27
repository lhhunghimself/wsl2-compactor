import os, sys, json, ctypes, subprocess, tempfile, textwrap
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

APP_DIR = Path(os.environ.get("APPDATA", r".")) / "WSLCompact"
APP_DIR.mkdir(parents=True, exist_ok=True)
CFG_PATH = APP_DIR / "config.json"

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def relaunch_elevated():
    # Relaunch current script with admin rights
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

def ensure_wsl():
    if not shutil.which("wsl.exe"):
        raise RuntimeError("wsl.exe not found")

def get_default_distro():
    cp = subprocess.run(["wsl","-l","-v"], capture_output=True, text=True, check=True)
    for line in cp.stdout.splitlines():
        if line.strip().startswith("*"):
            return line.strip().split()[1]
    cp2 = subprocess.run(["wsl","-l","-q"], capture_output=True, text=True, check=True)
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
                        if not p.exists():
                            raise FileNotFoundError(p)
                        return p
                except FileNotFoundError:
                    continue
    raise FileNotFoundError(f"VHD not found for distro {distro}")

def run_powershell(script, check=True):
    cp = subprocess.run(
        ["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-Command",script],
        text=True, capture_output=True
    )
    if check and cp.returncode != 0:
        raise RuntimeError(f"PowerShell failed:\n{cp.stdout}\n{cp.stderr}")
    return cp

def has_optimize_vhd():
    ps = "if (Get-Command Optimize-VHD -ErrorAction SilentlyContinue) { 0 } else { 1 }"
    return run_powershell(ps, check=False).returncode == 0

def run_optimize_vhd(vhd):
    ps = f"""
$ErrorActionPreference='Stop'
Mount-VHD -Path "{vhd}" -ReadOnly -NoDriveLetter | Out-Null
try {{ Optimize-VHD -Path "{vhd}" -Mode Full }} finally {{ Dismount-VHD -Path "{vhd}" -Confirm:$false }}
"""
    run_powershell(ps)

def run_diskpart_compact(vhd):
    script = f"""select vdisk file="{vhd}"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as tf:
        tf.write(script)
        p = tf.name
    try:
        subprocess.run(["diskpart.exe","/s",p], check=True)
    finally:
        try: os.remove(p)
        except OSError: pass

def fstrim(distro, user="root", skip=False):
    if skip: return
    subprocess.run(["wsl","-d",distro,"-u",user,"-e","bash","-lc","fstrim -av || true"], check=False)

def terminate(distro):
    subprocess.run(["wsl","--terminate",distro], check=False)
    subprocess.run(["wsl","--shutdown"], check=False)

def relaunch(distro):
    subprocess.Popen(["wsl","-d",distro])

class Worker(QThread):
    log = Signal(str)
    done = Signal(str)

    def __init__(self, distro, vhd, do_trim=True):
        super().__init__()
        self.distro = distro
        self.vhd = vhd
        self.do_trim = do_trim

    def run(self):
        try:
            self.log.emit("Running fstrim (best effort)…")
            fstrim(self.distro, skip=not self.do_trim)
            self.log.emit("Stopping WSL…")
            terminate(self.distro)
            self.log.emit(f"Compacting: {self.vhd}")
            if has_optimize_vhd():
                try:
                    self.log.emit("Using Optimize-VHD…")
                    run_optimize_vhd(self.vhd)
                except Exception as e:
                    self.log.emit(f"Optimize-VHD failed ({e}); falling back to DiskPart…")
                    run_diskpart_compact(self.vhd)
            else:
                self.log.emit("Using DiskPart…")
                run_diskpart_compact(self.vhd)
            self.log.emit("Relaunching distro…")
            relaunch(self.distro)
            self.done.emit("Done.")
        except Exception as e:
            self.done.emit(f"Error: {e}")

class MainWin(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WSL Compact")
        form = QFormLayout()
        self.distro = QLineEdit("Ubuntu")
        self.username = QLineEdit("ubuntu")
        self.vhd = QLineEdit("")
        self.trim = QCheckBox("Run fstrim before compact"); self.trim.setChecked(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.pick_vhd)

        form.addRow("Distro:", self.distro)
        form.addRow("Username:", self.username)
        row = QWidget(); rr = QVBoxLayout(row); rr.setContentsMargins(0,0,0,0)
        rr.addWidget(self.vhd); rr.addWidget(browse)
        form.addRow("VHDX:", row)
        form.addRow("", self.trim)

        self.runbtn = QPushButton("Compact Now")
        self.runbtn.clicked.connect(self.run_clicked)
        self.log = QTextEdit(); self.log.setReadOnly(True)

        lay = QVBoxLayout(self)
        lay.addLayout(form); lay.addWidget(self.runbtn); lay.addWidget(self.log)

        # Load config
        if CFG_PATH.exists():
            try:
                cfg = json.loads(CFG_PATH.read_text())
                self.distro.setText(cfg.get("distro","Ubuntu"))
                self.username.setText(cfg.get("username","ubuntu"))
                self.vhd.setText(cfg.get("vhd",""))
            except: pass
        if not self.vhd.text():
            # best-effort auto-detect on first launch
            try:
                self.vhd.setText(str(get_vhd_for_distro(self.distro.text())))
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
        }, indent=2))

        if os.name != "nt":
            QMessageBox.critical(self, "Error", "This must run on Windows.")
            return
        if not is_admin():
            # relaunch elevated and exit
            relaunch_elevated()

        distro = self.distro.text().strip() or "Ubuntu"
        vhd = self.vhd.text().strip()
        if not vhd:
            try: vhd = str(get_vhd_for_distro(distro))
            except Exception as e:
                QMessageBox.critical(self,"Error",f"VHD not found: {e}")
                return

        self.runbtn.setEnabled(False)
        self.worker = Worker(distro, vhd, self.trim.isChecked())
        self.worker.log.connect(lambda s: self.log.append(s))
        self.worker.done.connect(self.finish)
        self.worker.start()

    def finish(self, msg):
        self.log.append(msg)
        self.runbtn.setEnabled(True)

if __name__ == "__main__":
    import shutil
    app = QApplication(sys.argv)
    w = MainWin(); w.resize(560, 420); w.show()
    sys.exit(app.exec())

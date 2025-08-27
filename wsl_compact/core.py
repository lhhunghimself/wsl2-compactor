"""
WSL Compact Core - Core compaction logic without GUI dependencies

This module contains all the WSL2 VHDX compaction logic extracted from the main GUI application.
It can be used standalone for CLI operations or testing.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

# Global configuration
APP_DIR = Path(os.environ.get("APPDATA", r".")) / "WSLCompact"
APP_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "latest.txt"

# Global dry-run flag
DRY_RUN = False


def log_message(msg):
    """Log message to both console and log file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    
    # Print to console
    print(log_entry)
    
    # Write to log file
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception:
        pass  # Fail silently if logging fails


def is_windows():
    """Check if running on Windows."""
    return os.name == "nt"


def is_admin():
    """Check if running with administrator privileges."""
    if not is_windows():
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_elevated():
    """Relaunch current script with admin rights (for local runs)."""
    import ctypes
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)


def run(cmd, check=True, capture=False):
    """Run a subprocess command."""
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def wsl_root(distro, bash_cmd, check=True):
    """Run a bash command as root inside the distro."""
    return run(["wsl", "-d", distro, "-u", "root", "-e", "bash", "-lc", bash_cmd], check=check, capture=True)


def get_default_distro():
    """Get the default WSL distro."""
    cp = run(["wsl", "-l", "-v"], capture=True)
    for line in cp.stdout.splitlines():
        if line.strip().startswith("*"):
            parts = line.strip().split()
            # "* Ubuntu-22.04   Running ..."
            return parts[1]
    cp2 = run(["wsl", "-l", "-q"], capture=True)
    names = [l.strip() for l in cp2.stdout.splitlines() if l.strip()]
    if not names:
        raise RuntimeError("No WSL distros found.")
    return names[0]


def get_vhd_for_distro(distro):
    """Get the VHD path for a specific distro from the Windows registry."""
    if not is_windows():
        raise RuntimeError("VHD detection only works on Windows")
    
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\Lxss"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
                i += 1
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
    if DRY_RUN:
        log_message(f"[DRY-RUN] Would kill all processes for user {username} in distro {distro}")
        return
    wsl_root(distro, f'if id -u {username} >/dev/null 2>&1; then pkill -KILL -u {username} || true; fi', check=False)


def terminate_wsl(distro):
    """Terminate the WSL distro and shutdown WSL."""
    if DRY_RUN:
        log_message(f"[DRY-RUN] Would terminate WSL distro {distro} and shutdown WSL")
        return
    run(["wsl", "--terminate", distro], check=False)
    run(["wsl", "--shutdown"], check=False)


def run_diskpart_compact(vhd_path: Path):
    """Run DiskPart to compact the VHD file."""
    script = f"""select vdisk file="{vhd_path}"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"""
    if DRY_RUN:
        log_message(f"[DRY-RUN] Would run DiskPart compact on {vhd_path}")
        log_message(f"[DRY-RUN] DiskPart script would be:\n{script}")
        return "[DRY-RUN] DiskPart compact simulation completed"
    
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as tf:
        tf.write(script)
        p = tf.name
    try:
        cp = run(["diskpart.exe", "/s", p], check=True, capture=True)
        return cp.stdout
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def relaunch_distro(distro, username):
    """Relaunch the WSL distro for the specified user."""
    # Non-interactive background start so the distro is "up" for that user.
    if DRY_RUN:
        log_message(f"[DRY-RUN] Would relaunch WSL distro {distro} for user {username}")
        return
    subprocess.Popen(["wsl", "-d", distro, "-u", username])


class CompactionResult:
    """Result of a compaction operation."""
    def __init__(self, success: bool, message: str, log_entries: list = None):
        self.success = success
        self.message = message
        self.log_entries = log_entries or []


def compact_wsl_vhd(distro: str, username: str, vhd_path: str, relaunch_after: bool = True, dry_run: bool = False) -> CompactionResult:
    """
    Core compaction logic - extracted from the Worker.run() method.
    
    Args:
        distro: WSL distro name (e.g., "Ubuntu")
        username: Username to logout (e.g., "ubuntu")
        vhd_path: Path to the VHDX file to compact
        relaunch_after: Whether to relaunch the distro after compaction
        dry_run: Whether to simulate operations without actually performing them
    
    Returns:
        CompactionResult with success status and messages
    """
    global DRY_RUN
    DRY_RUN = dry_run
    
    log_entries = []
    
    def emit_log(msg):
        log_message(msg)
        log_entries.append(msg)
    
    try:
        vhd_path_obj = Path(vhd_path)
        
        emit_log(f"Target distro: {distro}")
        emit_log(f"Target user: {username}")
        emit_log(f"VHDX: {vhd_path_obj}")
        
        if not dry_run and not vhd_path_obj.exists():
            return CompactionResult(False, f"VHD file not found: {vhd_path_obj}", log_entries)
        
        # 1) Detect activity
        emit_log("Checking for active user processes…")
        active = False
        try:
            active = user_active(distro, username)
        except Exception as e:
            emit_log(f"Warning: activity check failed ({e}); continuing.")
        
        # 2) Log out (force)
        if active:
            emit_log("User appears active; logging out (killing all processes)…")
        else:
            emit_log("No active processes detected for user; proceeding to shutdown.")
        
        try:
            logout_user(distro, username)
        except Exception as e:
            emit_log(f"Warning: logout attempt failed ({e}); continuing.")
        
        # Re-check
        try:
            still_active = user_active(distro, username)
            emit_log("Logout verification: " + ("FAILED (still active)" if still_active else "OK"))
        except Exception as e:
            emit_log(f"Warning: could not re-verify logout ({e}).")
        
        # 3) Clean shutdown
        emit_log("Stopping WSL…")
        terminate_wsl(distro)
        
        # 4) Compact
        emit_log("Compacting VHD (DiskPart)…")
        out = run_diskpart_compact(vhd_path_obj)
        emit_log(out if out else "DiskPart finished.")
        
        # 5) Optional relaunch
        if relaunch_after:
            emit_log("Relaunching distro…")
            try:
                relaunch_distro(distro, username)
                emit_log("Relaunch requested.")
            except Exception as e:
                emit_log(f"Warning: relaunch failed ({e})")
        
        return CompactionResult(True, "Compaction completed successfully.", log_entries)
        
    except Exception as e:
        error_msg = f"Error: {e}"
        emit_log(error_msg)
        return CompactionResult(False, error_msg, log_entries)

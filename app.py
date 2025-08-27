import os, sys, json, argparse
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QFileDialog, QTextEdit, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal

# Import from our new core module
from wsl_compact.core import (
    compact_wsl_vhd, get_vhd_for_distro, is_windows, is_admin, 
    relaunch_elevated, log_message, APP_DIR, CFG_PATH
)

# Global dry-run flag
DRY_RUN = False

# ---------- worker ----------
class Worker(QThread):
    log = Signal(str)
    done = Signal(str, bool)  # message, ok?

    def __init__(self, distro, username, vhd_path, relaunch_after):
        super().__init__()
        self.distro = distro
        self.username = username
        self.vhd_path = vhd_path
        self.relaunch_after = relaunch_after

    def run(self):
        """Run the compaction using the core module."""
        global DRY_RUN
        
        # Use the core compaction function
        result = compact_wsl_vhd(
            distro=self.distro,
            username=self.username,
            vhd_path=self.vhd_path,
            relaunch_after=self.relaunch_after,
            dry_run=DRY_RUN
        )
        
        # Emit all log entries to the GUI
        for log_entry in result.log_entries:
            self.log.emit(log_entry.split('] ', 1)[-1])  # Remove timestamp for GUI
        
        # Emit final result
        self.done.emit(result.message, result.success)

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
        
        detect = QPushButton("Detect VHD")
        detect.clicked.connect(self.detect_vhd)

        form.addRow("Distro:", self.distro)
        form.addRow("Username:", self.username)
        # VHD field + buttons stacked
        vhd_row = QWidget(); vbox = QVBoxLayout(vhd_row); vbox.setContentsMargins(0,0,0,0)
        vbox.addWidget(self.vhd)
        # Button row for Browse and Detect
        btn_row = QWidget(); btn_layout = QVBoxLayout(btn_row); btn_layout.setContentsMargins(0,0,0,0)
        btn_layout.addWidget(browse); btn_layout.addWidget(detect)
        vbox.addWidget(btn_row)
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
                
                # Restore window geometry if saved
                if "window_geometry" in cfg:
                    geom = cfg["window_geometry"]
                    self.resize(geom.get("width", 600), geom.get("height", 440))
                    if "x" in geom and "y" in geom:
                        self.move(geom["x"], geom["y"])
            except: pass

        # Best-effort auto-detect VHD on first run
        if not self.vhd.text() and is_windows():
            try:
                self.vhd.setText(str(get_vhd_for_distro(self.distro.text().strip() or "Ubuntu")))
            except: pass

    def pick_vhd(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select ext4.vhdx", str(Path.home()), "VHDX (*.vhdx)")
        if p: self.vhd.setText(p)
    
    def detect_vhd(self):
        """Auto-detect VHD path for the current distro."""
        distro = self.distro.text().strip() or "Ubuntu"
        
        if not is_windows():
            QMessageBox.warning(self, "Warning", "VHD detection only works on Windows.")
            return
            
        try:
            vhd_path = get_vhd_for_distro(distro)
            self.vhd.setText(str(vhd_path))
            QMessageBox.information(self, "Success", f"VHD detected: {vhd_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not detect VHD for distro '{distro}': {e}")

    def save_config(self):
        """Save current configuration including window geometry."""
        config = {
            "distro": self.distro.text().strip() or "Ubuntu",
            "username": self.username.text().strip() or "ubuntu",
            "vhd": self.vhd.text().strip(),
            "relaunch": self.relaunch.isChecked(),
            "window_geometry": {
                "x": self.x(),
                "y": self.y(),
                "width": self.width(),
                "height": self.height()
            }
        }
        CFG_PATH.write_text(json.dumps(config, indent=2))
    
    def closeEvent(self, event):
        """Called when window is closed - save config."""
        self.save_config()
        event.accept()

    def run_clicked(self):
        # Save config before running
        self.save_config()

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
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="WSL Compact GUI - Compact WSL2 VHDX files")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Show what actions would be taken without executing them")
    args = parser.parse_args()
    
    # Set global dry-run flag
    DRY_RUN = args.dry_run
    
    if DRY_RUN:
        log_message("[DRY-RUN MODE] No actual changes will be made")
    else:
        log_message("WSL Compact GUI started")
    
    app = QApplication(sys.argv)
    w = MainWin(); w.resize(600, 440); w.show()
    
    # Add dry-run indicator to window title if enabled
    if DRY_RUN:
        w.setWindowTitle("WSL Compact (PySide6) - DRY RUN MODE")
    
    sys.exit(app.exec())

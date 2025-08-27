# WSL Compact (PySide6)

Minimal GUI to:
1) log out any existing user in a WSL2 distro,
2) verify logout,
3) compact the distro's ext4.vhdx,
4) optionally relaunch the distro for that user.

## Dev (Linux or Windows)
```bash
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py          # GUI launches (compaction only works on Windows)

```

## Features
* ✅ GUI (PySide6) for one-click compaction with progress log
* ✅ Command-line interface (headless) for automation / CI
* ✅ Dry-run mode – simulate actions without touching your VHD
* ✅ Windows CI builds (.exe) & headless tests on every push

---

## 1. Running the **GUI** application (Windows 10/11)

```powershell
git clone https://github.com/<you>/wsl2-compactor.git
cd wsl2-compactor
python -m venv .venv
.venv\Scripts\activate     # <-- on PowerShell / CMD
pip install -r requirements.txt  # installs PySide6

# launch the app
python app.py               # UAC prompt appears, GUI opens
```

### GUI usage steps
1. Choose **Distro** (default: Ubuntu)
2. Choose **User** inside the distro (default: ubuntu)
3. Leave **VHDX** blank to auto-detect or browse to a file
4. (Optional) uncheck **Relaunch distro after compaction**
5. Click **Run** – watch live log output at the bottom

Logs are also written to `%APPDATA%\WSLCompact\logs\latest.txt`.

---

## 2. Using the **Headless CLI**

### Prerequisites
* **Windows 10/11 host** – the CLI calls `wsl.exe`, the registry and `diskpart.exe`; it must run on Windows, **not inside the Linux distro**.
* **WSL 2 enabled** with at least one distro installed.
* **Administrator account** (required for DiskPart and terminating WSL).
* **Python ≥ 3.10** installed on the Windows side.

### Quick-start A – clone the repo (dev workflow)
```powershell
# Elevated PowerShell on Windows
git clone https://github.com/<you>/wsl2-compactor.git
cd wsl2-compactor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install .            # installs only the wsl_compact package – no PySide6

# Dry-run test (safe) – replace distro/user as needed
python -m wsl_compact.cli --distro Ubuntu --user ubuntu --dry-run
```

### Quick-start B – use wheel from release ZIP (no git needed)
```powershell
# Download WSL-Compact-CLI.zip from GitHub Releases and unzip
cd WSL-Compact-CLI
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install wsl_compact-*.whl
python -m wsl_compact.cli --help
```

> **Running inside the distro?**  Not possible – the tool needs host-side APIs. Always run it in Windows.

The core logic lives in `wsl_compact` and can be invoked without the GUI.

```powershell
# Dry-run (safe on any machine – no real changes)
python -m wsl_compact.cli --distro Ubuntu --user ubuntu --dry-run

# Real compaction with custom VHD path
python -m wsl_compact.cli --distro Ubuntu --user ubuntu \
       --vhd "C:\Users\me\AppData\Local\Packages\...\ext4.vhdx"

# Skip relaunch after compaction
python -m wsl_compact.cli --no-relaunch
```

Exit codes: `0` success, `1` failure, `130` cancelled.

---

## 3. Headless test script (Windows PowerShell)

We ship `scripts\test-compact.ps1` that validates the CLI in **dry-run** mode.

```powershell
pwsh scripts/test-compact.ps1 -Distro Ubuntu -User ubuntu
```

The script checks:
* Python module import
* `--help` output
* Dry-run log contains expected lines
* Error handling for invalid distros

---

## 4. Continuous Integration

GitHub Actions workflow (`.github/workflows/build.yml`):

1. **test-headless** job – runs the PowerShell test on `windows-latest`
2. **win** job – builds `WSL-Compact.exe` with PyInstaller (needs test job to pass)

Artifacts are available under **Actions → run → Artifacts**.

Tagging a release (`git tag v1.0.2 && git push --tags`) triggers the release workflow which uploads the executable to GitHub Releases.

---

## 5. Packaging standalone CLI (optional)

If you want a minimal CLI-only exe (~10 MB):

```powershell
pip install pyinstaller
pyinstaller --onefile -n WSL-Compact-CLI wsl_compact/cli.py
```

---

## 6. Pre-built Windows EXE

Every push to `master` produces a signed* `WSL-Compact.exe`.

### Where to download
1. **GitHub Actions artifact**  
   • Repo → **Actions** → latest **build-windows** run → **Artifacts** → *WSL-Compact*
2. **GitHub Release** (for tagged versions such as `v1.0.2`)  
   • Repo → **Releases** → choose a version → download *WSL-Compact.exe*

> \* currently unsigned – you will get a SmartScreen prompt. Click “More info → Run anyway” or sign with your own cert.

### How to use the EXE
1. Copy `WSL-Compact.exe` to any Windows 10/11 PC with WSL2 installed.  
2. **Double-click** – UAC prompt appears (requested by `--uac-admin` flag).  
3. Follow GUI steps (see section 1).  
4. Logs are written to `%APPDATA%\WSLCompact\logs\latest.txt`.

#### Command-line flags
`WSL-Compact.exe` accepts the same CLI flags as the Python version:
```powershell
WSL-Compact.exe --distro Ubuntu --user ubuntu --dry-run --no-relaunch
```
(*Note: flags work only when started from an elevated PowerShell/CMD window.*)

### About “elevated” PowerShell / CMD

`WSL-Compact.exe` manipulates WSL internals (terminating distros, running **diskpart.exe**, attaching VHDs).  
These actions **require Administrator rights**.  When you double-click the EXE the operating system already shows a UAC prompt and the GUI runs elevated – so everything just works.

However, **when you launch the EXE from the command-line to pass flags** no UAC prompt appears – the process inherits the permissions of the shell that started it.  Therefore:

1. **Open an elevated shell** first:  
   *Press <kbd>Win</kbd> → type “powershell”, right-click → “Run as administrator”*  
   or for CMD: *Press <kbd>Win</kbd>+<kbd>R</kbd> → type `cmd` → <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd>*
2. Navigate to the folder containing `WSL-Compact.exe`  
3. Run the command with flags (example above)

#### What if you run it **non-elevated**?

* The EXE starts but immediately tries to re-launch itself with admin rights (because it was built with `--uac-admin`).  You’ll get a second UAC prompt **without** your custom arguments – the relaunched instance doesn’t see the flags you typed.  
* Result: GUI opens in normal mode and CLI flags are **ignored**.  
* Some operations (e.g., DiskPart) would fail due to lack of privileges even if flags were somehow forwarded.

So, for scripted/CLI usage **always start an elevated shell first**.

---

## License
MIT

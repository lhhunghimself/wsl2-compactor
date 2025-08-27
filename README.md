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

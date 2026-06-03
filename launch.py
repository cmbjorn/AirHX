"""Bootstrap venv (first run) then launch the AirHX Streamlit app."""
import os
import subprocess
import sys
import time
import webbrowser

VENV   = os.path.join(os.path.dirname(__file__), ".venv")
PYTHON = os.path.join(VENV, "Scripts" if sys.platform == "win32" else "bin", "python")
PIP    = os.path.join(VENV, "Scripts" if sys.platform == "win32" else "bin", "pip")

def _bootstrap():
    print("Creating virtual environment …")
    subprocess.check_call([sys.executable, "-m", "venv", VENV])
    print("Installing dependencies …")
    subprocess.check_call([PIP, "install", "-r",
                           os.path.join(os.path.dirname(__file__), "requirements.txt")])

if not os.path.exists(PYTHON):
    _bootstrap()

PORT = 8503
proc = subprocess.Popen([
    PYTHON, "-m", "streamlit", "run",
    os.path.join(os.path.dirname(__file__), "app.py"),
    f"--server.port={PORT}",
    "--server.address=127.0.0.1",
    "--server.headless=true",
])

time.sleep(4)
webbrowser.open(f"http://127.0.0.1:{PORT}")
print(f"AirHX running at http://127.0.0.1:{PORT}  (Ctrl+C to stop)")

try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()

"""
compi_start - Main background entry point for compi server
Supports domain access (compi.mojuk.kr) and local access (localhost / 127.0.0.1) on port 26240
"""
import os
import sys
import atexit
import signal

# Set directory context
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

log_file = os.path.join(script_dir, "compi_server.log")
f = open(log_file, "a", encoding="utf-8", buffering=1)
if sys.stdout is None:
    sys.stdout = f
if sys.stderr is None:
    sys.stderr = f

def on_exit():
    f.write(f"--- atexit called for PID={os.getpid()} ---\n")
atexit.register(on_exit)

def on_signal(sig, frame):
    f.write(f"--- Received signal {sig} for PID={os.getpid()} ---\n")
    sys.exit(0)

try:
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
except Exception:
    pass

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 26240))
    host = "0.0.0.0"
    f.write(f"--- Starting uvicorn PID={os.getpid()} on {host}:{port} ---\n")
    uvicorn.run("main:app", host=host, port=port, log_level="info", access_log=True, reload=False)
    f.write(f"--- uvicorn.run finished PID={os.getpid()} ---\n")

"""Execute a notebook inside the instance's running JupyterLab (heatahead-jupyter).

Run on the LinuxONE instance:
    ~/datathon-env/bin/python web/jupyter/run_in_jupyter.py web/jupyter/T5_landlord_contacts.ipynb

Opens a session for the notebook through the server's REST API (so the kernel shows up
in JupyterLab beside the notebook), runs every code cell in that kernel, writes the
outputs back into the .ipynb, then shuts the session down. The token is read from
~/.config/heatahead/jupyter.env and never printed. Stops at the first failing cell and
still saves what ran.
"""

import os
import sys
import time
from pathlib import Path

import nbformat
import requests
from jupyter_client import BlockingKernelClient
from jupyter_core.paths import jupyter_runtime_dir
from nbformat.v4 import output_from_msg

SERVER = "http://127.0.0.1:8888"
ROOT_DIR = Path.home()                      # --ServerApp.root_dir of heatahead-jupyter
KERNEL = "datathon-env"                     # the project venv, not the system python3


def token():
    env = Path.home() / ".config/heatahead/jupyter.env"
    for line in env.read_text().splitlines():
        if line.startswith("JUPYTER_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("no JUPYTER_TOKEN in " + str(env))


def run(path):
    path = Path(path).resolve()
    nb = nbformat.read(path, as_version=4)
    s = requests.Session()
    s.headers["Authorization"] = f"token {token()}"
    s.get(f"{SERVER}/api/status", timeout=10).raise_for_status()
    sess = s.post(f"{SERVER}/api/sessions", timeout=60, json=dict(
        path=str(path.relative_to(ROOT_DIR)), type="notebook", name=path.name,
        kernel=dict(name=KERNEL))).json()
    kid = sess["kernel"]["id"]
    print(f"session {sess['id'][:8]} on kernel {KERNEL} ({kid[:8]}) in the running JupyterLab",
          flush=True)
    kc = BlockingKernelClient()
    kc.load_connection_file(os.path.join(jupyter_runtime_dir(), f"kernel-{kid}.json"))
    kc.start_channels()
    kc.wait_for_ready(timeout=120)
    ok, t_all = True, time.time()
    try:
        for i, cell in enumerate(nb.cells):
            if cell.cell_type != "code":
                continue
            t0 = time.time()
            msg_id = kc.execute(cell.source, store_history=True)
            cell.outputs = []
            while True:
                msg = kc.get_iopub_msg(timeout=3600)
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue
                kind, content = msg["msg_type"], msg["content"]
                if kind == "status" and content["execution_state"] == "idle":
                    break
                if kind == "execute_input":
                    cell.execution_count = content["execution_count"]
                elif kind in ("stream", "display_data", "execute_result", "error"):
                    out = output_from_msg(msg)
                    last = cell.outputs[-1] if cell.outputs else None
                    if (kind == "stream" and last and last.output_type == "stream"
                            and last.name == out.name):
                        last.text += out.text
                    else:
                        cell.outputs.append(out)
                    if kind == "error":
                        ok = False
            print(f"  cell {i:2d}: {time.time() - t0:6.1f} s {'ok' if ok else 'FAILED'}", flush=True)
            if not ok:
                break
    finally:
        nb.metadata.setdefault("heatahead", {})["executed"] = dict(
            server="heatahead-jupyter", kernel=KERNEL, machine=os.uname().machine,
            at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), seconds=round(time.time() - t_all))
        nbformat.write(nb, path)
        kc.stop_channels()
        s.delete(f"{SERVER}/api/sessions/{sess['id']}", timeout=60)
    print(f"{'all cells ran' if ok else 'stopped at a failing cell'}; outputs saved to {path}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1]) else 1)

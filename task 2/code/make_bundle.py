"""Bundle the Workstream 2 deliverables on the server into stream2_deliverables.zip.

Run from ~/heatahead/stream2/:  ~/datathon-env/bin/python make_bundle.py
Uses Python's zipfile (zlib deflate, so the DFLTCC engine on the z17 does the compression).
Never includes raw/ (raw apartment numbers) or work/ (keys and pseudonymized extracts).
"""
import glob
import os
import time
import zipfile

OUT = "stream2_deliverables.zip"
files = (["02_stream2_report.md", "02_stream2_analysis.ipynb", "README.md", "run_all.sh", "pull_open_data.sh", "make_bundle.py"]
         + sorted(glob.glob("s2_*.py")) + sorted(glob.glob("out/*"))
         + [f for f in sorted(glob.glob("logs/*.log")) if "chain" not in f])
t0 = time.perf_counter()
total = 0
with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for f in files:
        z.write(f, f)
        total += os.path.getsize(f)
secs = time.perf_counter() - t0
print(f"{len(files)} files, {total / 1e6:.1f} MB -> {os.path.getsize(OUT) / 1e6:.1f} MB in {secs:.2f} s "
      f"({total / 1e6 / secs:,.0f} MB/s, zlib deflate on the z17)")

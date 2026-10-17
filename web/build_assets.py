"""Precompute public/data/ for the Vercel (LITE) site from the FULL data.

Run on the LinuxONE instance, from the repo root, where model/out/ and data/ exist:
    ~/datathon-env/bin/python web/build_contacts.py --pull   # T5a owner/agent table
    ~/datathon-env/bin/python web/build_assets.py

Writes (docs/VERCEL.md section 2):
    public/data/map_data.json     exactly what /api/map_data returns in FULL mode
    public/data/b/<n>.json        n = bbl % 128; {bbl: [record over app.FIELDS]}
    public/data/reliability.json  the season calibration table
    public/data/top500.csv        the government export, /api/queue.csv?k=500
    public/data/meta.json         citywide median, counts, build time, git sha, model files
Building-level only: nothing here carries an apartment number.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ["APP_MODE"] = "full"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as web  # noqa: E402  (FULL mode: loads model/out and data with pandas)

ASSETS = web.ASSETS
MAX_FILE, MAX_TOTAL = 25e6, 60e6
MODEL_FILES = ["season_risk_2026.csv", "ranked_inspection_list.csv",
               "season_reliability.csv", "building_day_counts.csv",
               "heat_model_final.json", "calibration.csv"]


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")))


def main():
    assert web.season_risk.index.is_unique, "season_risk has duplicate bbls"
    assert web.ranked.index.is_unique, "ranked list has duplicate bbls"
    if ASSETS.exists():
        shutil.rmtree(ASSETS)

    shards = [dict() for _ in range(web.SHARDS)]
    for bbl in web.season_risk.index:
        rec = web.building_record(int(bbl))
        shards[int(bbl) % web.SHARDS][str(int(bbl))] = [rec[f] for f in web.FIELDS]
    for n, shard in enumerate(shards):
        dump(ASSETS / "b" / f"{n}.json", shard)

    dump(ASSETS / "map_data.json", web.map_rows())
    dump(ASSETS / "reliability.json", web.RELIABILITY)
    (ASSETS / "top500.csv").write_text(web.queue_csv(500))

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=web.ROOT,
                             capture_output=True, text=True).stdout.strip()
    except OSError:
        sha = None
    models = {}
    for name in MODEL_FILES:
        f = web.OUT / name
        if f.exists():
            st = f.stat()
            models[name] = dict(bytes=st.st_size, modified=datetime.fromtimestamp(
                st.st_mtime, timezone.utc).isoformat(timespec="seconds"))
    contacts = web.DATA / "second_tier/bbl_contacts.csv"
    if contacts.exists():
        st = contacts.stat()
        models[contacts.name] = dict(bytes=st.st_size, modified=datetime.fromtimestamp(
            st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            source="HPD registration contacts, NYC Open Data feu5-w2e2")
    else:
        print("no data/second_tier/bbl_contacts.csv: run web/build_contacts.py first "
              "for the owner and managing-agent fields")
    sr = web.season_risk.p_season
    meta = dict(median=round(float(sr.median()), 4), ranked=len(web.season_risk),
                cold_ranked=len(web.ranked), at_least_80=int((sr >= 0.8).sum()),
                at_least_50=int((sr >= 0.5).sum()), shards=web.SHARDS,
                fields=list(web.FIELDS), built_at=datetime.now(timezone.utc)
                .isoformat(timespec="seconds"), built_on=web.ARCH, git_sha=sha,
                model_files=models)
    dump(ASSETS / "meta.json", meta)

    files = [f for f in ASSETS.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    biggest = max(files, key=lambda f: f.stat().st_size)
    print(f"wrote {len(files)} files, {total / 1e6:.1f} MB total; biggest "
          f"{biggest.relative_to(web.ROOT)} {biggest.stat().st_size / 1e6:.1f} MB")
    print(json.dumps({k: v for k, v in meta.items() if k != "fields"}, indent=1))
    assert biggest.stat().st_size < MAX_FILE, "a file is over 25 MB"
    assert total < MAX_TOTAL, "public/data is over 60 MB"


if __name__ == "__main__":
    main()

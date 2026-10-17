"""STEP 0: stage the raw tables on the IBM z17 and apply hardware data protection.

What this does, on the LinuxONE guest itself:
  1. Inflates the raw complaint (ygpa-z7cr) and violation (wvxf-dwi5) tables that
     were shipped as gzip streams (zlib inflate -> DFLTCC on-chip deflate engine).
  2. Pseudonymizes the tenant-level `apartment` field: HMAC-SHA256 over
     (building_id, apartment) with a server-only key, keeps the 16-hex-char tag as
     `apt_hash`, and drops the raw apartment number from every working table.
     Distinct complaining apartments per building can still be counted.
  3. Writes compressed (zlib, DFLTCC) and encrypted (AES-256-GCM through OpenSSL's
     CPACF path) copies of the staged extracts.
  4. Benchmarks every one of those operations on the real project files, with the
     hardware feature on and off (DFLTCC=0 for deflate, OPENSSL_s390xcap masks for
     the CPACF cipher and hash instructions), and logs MB/s.

Usage:
  python s2_00_stage_protect.py            # full run
  python s2_00_stage_protect.py --bench    # internal: one benchmark pass under the current env
"""
import gzip
import hashlib
import hmac
import json
import os
import platform
import subprocess
import sys
import time
import zlib

import numpy as np
import pandas as pd

from s2_common import RAW, WORK, OUT, LOGS, Timer

RAW_FILES = {"ygpa-z7cr.csv": "complaints", "wvxf-dwi5.csv": "violations"}
KEY_HMAC = WORK / ".apt_hmac.key"
KEY_AES = WORK / ".aes256.key"
MB = 1024 * 1024
CPACF_OFF = "km:0:0;kmc:0:0;kmctr:0:0;kmf:0:0;kmo:0:0;kma:0:0;kmac:0:0;kimd:0:0;klmd:0:0"


def _key(path, n=32):
    if not path.exists():
        path.write_bytes(os.urandom(n))
        path.chmod(0o600)
    return path.read_bytes()


# ---------------------------------------------------------------- 1. inflate
def inflate():
    rows = []
    for name in RAW_FILES:
        gz, out = RAW / f"{name}.gz", RAW / name
        if out.exists() and out.stat().st_size > 0:
            print(f"  {name} already inflated ({out.stat().st_size/MB:,.1f} MB)")
            continue
        t0 = time.perf_counter()
        with gzip.open(gz, "rb") as f, open(out, "wb") as g:
            while True:
                chunk = f.read(64 * MB)
                if not chunk:
                    break
                g.write(chunk)
        secs = time.perf_counter() - t0
        rows.append({"file": name, "gz_mb": gz.stat().st_size / MB, "csv_mb": out.stat().st_size / MB,
                     "secs": secs, "inflate_mb_per_s": out.stat().st_size / MB / secs})
        print(f"  inflated {name}: {out.stat().st_size/MB:,.1f} MB in {secs:.2f} s "
              f"({out.stat().st_size/MB/secs:,.0f} MB/s output, DFLTCC={os.environ.get('DFLTCC','default')})")
    return rows


# ---------------------------------------------------------------- 2. pseudonymize
def pseudonymize():
    key = _key(KEY_HMAC)
    log = {}
    # complaints: keep every analytic column, drop the raw apartment and the
    # post-event status date (banned as a feature anyway, so it never enters a working table)
    with Timer("read raw complaints"):
        c = pd.read_csv(RAW / "ygpa-z7cr.csv", dtype=str, keep_default_na=False,
                        usecols=["received_date", "problem_id", "complaint_id", "building_id", "bbl", "bin",
                                 "apartment", "minor_category", "problem_code", "problem_duplicate_flag",
                                 "complaint_anonymous_flag", "unique_key"])
    log["complaints_rows"] = len(c)
    with Timer("HMAC-SHA256 pseudonymize apartments (complaints)") as t:
        msgs = (c.building_id + "|" + c.apartment.str.strip().str.upper()).to_numpy()
        c["apt_hash"] = [hmac.digest(key, m.encode(), "sha256")[:8].hex() for m in msgs]
    nbytes = int(sum(len(m) for m in msgs))
    log["hmac_rows"] = len(c)
    log["hmac_secs"] = t.secs
    log["hmac_rows_per_s"] = len(c) / t.secs
    log["hmac_msg_mb_per_s"] = nbytes / MB / t.secs
    log["apartments_distinct_raw"] = int(c.apartment.str.strip().str.upper().nunique())
    log["apartments_distinct_hashed"] = int(c.apt_hash.nunique())
    c = c.drop(columns=["apartment"])
    with Timer("write complaints_pseud.csv"):
        c.to_csv(WORK / "complaints_pseud.csv", index=False)
    del c

    with Timer("read raw violations"):
        v = pd.read_csv(RAW / "wvxf-dwi5.csv", dtype=str, keep_default_na=False)
    with Timer("HMAC-SHA256 pseudonymize apartments (violations)") as t:
        msgs = (v.buildingid + "|" + v.apartment.str.strip().str.upper()).to_numpy()
        v["apt_hash"] = [hmac.digest(key, m.encode(), "sha256")[:8].hex() for m in msgs]
    log["violations_rows"] = len(v)
    log["hmac_violations_secs"] = t.secs
    v = v.drop(columns=["apartment"])
    v.to_csv(WORK / "violations_pseud.csv", index=False)
    print(f"  working tables carry apt_hash only; raw apartment numbers never leave raw/ "
          f"({log['apartments_distinct_raw']:,} distinct apartment labels -> {log['apartments_distinct_hashed']:,} distinct hashes)")
    return log


# ---------------------------------------------------------------- 3+4. compress / encrypt / bench
def bench_pass():
    """One pass under the current environment (DFLTCC, OPENSSL_s390xcap)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    res = {"env_DFLTCC": os.environ.get("DFLTCC", "default"),
           "env_OPENSSL_s390xcap": os.environ.get("OPENSSL_s390xcap", "default"), "ops": []}
    files = {"raw complaints ygpa-z7cr.csv": RAW / "ygpa-z7cr.csv",
             "staged complaints_pseud.csv": WORK / "complaints_pseud.csv",
             "staged violations_pseud.csv": WORK / "violations_pseud.csv"}
    aes_key = _key(KEY_AES)
    for label, path in files.items():
        data = path.read_bytes()
        n = len(data)
        for level in (1, 6):
            t0 = time.perf_counter(); z = zlib.compress(data, level); s = time.perf_counter() - t0
            t1 = time.perf_counter(); back = zlib.decompress(z); s2 = time.perf_counter() - t1
            assert back == data
            res["ops"].append({"file": label, "op": f"zlib compress level {level}", "in_mb": n / MB, "out_mb": len(z) / MB,
                               "ratio": n / len(z), "secs": s, "mb_per_s": n / MB / s})
            res["ops"].append({"file": label, "op": f"zlib decompress level {level}", "in_mb": len(z) / MB, "out_mb": n / MB,
                               "ratio": n / len(z), "secs": s2, "mb_per_s": n / MB / s2})
            if level == 6 and label.startswith("staged"):
                (WORK / (path.name + ".zz")).write_bytes(z)
                # AES-256-GCM over the compressed extract (what actually sits on disk)
                nonce = os.urandom(12)
                t2 = time.perf_counter(); ct = AESGCM(aes_key).encrypt(nonce, z, label.encode()); s3 = time.perf_counter() - t2
                t3 = time.perf_counter(); pt = AESGCM(aes_key).decrypt(nonce, ct, label.encode()); s4 = time.perf_counter() - t3
                assert pt == z
                (WORK / (path.name + ".zz.gcm")).write_bytes(nonce + ct)
                res["ops"].append({"file": label + " (zlib-6 stream)", "op": "AES-256-GCM encrypt (OpenSSL via python cryptography)",
                                   "in_mb": len(z) / MB, "out_mb": len(ct) / MB, "ratio": 1.0, "secs": s3, "mb_per_s": len(z) / MB / s3})
                res["ops"].append({"file": label + " (zlib-6 stream)", "op": "AES-256-GCM decrypt+verify",
                                   "in_mb": len(ct) / MB, "out_mb": len(z) / MB, "ratio": 1.0, "secs": s4, "mb_per_s": len(z) / MB / s4})
        # AES-256-GCM over the uncompressed bytes too (the headline MB/s), chunked at 64 MB
        nonce = os.urandom(12); g = AESGCM(aes_key)
        t0 = time.perf_counter()
        for i in range(0, n, 64 * MB):
            g.encrypt(nonce, data[i:i + 64 * MB], None)
        s = time.perf_counter() - t0
        res["ops"].append({"file": label, "op": "AES-256-GCM encrypt (64 MB chunks)", "in_mb": n / MB, "out_mb": n / MB,
                           "ratio": 1.0, "secs": s, "mb_per_s": n / MB / s})
        t0 = time.perf_counter(); hashlib.sha256(data).hexdigest(); s = time.perf_counter() - t0
        res["ops"].append({"file": label, "op": "SHA-256 digest (hashlib/OpenSSL)", "in_mb": n / MB, "out_mb": 0,
                           "ratio": 1.0, "secs": s, "mb_per_s": n / MB / s})
        t0 = time.perf_counter(); hmac.digest(aes_key, data, "sha256"); s = time.perf_counter() - t0
        res["ops"].append({"file": label, "op": "HMAC-SHA256 digest", "in_mb": n / MB, "out_mb": 0,
                           "ratio": 1.0, "secs": s, "mb_per_s": n / MB / s})
        del data
    # native command-line tools on the staged extract
    src = WORK / "complaints_pseud.csv"
    n = src.stat().st_size
    env = os.environ.copy()
    t0 = time.perf_counter()
    subprocess.run(["openssl", "enc", "-aes-256-ctr", "-pbkdf2", "-pass", f"file:{KEY_AES}",
                    "-in", str(src), "-out", str(WORK / "complaints_pseud.csv.ctr")], check=True, env=env)
    s = time.perf_counter() - t0
    res["ops"].append({"file": "staged complaints_pseud.csv", "op": "openssl enc -aes-256-ctr -pbkdf2 (CLI; enc has no GCM mode)",
                       "in_mb": n / MB, "out_mb": n / MB, "ratio": 1.0, "secs": s, "mb_per_s": n / MB / s})
    t0 = time.perf_counter()
    subprocess.run(["openssl", "dgst", "-sha256", "-hmac", "stream2", str(src)], check=True, env=env, capture_output=True)
    s = time.perf_counter() - t0
    res["ops"].append({"file": "staged complaints_pseud.csv", "op": "openssl dgst -sha256 -hmac (CLI)",
                       "in_mb": n / MB, "out_mb": 0, "ratio": 1.0, "secs": s, "mb_per_s": n / MB / s})
    (WORK / "complaints_pseud.csv.ctr").unlink(missing_ok=True)
    return res


def run_bench_variants():
    me = os.path.abspath(__file__)
    variants = {
        "hardware on (DFLTCC default, CPACF on)": {},
        "DFLTCC=0 (deflate in software)": {"DFLTCC": "0"},
        "CPACF masked (AES + SHA instructions off, OPENSSL_s390xcap)": {"OPENSSL_s390xcap": CPACF_OFF},
    }
    out = {}
    for label, env_extra in variants.items():
        env = os.environ.copy(); env.update(env_extra)
        with Timer(f"benchmark pass: {label}"):
            r = subprocess.run([sys.executable, me, "--bench"], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr[-2000:]); raise SystemExit("bench pass failed")
        out[label] = json.loads(r.stdout.strip().splitlines()[-1])
    return out


def openssl_speed():
    rows = []
    for algo in ("aes-256-gcm", "sha256"):
        for label, env_extra in {"CPACF on": {}, "CPACF masked": {"OPENSSL_s390xcap": CPACF_OFF}}.items():
            env = os.environ.copy(); env.update(env_extra)
            r = subprocess.run(["openssl", "speed", "-seconds", "2", "-evp", algo], env=env, capture_output=True, text=True)
            last = [l for l in r.stdout.splitlines() if l.strip()][-1].split()
            rows.append({"algo": algo, "mode": label, "kb_per_s_16KB_blocks": float(last[-1].rstrip("k")),
                         "gb_per_s_16KB_blocks": float(last[-1].rstrip("k")) / 1024 / 1024})
    return rows


def machine_facts():
    cpuinfo = open("/proc/cpuinfo").read()
    facts = {"uname_m": platform.machine(), "kernel": platform.release(),
             "machine_line": [l for l in cpuinfo.splitlines() if "machine" in l][0].strip(),
             "features_line": [l for l in cpuinfo.splitlines() if l.startswith("features")][0].strip(),
             "has_dflt": " dflt" in cpuinfo, "has_nnpa": " nnpa" in cpuinfo, "has_vx": " vx" in cpuinfo,
             "nproc": os.cpu_count(), "python": platform.python_version(), "zlib": zlib.ZLIB_RUNTIME_VERSION,
             "openssl": subprocess.run(["openssl", "version"], capture_output=True, text=True).stdout.strip()}
    try:
        facts["lszcrypt"] = subprocess.run(["lszcrypt"], capture_output=True, text=True).stdout.strip() or "no Crypto Express cards"
    except FileNotFoundError:
        facts["lszcrypt"] = "lszcrypt not installed"
    return facts


def write_log(facts, inflate_rows, pseud, bench, speed):
    log = {"machine": facts, "inflate": inflate_rows, "pseudonymize": pseud, "bench": bench, "openssl_speed": speed}
    (OUT / "z17_hardware_log.json").write_text(json.dumps(log, indent=2))
    rows = []
    for variant, r in bench.items():
        for op in r["ops"]:
            rows.append({"variant": variant, **op})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "z17_hardware_log.csv", index=False)
    md = ["# IBM z17 hardware execution log (Workstream 2, measured on the real project files)", "",
          f"- Machine: `{facts['machine_line']}`, `uname -m` = {facts['uname_m']}, {facts['nproc']} virtual cores, kernel {facts['kernel']}",
          f"- Facilities: dflt (on-chip deflate) = {facts['has_dflt']}, nnpa (Telum AI accelerator) = {facts['has_nnpa']}, vx = {facts['has_vx']}",
          f"- zlib {facts['zlib']} (DFLTCC build), {facts['openssl']}, Python {facts['python']}; Crypto Express: {facts['lszcrypt']}", ""]
    if inflate_rows:
        md += ["## 1. Inflating the shipped gzip streams (zlib inflate, DFLTCC)", "", "| file | gz MB | csv MB | seconds | MB/s |", "|---|---|---|---|---|"]
        md += [f"| {r['file']} | {r['gz_mb']:.1f} | {r['csv_mb']:.1f} | {r['secs']:.2f} | {r['inflate_mb_per_s']:,.0f} |" for r in inflate_rows]
        md.append("")
    md += ["## 2. Apartment pseudonymization (HMAC-SHA256, per row)", "",
           f"- {pseud['hmac_rows']:,} complaint rows hashed in {pseud['hmac_secs']:.2f} s = {pseud['hmac_rows_per_s']:,.0f} rows/s "
           f"({pseud['hmac_msg_mb_per_s']:.1f} MB/s of message bytes, Python call overhead dominates)",
           f"- {pseud['apartments_distinct_raw']:,} distinct raw apartment labels became {pseud['apartments_distinct_hashed']:,} distinct 64-bit tags; the raw column is dropped from every working table",
           f"- {pseud['violations_rows']:,} violation rows hashed in {pseud['hmac_violations_secs']:.2f} s", ""]
    md += ["## 3. Compression and encryption of the staged extracts, hardware on vs off", "",
           "| variant | file | operation | in MB | out MB | ratio | seconds | MB/s |", "|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        md.append(f"| {r.variant} | {r.file} | {r.op} | {r.in_mb:,.1f} | {r.out_mb:,.1f} | {r.ratio:.2f} | {r.secs:.3f} | {r.mb_per_s:,.0f} |")
    md += ["", "## 4. openssl speed, 16 KB blocks, one core", "", "| algorithm | mode | GB/s |", "|---|---|---|"]
    md += [f"| {r['algo']} | {r['mode']} | {r['gb_per_s_16KB_blocks']:.2f} |" for r in speed]
    (OUT / "z17_hardware_log.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    if "--bench" in sys.argv:
        print(json.dumps(bench_pass()))
        sys.exit(0)
    print("STEP 0: stage + hardware data protection on", platform.machine())
    facts = machine_facts()
    print(" ", facts["machine_line"], "| dflt", facts["has_dflt"], "| nnpa", facts["has_nnpa"])
    with Timer("inflate shipped gzip streams"):
        inflate_rows = inflate()
    if (WORK / "complaints_pseud.csv").exists() and "--force" not in sys.argv:
        print("  pseudonymized extracts already exist; reusing (pass --force to redo)")
        pseud = json.loads((OUT / "z17_hardware_log.json").read_text())["pseudonymize"]
    else:
        with Timer("pseudonymize"):
            pseud = pseudonymize()
    bench = run_bench_variants()
    speed = openssl_speed()
    write_log(facts, inflate_rows, pseud, bench, speed)
    print("STEP 0 complete")

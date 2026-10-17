# LinuxONE runbook — model workstream

Everything the model needs on the instance, in order. SSH in as `linux1` with the team key.

## 1. Sanity + container (once)

```bash
uname -m                      # must say s390x — screenshot for the video
grep -o nnpa /proc/cpuinfo | head -1   # Telum accelerator check — screenshot either way

docker pull registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
docker run --network host --name notebook \
  -v /home/linux1/shared:/home/ibm-user/shared -d \
  registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x:latest
```

Change the Jupyter token before opening port 38888 — the default `Your_Token1` is in a public README (stream 3 owns ports/iptables).

## 2. Code + data

```bash
cd /home/linux1/shared
git clone https://github.com/emersoncortazar/ibm_submission.git
```

From the laptop (PowerShell), copy the data in — only these five files are needed:

```powershell
scp C:\projects\ibmz\data\hpd_heat_complaints.csv `
    C:\projects\ibmz\data\hpd_heat_violations.csv `
    C:\projects\ibmz\data\days.csv `
    C:\projects\ibmz\data\buildings.csv `
    C:\projects\ibmz\data\noaa_daily_centralpark.csv `
    linux1@<INSTANCE_IP>:/home/linux1/shared/ibm_submission/data/
```

(The 345 MB complaints file takes a few minutes. Alternative: `curl` it from the team Drive inside the instance.)

## 3. Run the pipeline inside the container

```bash
docker exec -it notebook bash
cd /home/ibm-user/shared/ibm_submission
pip install --only-binary=:all: snapml        # ONLY snapml; never upgrade numpy/pandas/sklearn/xgboost

python model/01_build_panel.py                # ~5-10 min
python model/02_train.py                      # picks up the container's XGBoost -> heat_model.json
python model/03_evaluate.py                   # the headline precision@k numbers
python model/05_backtest.py                   # all-season rolling backtest
python model/06_final_scores.py               # ranked list for the frontend map
python model/04_snapml_bench.py               # events/sec + p99 latency — THE IBM Z numbers
```

Screenshot `04`'s output next to `uname -m` for the video.

## 4. Push results back

```bash
git add model/README.md   # paste new numbers in first
git commit -m "LinuxONE run: XGBoost + Snap ML numbers"
git push
```

Instance survival rules (from docs/heat-project-brief.md §7): push to GitHub often — no backups, instances have hung mid-event; don't pickle models across machines (big-endian); don't let pip touch the preinstalled stack.

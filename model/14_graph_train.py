"""M9: GraphSAGE over the building graph, trained ON THE LINUXONE INSTANCE
(the IBM container ships PyTorch for s390x - no new dependencies).

Two mean-aggregation SAGE layers over the landlord/block hub graph, per-spell
snapshots from model/13. Train seasons 2018-2023, early-stop on 2024-25's
spells, test on the same 8 held-out 2025-26 spells as the frozen numbers -
so M9's precision@k lands directly next to M1's 86.1 / 64.6 / 51.4 / 34.8.
Frozen numbers never change; M9 is a new catalog entry whatever happens.

Run (instance container):  python model/14_graph_train.py
Writes: model/out/graph/m9_results.csv, m9_state.pt (stays on this machine)
"""

import glob
import numpy as np
import torch
import torch.nn as nn

from common import FEATS, OUT

torch.manual_seed(0)
G = OUT / "graph"
KS = (100, 500, 1000, 2500)
M1 = {100: .861, 500: .646, 1000: .514, 2500: .348}      # frozen spell p@k reference

nodes = np.load(G / "nodes.npz")
N, NB = int(nodes["n_nodes"]), int(nodes["n_buildings"])
ei = torch.from_numpy(nodes["edge_index"])
deg = torch.zeros(N).index_add_(0, ei[1], torch.ones(ei.shape[1]))
vals = 1.0 / deg.clamp(min=1)[ei[1]]
A = torch.sparse_coo_tensor(ei, vals, (N, N)).coalesce()  # row-normalized (mean of in-nbrs)

def load_spell(path):
    z = np.load(path)
    X = z["X"].copy()
    for c in ("days_since_c", "days_since_v"):
        X[:, FEATS.index(c)] = np.minimum(X[:, FEATS.index(c)], 365)
    X = np.nan_to_num(X, nan=-1.0)
    return X, z["y"].astype(np.float32), z["in_univ"], int(z["season"])

spells = sorted(glob.glob(str(G / "spell_*.npz")))
data = [(p,) + load_spell(p) for p in spells]
train = [d for d in data if 2018 <= d[4] <= 2023]
val   = [d for d in data if d[4] == 2024]
test  = [d for d in data if d[4] == 2025]
print(f"spells: train {len(train)} | val {len(val)} | test {len(test)}")

# standardize with train-universe stats; class weight from the train base rate
stk = np.vstack([d[1][d[3]] for d in train])
mu, sd = stk.mean(0), stk.std(0) + 1e-6
y_tr = np.concatenate([d[2][d[3]] for d in train])
posw = torch.tensor((1 - y_tr.mean()) / max(float(y_tr.mean()), 1e-6),
                    dtype=torch.float32)

def tensors(d):
    _, X, y, u, _ = d
    H = np.zeros((N, X.shape[1]), dtype=np.float32)
    H[:NB] = (X - mu) / sd
    return torch.from_numpy(H), torch.from_numpy(y), torch.from_numpy(u)

class Sage(nn.Module):
    def __init__(self, fin, h=64):
        super().__init__()
        self.s1, self.n1 = nn.Linear(fin, h), nn.Linear(fin, h)
        self.s2, self.n2 = nn.Linear(h, h), nn.Linear(h, h)
        self.head = nn.Linear(h, 1)
        self.act, self.drop = nn.ReLU(), nn.Dropout(0.2)

    def forward(self, H):
        H1 = self.act(self.s1(H) + self.n1(torch.sparse.mm(A, H)))
        H1 = self.drop(H1)
        H2 = self.act(self.s2(H1) + self.n2(torch.sparse.mm(A, H1)))
        return self.head(H2).squeeze(-1)

def p_at_k(model, ds):
    model.eval()
    out = {k: [] for k in KS}
    with torch.no_grad():
        for d in ds:
            H, y, u = tensors(d)
            logit = model(H)[:NB][u]
            yy = y[u]
            order = torch.argsort(logit, descending=True)
            for k in KS:
                out[k].append(yy[order[:k]].mean().item())
    return {k: float(np.mean(v)) for k, v in out.items()}

model = Sage(len(FEATS))
opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
lossf = nn.BCEWithLogitsLoss(pos_weight=posw)

best, best_state, patience = -1, None, 0
for epoch in range(30):
    model.train()
    tot = 0.0
    for d in train:
        H, y, u = tensors(d)
        opt.zero_grad()
        logit = model(H)[:NB][u]
        loss = lossf(logit, y[u])
        loss.backward()
        opt.step()
        tot += loss.item()
    vp = p_at_k(model, val)[100]
    print(f"epoch {epoch:02d} loss {tot/len(train):.4f} val p@100 {vp:.3f}", flush=True)
    if vp > best:
        best, best_state, patience = vp, {k: v.clone() for k, v in model.state_dict().items()}, 0
    else:
        patience += 1
        if patience >= 5:
            break

model.load_state_dict(best_state)
res = p_at_k(model, test)
print("\nM9 GraphSAGE on the 8 held-out 2025-26 spells (vs frozen M1):")
rows = []
for k in KS:
    print(f"  p@{k:<5} M9 {res[k]:.3f}   | M1 frozen {M1[k]:.3f}   | delta {res[k]-M1[k]:+.3f}")
    rows.append(dict(k=k, m9=round(res[k], 4), m1_frozen=M1[k], delta=round(res[k]-M1[k], 4)))
import pandas as pd
pd.DataFrame(rows).to_csv(G / "m9_results.csv", index=False)
torch.save(model.state_dict(), G / "m9_state.pt")   # same-machine artifact only
print("wrote m9_results.csv, m9_state.pt")

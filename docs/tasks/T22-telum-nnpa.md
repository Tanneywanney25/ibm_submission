# T22 — real Telum/NNPA offload: earn the accelerator claim

## Goal

Today the pitch honestly says the Snap ML number is the **CPU tree engine**
and "we don't claim accelerator offload" (model/README.md). Close that gap:
run a real model through the Telum on-chip AI accelerator (NNPA) via the
IBM Z Deep Learning Compiler / zDNN stack, measure it against CPU, and
upgrade the slide from "runs fast on LinuxONE" to "uses the z17 AI
accelerator, measured". This is the single most judge-visible LinuxONE
feature we are not using. `nnpa` is already present in the guest's
/proc/cpuinfo.

## Approach

Trees don't offload to NNPA — matrix ops do. So:

1. **Distill** the frozen scorer into a small MLP (e.g. 29→64→64→1) trained
   to mimic M13/M4's calibrated scores on the training seasons (a *new*
   model, M12-distilled, own catalog entry; the ranking it produces gets
   compared, not substituted).
2. Export ONNX (opset the zDLC supports), compile with the **IBM Z Deep
   Learning Compiler** (ships as a container image, `icr.io/ibmz/zdlc`) with
   `--maccel=NNPA`, producing a shared library callable from Python.
3. Benchmark on the guest: batch scoring and p99 single-row, NNPA build vs
   CPU build vs the existing XGBoost/Snap ML numbers, same 172,485-building
   matrix. Also report ranking agreement with the frozen scorer (Spearman,
   top-k overlap) so the distillation is honest about fidelity.
4. Write it up in `docs/model-iterations.md` + a slide figure.

Fallback if zDLC turns out impractical on the guest (container limits,
opset issues): the AI Toolkit for IBM Z builds of TensorFlow/PyTorch with
zDNN backend; document whatever was tried either way — an honest "we tried
X, hit Y" paragraph still beats silence.

## Contracts

- Nothing here touches the frozen submission numbers or the site's scoring
  path; it is a benchmark + pitch artifact. If NNPA wins, switching the
  live scorer is a *separate* decision.
- No pickles cross machines; ONNX and compiled .so live on the guest,
  results CSVs get pushed.
- Docker image pulls and runs on the guest only (8 GB RAM — watch the
  compile footprint); never let pip touch the pinned libraries.
- Account expires 2026-11-15; push benchmark outputs same-day.

## Acceptance

- [ ] A model demonstrably executes on NNPA (zDLC `--maccel=NNPA` build
      runs and its output matches the CPU build numerically).
- [ ] Benchmark table: NNPA vs CPU vs XGBoost vs Snap ML, batch + p99, plus
      distillation fidelity (top-100/2500 overlap with the frozen ranking).
- [ ] model/README.md's honest caveat replaced by the measured claim (or
      updated with the honest negative result).
- [ ] Slide figure ready.

"""Training of M1 TrendNet (PLAN_ANALYTICS 11.2).

* losses: cross-entropy (class) + Gaussian NLL (slope; only where a trend exists or
  certainly does not) + BCE per month (step), weighted;
* curriculum: the minimum SNR of planted signals falls from 0.5 to 0.05 over the first
  half of training (strong signals first);
* ensemble of 5 seeds; temperature scaling and slope-interval scaling on validation.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, IterableDataset, get_worker_info

from earthtrend.analytics.training.trendnet.data import Split, batch
from earthtrend.analytics.training.trendnet.model import Ensemble, TrendNet, n_parameters


@dataclass
class TrainConfig:
    channels: int = 128
    dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128, 1, 4, 16, 64)
    dropout: float = 0.1
    steps: int = 6000
    batch_size: int = 128
    lr: float = 2e-3
    weight_decay: float = 1e-4
    w_slope: float = 0.5
    w_step: float = 2.0
    curriculum_start_snr: float = 0.5
    curriculum_end_snr: float = 0.05
    n_members: int = 5
    seeds: tuple[int, ...] = (11, 22, 33, 44, 55)
    val_examples: int = 4096
    workers: int = 6
    amp: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class Stream(IterableDataset):  # type: ignore[type-arg]
    """Endless on-the-fly batches; each worker draws a disjoint index range."""

    def __init__(self, cfg: TrainConfig, seed: int) -> None:
        self.cfg = cfg
        self.seed = seed

    def __iter__(self):  # type: ignore[no-untyped-def]
        info = get_worker_info()
        wid = info.id if info else 0
        nw = info.num_workers if info else 1
        step = wid
        bs = self.cfg.batch_size
        while True:
            frac = min(1.0, step / max(1, self.cfg.steps // 2))
            s0, s1 = self.cfg.curriculum_start_snr, self.cfg.curriculum_end_snr
            min_snr = float(math.exp(math.log(s0) + frac * (math.log(s1) - math.log(s0))))
            start = self.seed * 100_000_000 + step * bs
            b = batch("train", range(start, start + bs), min_snr=min_snr)
            yield {k: torch.from_numpy(v) for k, v in b.items()}
            step += nw


def losses(
    out: tuple[torch.Tensor, ...], b: dict[str, torch.Tensor], cfg: TrainConfig
) -> tuple[torch.Tensor, dict[str, float]]:
    logits, mu, logvar, step_logits = out
    ce = nn.functional.cross_entropy(logits, b["label"])
    nll = 0.5 * (logvar + (b["slope"] - mu) ** 2 / torch.exp(logvar))
    nll = nll.mean()
    m = b["mask"]
    bce = nn.functional.binary_cross_entropy_with_logits(step_logits, b["step"], reduction="none")
    pos_w = 1.0 + 50.0 * b["step"]  # steps are rare: up-weight the step months
    bce = (bce * pos_w * m).sum() / m.sum()
    total = ce + cfg.w_slope * nll + cfg.w_step * bce
    return total, {"ce": float(ce), "nll": float(nll), "bce": float(bce)}


def _device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def train_member(cfg: TrainConfig, seed: int, log: list[dict[str, Any]]) -> TrendNet:
    torch.manual_seed(seed)
    dev = _device()
    model = TrendNet(cfg.channels, tuple(cfg.dilations), cfg.dropout).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=cfg.lr, total_steps=cfg.steps)
    scaler = torch.amp.GradScaler(enabled=cfg.amp and dev.type == "cuda")
    loader = DataLoader(
        Stream(cfg, seed),
        batch_size=None,
        num_workers=cfg.workers,
        persistent_workers=cfg.workers > 0,
        prefetch_factor=4 if cfg.workers else None,
    )
    model.train()
    t0 = time.perf_counter()
    for i, b in enumerate(loader):
        if i >= cfg.steps:
            break
        b = {k: v.to(dev, non_blocking=True) for k, v in b.items()}
        with torch.autocast(dev.type, enabled=cfg.amp and dev.type == "cuda"):
            out = model(b["features"], b["mask"])
        out = tuple(o.float() for o in out)
        loss, parts = losses(out, b, cfg)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(opt)
        scaler.update()
        sched.step()
        if i % 200 == 0 or i == cfg.steps - 1:
            rec = {
                "seed": seed,
                "step": i,
                "loss": float(loss),
                **parts,
                "sec": round(time.perf_counter() - t0, 1),
            }
            log.append(rec)
            print(json.dumps(rec), flush=True)
    model.eval()
    return model


@torch.no_grad()
def predict_members(
    members: list[TrendNet], split: Split, n: int, bs: int = 256, offset: int = 0
) -> dict[str, np.ndarray]:
    dev = _device()
    outs: dict[str, list[np.ndarray]] = {"logits": [], "mu": [], "logvar": [], "step": []}
    labels: dict[str, list[np.ndarray]] = {}
    for start in range(offset, offset + n, bs):
        b = batch(split, range(start, min(start + bs, offset + n)))
        f = torch.from_numpy(b["features"]).to(dev)
        m = torch.from_numpy(b["mask"]).to(dev)
        res = [mdl(f, m) for mdl in members]
        outs["logits"].append(torch.stack([r[0] for r in res]).cpu().numpy())
        outs["mu"].append(torch.stack([r[1] for r in res]).cpu().numpy())
        outs["logvar"].append(torch.stack([r[2] for r in res]).cpu().numpy())
        outs["step"].append(torch.sigmoid(torch.stack([r[3] for r in res])).mean(0).cpu().numpy())
        for k, v in b.items():
            labels.setdefault(k, []).append(v)
    res_np = {k: np.concatenate(v, axis=1 if k != "step" else 0) for k, v in outs.items()}
    res_np.update({k: np.concatenate(v) for k, v in labels.items()})
    return res_np


def fit_temperature(member_logits: np.ndarray, labels: np.ndarray) -> float:
    """Single temperature for all members, minimizing NLL of the averaged probabilities."""
    best_t, best = 1.0, np.inf
    for t in np.exp(np.linspace(np.log(0.3), np.log(5.0), 120)):
        z = member_logits / t
        z = z - z.max(-1, keepdims=True)
        p = np.exp(z) / np.exp(z).sum(-1, keepdims=True)
        pm = p.mean(0)
        nll = -np.mean(np.log(pm[np.arange(labels.size), labels] + 1e-12))
        if nll < best:
            best, best_t = nll, float(t)
    return best_t


def fit_sd_scale(
    mu: np.ndarray, logvar: np.ndarray, target: np.ndarray, level: float = 0.9
) -> float:
    """Scale of the predictive sd so the 90% interval covers 90% on validation."""
    m = mu.mean(0)
    sd = np.sqrt(np.exp(logvar).mean(0) + mu.var(0))
    z = abs(float(np.quantile(np.abs(target - m) / sd, level)))
    return z / 1.6448536


def train_ensemble(cfg: TrainConfig, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    members = [train_member(cfg, s, log) for s in cfg.seeds[: cfg.n_members]]
    val = predict_members(members, "val", cfg.val_examples)
    temperature = fit_temperature(val["logits"], val["label"])
    # The slope label (trend component) is exact for every class, incl. 0 for pure steps.
    sd_scale = fit_sd_scale(val["mu"], val["logvar"], val["slope"])
    ens = Ensemble(members, temperature, sd_scale).eval()
    torch.save(
        {
            "config": asdict(cfg),
            "state": ens.state_dict(),
            "temperature": temperature,
            "sd_scale": sd_scale,
        },
        out_dir / "ensemble.pt",
    )
    (out_dir / "train_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    return {
        "temperature": temperature,
        "sd_scale": sd_scale,
        "n_parameters_per_member": n_parameters(members[0]),
        "ensemble": ens,
    }

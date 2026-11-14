"""M1 TrendNet architecture (PLAN_ANALYTICS 11.2): dilated residual TCN + attention pooling.

Heads: class logits (5), slope mean and log-variance (Gaussian NLL), per-month step logits.
Training-only module (PyTorch); the app runs the exported ONNX ensemble.
"""

from __future__ import annotations

import torch
from torch import nn

from earthtrend.analytics.training.trendnet.data import N_CHANNELS, N_CLASSES


class ResidualBlock(nn.Module):
    def __init__(self, channels: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.conv1 = nn.Conv1d(channels, channels, 3, padding=dilation, dilation=dilation)
        self.conv2 = nn.Conv1d(channels, channels, 3, padding=dilation, dilation=dilation)
        self.norm1 = nn.GroupNorm(8, channels)
        self.norm2 = nn.GroupNorm(8, channels)
        self.act = nn.GELU()
        self.drop = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        h = self.drop(self.act(self.norm1(self.conv1(x * mask))))
        h = self.norm2(self.conv2(h * mask))
        return self.act(x + h) * mask


class TrendNet(nn.Module):
    def __init__(
        self,
        channels: int = 128,
        dilations: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64, 128, 1, 4, 16, 64),
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.inp = nn.Conv1d(N_CHANNELS, channels, 1)
        self.blocks = nn.ModuleList(ResidualBlock(channels, d, dropout) for d in dilations)
        self.attn = nn.Conv1d(channels, 1, 1)
        self.cls = nn.Sequential(
            nn.Linear(channels, channels), nn.GELU(), nn.Linear(channels, N_CLASSES)
        )
        self.reg = nn.Sequential(nn.Linear(channels, channels), nn.GELU(), nn.Linear(channels, 2))
        self.step = nn.Conv1d(channels, 1, 1)

    def forward(
        self, features: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """(B, C, L), (B, L) -> class logits, slope mean, slope log-var, step logits."""
        m = mask.unsqueeze(1)
        h = self.inp(features) * m
        for blk in self.blocks:
            h = blk(h, m)
        scores = self.attn(h).squeeze(1).masked_fill(mask < 0.5, -1e4)  # fits float16 (AMP)
        w = torch.softmax(scores, dim=-1).unsqueeze(1)
        pooled = (h * w).sum(-1)
        reg = self.reg(pooled)
        step_logits = self.step(h).squeeze(1).masked_fill(mask < 0.5, -30.0)
        return self.cls(pooled), reg[:, 0], reg[:, 1].clamp(-10, 6), step_logits


class Ensemble(nn.Module):
    """Exported model: members + temperature. Outputs the quantities ``AiOpinion`` needs."""

    def __init__(self, members: list[TrendNet], temperature: float, slope_sd_scale: float) -> None:
        super().__init__()
        self.members = nn.ModuleList(members)
        self.register_buffer("temperature", torch.tensor(float(temperature)))
        self.register_buffer("sd_scale", torch.tensor(float(slope_sd_scale)))

    def forward(
        self, features: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """-> class_probs (B,5), member_probs (K,B,5), slope mean/sd (B), step_prob (B,L)."""
        probs, means, variances, steps = [], [], [], []
        for mdl in self.members:
            logits, mu, logvar, step = mdl(features, mask)
            probs.append(torch.softmax(logits / self.temperature, dim=-1))
            means.append(mu)
            variances.append(torch.exp(logvar))
            steps.append(torch.sigmoid(step))
        p = torch.stack(probs)
        mu = torch.stack(means)
        var = torch.stack(variances).mean(0) + mu.var(0, unbiased=False)  # mixture variance
        return p.mean(0), p, mu.mean(0), torch.sqrt(var) * self.sd_scale, torch.stack(steps).mean(0)


def n_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())

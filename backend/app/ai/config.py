"""Pengaturan AI dari environment container. Mengubah .env berlaku setelah container dibuat ulang
(`docker compose up -d`); worker yang dimatikan menggagalkan job antre (`ai_disabled`) dan berhenti menyimpan hasil."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.ai.claude import claude_ready

PROVIDERS = ("fake", "claude")  # claude = app/ai/claude.py (Tahap 2 PR 4c), aktif hanya bila kunci & tarif terisi


@dataclass(frozen=True)
class AiSettings:
    enabled: bool
    provider: str
    intents: frozenset[str]
    job_estimate_micro_usd: int
    worker_timeout_s: int
    poll_interval_s: float


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name) or default)
    except ValueError:
        value = default
    return min(max(value, low), high)


def ai_settings() -> AiSettings:
    provider = (os.environ.get("CLAU_AI_PROVIDER") or "fake").strip()
    return AiSettings(
        # Fail closed: AI mati kecuali diaktifkan eksplisit, dan provider tak dikenal = mati.
        # Provider claude tanpa kunci API atau tarif model = mati juga (biaya harus bisa dihitung untuk batas biaya).
        enabled=os.environ.get("CLAU_AI_ENABLED") == "1" and provider in PROVIDERS
        and (provider != "claude" or claude_ready()),
        provider=provider,
        intents=frozenset(i.strip() for i in (os.environ.get("CLAU_AI_INTENTS") or "caption").split(",") if i.strip()),
        job_estimate_micro_usd=_int("CLAU_AI_JOB_ESTIMATE_MICRO_USD", 200_000, 0, 100_000_000),
        worker_timeout_s=_int("CLAU_AI_WORKER_TIMEOUT_S", 600, 60, 3600),
        poll_interval_s=_int("CLAU_AI_POLL_INTERVAL_S", 3, 1, 60),
    )

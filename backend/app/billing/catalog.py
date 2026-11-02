"""Katalog harga & tarif kredit. Sumber: clau-market/commercial/pricing.md (Approved v1.3.0, 2026-11-02).

Mengubah angka di sini wajib bersamaan dengan pricing.md dan landing page (web/src/data/pricing.ts). Nominal tagihan
selalu diambil dari sini oleh server, tidak pernah dari browser.
"""

from __future__ import annotations

from app.registry import load_registry

CURRENCY = "IDR"
MONTHLY_CREDITS = 500
CREDIT_PRICE_IDR = 200  # nilai jual dasar per kredit (top up 250 kredit)
TOPUP_VALID_MONTHS = 12
# Kredit percobaan (pricing.md v1.3.0 §2a): sekali per klien pendaftar mandiri, dipakai paling dulu, sisa hangus.
TRIAL_CREDITS = 50
TRIAL_DAYS = 3

# plan_months -> harga (Rp)
PLANS: dict[int, int] = {1: 149_000, 3: 399_000, 6: 749_000, 12: 1_390_000}
# kredit -> harga (Rp)
TOPUPS: dict[int, int] = {250: 50_000, 550: 100_000, 1500: 250_000}

# intent -> kredit per aksi (≥ 3x biaya provider AI per aksi; rincian biaya di price sheet privat owner).
CREDIT_COSTS: dict[str, int] = {
    "caption": 8,
    "reel-script": 13,
    "stories": 8,
    "ota-listing": 10,
    "review-reply": 3,
    "content-calendar": 18,
    "seasonal-campaign": 18,
    "localize": 5,
    "report": 20,
    "image": 29,
    "video": 111,
    "data-analysis": 20,
    "data-annotation": 10,
    "integration": 39,
    "web-dev": 39,
    "sop": 10,
    "inquiry-reply": 3,
    "guest-message": 3,
}


def save_pct(months: int) -> int:
    base = PLANS[1] * months
    return round((base - PLANS[months]) * 100 / base)


def credit_cost(intent: str) -> int | None:
    return CREDIT_COSTS.get(intent)


def catalog() -> dict:
    agents = {i: a for a in load_registry()["agents"] for i in a["intents"]}
    return {
        "currency": CURRENCY,
        "monthly_credits": MONTHLY_CREDITS,
        "trial_credits": TRIAL_CREDITS,
        "trial_days": TRIAL_DAYS,
        "plans": [{"plan_months": m, "price_idr": p, "save_pct": save_pct(m)} for m, p in PLANS.items()],
        "topups": [{"credits": c, "price_idr": p} for c, p in TOPUPS.items()],
        "credit_costs": [
            {"intent": intent, "agent": agents[intent]["display_name"] if intent in agents else None, "credits": credits,
             "status": agents[intent]["status"] if intent in agents else "planned"}
            for intent, credits in CREDIT_COSTS.items()
        ],
    }

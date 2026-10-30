"""Masa berlaku kredit top up (kontrak core 0.14.0, migrasi 0011; pricing.md §2; model kredit Sintra.ai).

Fungsi murni (tanpa database) yang membaca riwayat bucket `topup` dan menentukan:
- sisa top up yang sudah lewat `expires_at` dan harus dihanguskan (baris `topup_expire`), dan
- sisa per top up yang masih berlaku (untuk `Wallet.topup_next_expiry`).

Aturan pembagian (disimulasikan urut waktu, jadi hasilnya sama berapa kali pun dihitung):
1. `topup` membuka "lot" seberat kreditnya dengan `expires_at` (12 bulan sejak lunas).
2. Pemakaian (`usage`), penyesuaian negatif, dan pengurangan lain memotong lot yang **masih berlaku pada saat itu**,
   paling cepat kedaluwarsa dulu; lalu kredit tanpa kedaluwarsa (penyesuaian positif owner, refund).
3. Lot yang sudah lewat `expires_at` tidak bisa dipakai lagi; sisanya hangus. Data lama yang terlanjur memakai lot
   kedaluwarsa (sebelum fitur ini) diambil dari lot itu terakhir, supaya hitungan tetap konsisten dengan saldo.
4. Refund dan penyesuaian positif masuk kantong tanpa kedaluwarsa (lebih menguntungkan klien, sederhana diaudit).
5. Baris `topup_expire` yang sudah ada menutup lotnya (idempoten: satu per tagihan).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Entry:
    """Satu baris credit_ledger bucket `topup` (hanya kolom yang dibutuhkan)."""

    id: int
    created_at: datetime
    delta: int
    reason: str
    payment_id: int | None = None
    expires_at: datetime | None = None


@dataclass
class Lot:
    payment_id: int
    expires_at: datetime
    remaining: int
    closed: bool = False  # sudah punya baris topup_expire


@dataclass(frozen=True)
class Result:
    to_expire: list[tuple[int, int]]  # (payment_id, kredit yang dihanguskan)
    open_lots: list[Lot]  # top up yang masih berlaku dan bersisa, paling cepat kedaluwarsa dulu
    permanent: int  # kredit top up tanpa kedaluwarsa (penyesuaian positif, refund)


def plan(entries: list[Entry], at: datetime) -> Result:
    lots: list[Lot] = []
    by_payment: dict[int, Lot] = {}
    permanent = 0

    def take(amount: int, when: datetime) -> None:
        nonlocal permanent
        valid = sorted((x for x in lots if not x.closed and x.expires_at > when and x.remaining > 0), key=lambda x: x.expires_at)
        for lot in valid:
            used = min(lot.remaining, amount)
            lot.remaining -= used
            amount -= used
            if amount == 0:
                return
        used = min(permanent, amount)
        permanent -= used
        amount -= used
        if amount == 0:
            return
        # Data lama: pemakaian yang terlanjur memakai top up kedaluwarsa yang belum dihanguskan (paling baru dulu).
        stale = sorted((x for x in lots if not x.closed and x.remaining > 0), key=lambda x: x.expires_at, reverse=True)
        for lot in stale:
            used = min(lot.remaining, amount)
            lot.remaining -= used
            amount -= used
            if amount == 0:
                return
        # Sisa > 0 berarti riwayat tidak konsisten; database tetap menjaga saldo tidak negatif.

    for e in sorted(entries, key=lambda x: (x.created_at, x.id)):
        if e.reason == "topup":
            if e.payment_id is None or e.expires_at is None:
                permanent += e.delta  # top up tanpa masa berlaku (tidak terjadi di data normal)
                continue
            lot = Lot(payment_id=e.payment_id, expires_at=e.expires_at, remaining=e.delta)
            lots.append(lot)
            by_payment[e.payment_id] = lot
        elif e.reason == "topup_expire":
            lot = by_payment.get(e.payment_id) if e.payment_id is not None else None
            if lot is not None:
                lot.remaining = max(0, lot.remaining + e.delta)
                lot.closed = True
        elif e.delta > 0:
            permanent += e.delta
        elif e.delta < 0:
            take(-e.delta, e.created_at)

    to_expire = [(lot.payment_id, lot.remaining) for lot in lots
                 if not lot.closed and lot.expires_at <= at and lot.remaining > 0]
    open_lots = sorted((lot for lot in lots if not lot.closed and lot.expires_at > at and lot.remaining > 0),
                       key=lambda x: x.expires_at)
    return Result(to_expire=to_expire, open_lots=open_lots, permanent=permanent)


def next_expiry(result: Result) -> dict | None:
    """Kredit top up yang paling cepat hangus: {credits, expires_at} (untuk Wallet.topup_next_expiry)."""
    if not result.open_lots:
        return None
    first = result.open_lots[0]
    credits = sum(x.remaining for x in result.open_lots if x.expires_at == first.expires_at)
    return {"credits": credits, "expires_at": first.expires_at}

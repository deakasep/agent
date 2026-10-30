"""Buku kredit: saldo, hibah bulanan & hangus top up (lazy, tanpa cron), pemotongan untuk job AI, efek pembayaran lunas.

Semua penulisan ke credit_ledger dikunci per klien (advisory lock yang sama dengan trigger migrasi 0008), jadi cek
saldo + tulis tidak balapan. Aturan akhirnya tetap ditegakkan database (credit_entry_invalid / credit_insufficient).
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.billing.catalog import MONTHLY_CREDITS, TOPUP_VALID_MONTHS
from app.billing.topup_expiry import Entry, Result, plan
from app.db.models import AuditLog, CreditEntry, Payment, Subscription
from app.errors import ApiError

WITA = timezone(timedelta(hours=8))


def now() -> datetime:
    return datetime.now(timezone.utc)


def add_months(value: datetime, months: int) -> datetime:
    """Tanggal sama di bulan ke-n (31 Jan + 1 bulan = 28/29 Feb)."""
    index = value.month - 1 + months
    year, month = value.year + index // 12, index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def lock(db: Session, client_code: str) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"clau_credit:{client_code}"})


def balances(db: Session, client_code: str) -> dict[str, int]:
    rows = dict(db.execute(
        select(CreditEntry.bucket, func.coalesce(func.sum(CreditEntry.delta), 0))
        .where(CreditEntry.client_code == client_code).group_by(CreditEntry.bucket)
    ).all())
    monthly, topup = int(rows.get("monthly", 0)), int(rows.get("topup", 0))
    return {"monthly": monthly, "topup": topup, "total": monthly + topup}


def active_subscription(db: Session, client_code: str, at: datetime) -> Subscription | None:
    return db.scalar(
        select(Subscription).where(Subscription.client_code == client_code, Subscription.starts_at <= at, Subscription.ends_at > at)
        .order_by(Subscription.starts_at.desc(), Subscription.id.desc()).limit(1)
    )


def current_period(sub: Subscription, at: datetime) -> tuple[datetime, datetime]:
    """Periode kredit bulanan yang memuat `at`: [mulai, mulai + 1 bulan), dipotong di akhir langganan."""
    k = 0
    while add_months(sub.starts_at, k + 1) <= at:
        k += 1
    start = add_months(sub.starts_at, k)
    return start, min(add_months(sub.starts_at, k + 1), sub.ends_at)


def wita_date(value: datetime) -> date:
    return value.astimezone(WITA).date()


def ensure_monthly(db: Session, client_code: str, at: datetime | None = None) -> None:
    """Kredit bulanan periode berjalan: sisa periode lalu hangus (monthly_expire), lalu hibah baru (monthly_grant).
    Tanpa langganan aktif, sisa kredit bulanan hangus. Idempoten (indeks unik per langganan + periode)."""
    at = at or now()
    lock(db, client_code)
    monthly = balances(db, client_code)["monthly"]
    sub = active_subscription(db, client_code, at)
    if sub is None:
        if monthly > 0:
            last = db.scalar(select(Subscription).where(Subscription.client_code == client_code)
                             .order_by(Subscription.ends_at.desc(), Subscription.id.desc()).limit(1))
            if last is not None:
                db.add(CreditEntry(client_code=client_code, delta=-monthly, bucket="monthly", reason="monthly_expire",
                                   subscription_id=last.id, period_start=wita_date(last.ends_at)))
                db.flush()
        return
    start, _ = current_period(sub, at)
    period = wita_date(start)
    granted = db.scalar(select(CreditEntry.id).where(
        CreditEntry.subscription_id == sub.id, CreditEntry.period_start == period, CreditEntry.reason == "monthly_grant"))
    if granted is not None:
        return
    if monthly > 0:
        db.add(CreditEntry(client_code=client_code, delta=-monthly, bucket="monthly", reason="monthly_expire",
                           subscription_id=sub.id, period_start=period))
        db.flush()
    db.add(CreditEntry(client_code=client_code, delta=MONTHLY_CREDITS, bucket="monthly", reason="monthly_grant",
                       subscription_id=sub.id, period_start=period))
    db.flush()


def topup_entries(db: Session, client_code: str) -> list[Entry]:
    rows = db.execute(
        select(CreditEntry.id, CreditEntry.created_at, CreditEntry.delta, CreditEntry.reason, CreditEntry.payment_id, CreditEntry.expires_at)
        .where(CreditEntry.client_code == client_code, CreditEntry.bucket == "topup")
    ).all()
    return [Entry(id=r.id, created_at=r.created_at, delta=r.delta, reason=r.reason, payment_id=r.payment_id, expires_at=r.expires_at)
            for r in rows]


def ensure_topup_expiry(db: Session, client_code: str, at: datetime | None = None) -> Result:
    """Sisa top up yang lewat masa berlakunya (12 bulan sejak lunas) dihanguskan lewat `topup_expire` (migrasi 0011).
    Lazy seperti kredit bulanan: dipanggil saat dompet dibaca dan sebelum kredit dipotong. Idempoten."""
    at = at or now()
    lock(db, client_code)
    # Trigger memakai now() transaksi; jangan menghanguskan lebih awal dari waktu database.
    at = min(at, db.scalar(select(func.now())))
    result = plan(topup_entries(db, client_code), at)
    if result.to_expire:
        available = balances(db, client_code)["topup"]
        for payment_id, credits in result.to_expire:
            amount = min(credits, available)
            if amount <= 0:
                continue
            db.add(CreditEntry(client_code=client_code, delta=-amount, bucket="topup", reason="topup_expire", payment_id=payment_id))
            available -= amount
        db.flush()
        result = plan(topup_entries(db, client_code), at)
    return result


def ensure_credits(db: Session, client_code: str, at: datetime | None = None) -> Result:
    """Kredit bulanan periode berjalan + hangus top up kedaluwarsa, dalam satu kunci per klien."""
    at = at or now()
    ensure_monthly(db, client_code, at)
    return ensure_topup_expiry(db, client_code, at)


def charge(db: Session, client_code: str, credits: int, ai_job_id: int) -> list[CreditEntry]:
    """Potong kredit untuk job AI yang baru dibuat: bulanan dulu, lalu top up (yang paling cepat kedaluwarsa; pembagian
    per top up dihitung app/billing/topup_expiry.py). Saldo kurang → 402, sebelum commit."""
    ensure_credits(db, client_code)
    bal = balances(db, client_code)
    if bal["total"] < credits:
        raise ApiError(402, "credits_insufficient", f"Kredit tidak cukup: butuh {credits}, sisa {bal['total']}. Top up dari dashboard.")
    from_monthly = min(bal["monthly"], credits)
    rows = []
    for bucket, amount in (("monthly", from_monthly), ("topup", credits - from_monthly)):
        if amount > 0:
            rows.append(CreditEntry(client_code=client_code, delta=-amount, bucket=bucket, reason="usage", ai_job_id=ai_job_id))
    db.add_all(rows)
    db.flush()
    return rows


def apply_paid(db: Session, payment: Payment, method: str | None = None, at: datetime | None = None) -> None:
    """Tagihan lunas → paket aktif (+ kredit bulan pertama) atau kredit top up. Pemanggil mengunci baris tagihan."""
    at = at or now()
    payment.status, payment.paid_at = "paid", at
    if method:
        payment.method = method[:40]
    db.flush()
    lock(db, payment.client_code)
    if payment.kind == "subscription":
        latest_end = db.scalar(select(func.max(Subscription.ends_at)).where(Subscription.client_code == payment.client_code))
        start = max(at, latest_end) if latest_end else at
        sub = Subscription(client_code=payment.client_code, payment_id=payment.id, plan_months=payment.plan_months,
                           starts_at=start, ends_at=add_months(start, payment.plan_months))
        db.add(sub)
        db.flush()
        ensure_monthly(db, payment.client_code, at)
        meta = {"subscription_id": sub.id, "plan_months": sub.plan_months}
    else:
        entry = CreditEntry(client_code=payment.client_code, delta=payment.credits, bucket="topup", reason="topup",
                            payment_id=payment.id, expires_at=add_months(at, TOPUP_VALID_MONTHS))
        db.add(entry)
        db.flush()
        meta = {"credits": payment.credits}
    db.add(AuditLog(actor_id=None, action="payment.paid", object_type="payment", object_id=str(payment.id),
                    meta={"client_code": payment.client_code, "kind": payment.kind, "amount_idr": payment.amount_idr, **meta}))

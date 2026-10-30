"""Masa berlaku kredit top up (kontrak core 0.14.0): unit test fungsi murni, tanpa database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.billing.topup_expiry import Entry, next_expiry, plan

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def d(days: int) -> datetime:
    return T0 + timedelta(days=days)


def topup(i: int, day: int, credits: int, pid: int, valid_days: int = 365) -> Entry:
    return Entry(id=i, created_at=d(day), delta=credits, reason="topup", payment_id=pid, expires_at=d(day + valid_days))


def use(i: int, day: int, credits: int) -> Entry:
    return Entry(id=i, created_at=d(day), delta=-credits, reason="usage")


def test_unused_topup_expires_after_validity():
    entries = [topup(1, 0, 250, pid=10)]
    assert plan(entries, d(364)).to_expire == []
    assert plan(entries, d(365)).to_expire == [(10, 250)]


def test_usage_takes_soonest_expiring_topup_first():
    entries = [topup(1, 0, 250, pid=10), topup(2, 100, 550, pid=11), use(3, 200, 300)]
    r = plan(entries, d(300))
    assert {x.payment_id: x.remaining for x in r.open_lots} == {11: 500}  # lot 10 habis dipakai dulu
    assert plan(entries, d(366)).to_expire == []  # lot 10 sudah habis, tidak ada yang hangus
    assert plan(entries, d(466)).to_expire == [(11, 500)]


def test_usage_after_expiry_never_draws_from_expired_topup():
    entries = [topup(1, 0, 250, pid=10), topup(2, 100, 550, pid=11), use(3, 400, 100)]
    r = plan(entries, d(400))
    assert r.to_expire == [(10, 250)]
    assert {x.payment_id: x.remaining for x in r.open_lots} == {11: 450}


def test_existing_expire_row_is_idempotent():
    entries = [topup(1, 0, 250, pid=10), Entry(id=2, created_at=d(366), delta=-250, reason="topup_expire", payment_id=10)]
    r = plan(entries, d(500))
    assert r.to_expire == [] and r.open_lots == []


def test_refund_and_positive_adjustment_never_expire():
    entries = [
        topup(1, 0, 250, pid=10),
        use(2, 10, 50),
        Entry(id=3, created_at=d(11), delta=50, reason="refund"),
        Entry(id=4, created_at=d(12), delta=20, reason="adjustment"),
    ]
    r = plan(entries, d(400))
    assert r.to_expire == [(10, 200)]  # 50 terpakai dari lot; refund 50 + bonus 20 tetap
    assert r.permanent == 70


def test_permanent_credits_used_after_expiring_topups():
    entries = [Entry(id=1, created_at=d(0), delta=100, reason="adjustment"), topup(2, 1, 250, pid=10), use(3, 5, 120)]
    r = plan(entries, d(10))
    assert {x.payment_id: x.remaining for x in r.open_lots} == {10: 130}
    assert r.permanent == 100


def test_legacy_usage_from_expired_lot_keeps_totals_consistent():
    # Sebelum fitur ini, pemakaian bisa terjadi setelah lot kedaluwarsa (belum dihanguskan).
    entries = [topup(1, 0, 250, pid=10), use(2, 400, 100)]
    r = plan(entries, d(401))
    assert r.to_expire == [(10, 150)]  # 250 - 100 yang terlanjur dipakai; saldo akhir 0


def test_next_expiry_reports_soonest_lot():
    entries = [topup(1, 0, 250, pid=10), topup(2, 30, 550, pid=11), use(3, 40, 50)]
    assert next_expiry(plan(entries, d(50))) == {"credits": 200, "expires_at": d(365)}
    assert next_expiry(plan([], d(0))) is None

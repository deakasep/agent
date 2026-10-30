"""Endpoint langganan & kredit (kontrak core api-contracts 0.11.0 § Langganan & Kredit).

Nominal & kredit selalu dari katalog server. Status lunas hanya dari webhook Midtrans bertanda tangan valid, atau
simulasi owner untuk provider `fake` di luar produksi. Tidak ada data kartu/rekening yang diterima atau disimpan.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.access import can_access_client
from app.auth.deps import AuthContext, current_user, get_db, require_owner
from app.billing.catalog import PLANS, TOPUPS, catalog
from app.billing.ledger import active_subscription, apply_paid, balances, current_period, ensure_credits, ensure_topup_expiry, lock, now
from app.billing.topup_expiry import next_expiry
from app.billing.provider import (
    GatewayError,
    billing_settings,
    create_payment_url,
    midtrans_outcome,
    midtrans_signature_valid,
)
from app.db.models import CLIENT_CODE_RE, AuditLog, Client, CreditEntry, Payment
from app.errors import ApiError
from app.workflow import Body, Page, audit, check_list_scope, forbidden, iso, not_found, page, paged, role_for

router = APIRouter(prefix="/billing")
PENDING_WINDOW = timedelta(hours=24)


def entry_json(e: CreditEntry) -> dict:
    return {
        "id": e.id, "client_code": e.client_code, "delta": e.delta, "bucket": e.bucket, "reason": e.reason,
        "subscription_id": e.subscription_id, "period_start": iso(e.period_start), "payment_id": e.payment_id,
        "ai_job_id": e.ai_job_id, "expires_at": iso(e.expires_at), "note": e.note, "created_by": e.created_by,
        "created_at": iso(e.created_at),
    }


_NO_URL = object()


def payment_json(p: Payment, payment_url: object = _NO_URL) -> dict:
    out = {
        "id": p.id, "client_code": p.client_code, "kind": p.kind, "plan_months": p.plan_months, "credits": p.credits,
        "amount_idr": p.amount_idr, "provider": p.provider, "order_id": p.order_id, "status": p.status, "method": p.method,
        "requested_by": p.requested_by, "created_at": iso(p.created_at), "paid_at": iso(p.paid_at),
    }
    if payment_url is not _NO_URL:
        out["payment_url"] = payment_url  # checkout: URL Snap, atau None untuk mode uji
    return out


def require_client(db: Session, ctx: AuthContext, client_code: str) -> Client:
    client = db.get(Client, client_code)
    if client is None or not can_access_client(ctx.memberships, client_code):
        raise ApiError(404, "client_not_found", "Klien tidak dikenal.")
    return client


@router.get("/catalog")
def get_catalog() -> dict:
    return catalog()


@router.get("/wallet")
def get_wallet(client_code: str = Query(pattern=CLIENT_CODE_RE), ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    client = require_client(db, ctx, client_code)
    at = now()
    expiry = next_expiry(ensure_credits(db, client_code, at))
    db.commit()
    sub = active_subscription(db, client_code, at)
    subscription = None
    if sub is not None:
        start, nxt = current_period(sub, at)
        subscription = {"plan_months": sub.plan_months, "starts_at": iso(sub.starts_at), "ends_at": iso(sub.ends_at),
                        "active": True, "period_start": iso(start), "next_reset": iso(nxt) if nxt < sub.ends_at else None}
    topup_next_expiry = {"credits": expiry["credits"], "expires_at": iso(expiry["expires_at"])} if expiry else None
    return {"client_code": client_code, "balance": balances(db, client_code), "subscription": subscription,
            "topup_next_expiry": topup_next_expiry, "simulation": client.simulation}


@router.get("/ledger")
def list_ledger(client_code: str = Query(pattern=CLIENT_CODE_RE), p: Page = Depends(page), ctx: AuthContext = Depends(current_user),
                db: Session = Depends(get_db)) -> dict:
    require_client(db, ctx, client_code)
    stmt = select(CreditEntry).where(CreditEntry.client_code == client_code).order_by(CreditEntry.created_at.desc(), CreditEntry.id.desc())
    rows, total = paged(db, stmt, p)
    return {"items": [entry_json(e) for (e,) in rows], "total": total, "limit": p.limit, "offset": p.offset}


@router.get("/payments")
def list_payments(client_code: str | None = Query(None, pattern=CLIENT_CODE_RE), p: Page = Depends(page),
                  ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    visible = check_list_scope(ctx, client_code)
    stmt = select(Payment).order_by(Payment.created_at.desc(), Payment.id.desc())
    if visible is not None:
        stmt = stmt.where(Payment.client_code.in_(visible))
    if client_code:
        stmt = stmt.where(Payment.client_code == client_code)
    rows, total = paged(db, stmt, p)
    return {"items": [payment_json(x) for (x,) in rows], "total": total, "limit": p.limit, "offset": p.offset}


class CheckoutIn(Body):
    client_code: str = Field(pattern=CLIENT_CODE_RE)
    kind: Literal["subscription", "topup"]
    plan_months: int | None = None
    topup_credits: int | None = None


@router.post("/checkout", status_code=201)
def checkout(body: CheckoutIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    settings = billing_settings()
    client = require_client(db, ctx, body.client_code)
    if role_for(ctx, body.client_code) not in ("owner", "client_approver"):
        raise forbidden("Hanya owner atau approver klien yang membayar paket/top up.")
    if not settings.enabled:
        raise ApiError(409, "billing_disabled", "Pembayaran sedang tidak tersedia.")
    if body.kind == "subscription":
        if body.plan_months not in PLANS or body.topup_credits is not None:
            raise ApiError(422, "invalid_plan", "Pilih durasi paket 1, 3, 6, atau 12 bulan.")
        amount, plan_months, credits, item = PLANS[body.plan_months], body.plan_months, None, f"CLAU AI paket {body.plan_months} bulan"
    else:
        if body.topup_credits not in TOPUPS or body.plan_months is not None:
            raise ApiError(422, "invalid_plan", "Pilih paket top up yang tersedia.")
        amount, plan_months, credits, item = TOPUPS[body.topup_credits], None, body.topup_credits, f"CLAU AI top up {body.topup_credits} kredit"
    lock(db, client.client_code)
    pending = db.scalar(select(Payment.id).where(Payment.client_code == client.client_code, Payment.status == "pending",
                                                 Payment.created_at > now() - PENDING_WINDOW))
    if pending is not None:
        raise ApiError(409, "payment_pending_exists", "Masih ada tagihan yang belum dibayar; selesaikan atau tunggu kedaluwarsa.")
    payment = Payment(client_code=client.client_code, kind=body.kind, plan_months=plan_months, credits=credits, amount_idr=amount,
                      provider=settings.provider, requested_by=ctx.user.id,
                      # Unik & tidak bisa ditebak; tidak diubah setelah dibuat (payment_transition).
                      order_id=f"CLAU-{client.client_code}-{int(now().timestamp())}-{secrets.token_hex(6)}")
    db.add(payment)
    db.flush()
    try:
        url = create_payment_url(settings, payment.order_id, amount, item)
    except GatewayError as exc:
        db.rollback()
        raise ApiError(503, "payment_gateway_unavailable", "Payment gateway tidak bisa dihubungi; coba lagi.") from exc
    audit(db, ctx, "payment.create", "payment", payment.id, client_code=client.client_code, kind=body.kind, amount_idr=amount)
    db.commit()
    return payment_json(payment, url)


@router.post("/payments/{payment_id}/simulate-paid")
def simulate_paid(payment_id: int, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    settings = billing_settings()
    if settings.environment == "production":
        raise ApiError(409, "billing_simulation_disabled", "Simulasi pembayaran tidak tersedia di produksi.")
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise not_found()
    if payment.provider != "fake":
        raise ApiError(409, "billing_simulation_disabled", "Simulasi hanya untuk tagihan mode uji.")
    if payment.status != "pending":
        raise ApiError(409, "payment_not_pending", "Tagihan sudah selesai.")
    apply_paid(db, payment, method="simulasi")
    audit(db, ctx, "payment.simulate_paid", "payment", payment.id, client_code=payment.client_code)
    db.commit()
    return payment_json(payment)


@router.post("/webhooks/midtrans")
async def midtrans_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Notifikasi Midtrans (tanpa sesi/CSRF): tanda tangan wajib valid, nominal wajib sama, idempoten."""
    settings = billing_settings()
    try:
        payload = await request.json()
    except ValueError as exc:
        raise ApiError(422, "validation_error", "Request tidak valid: body") from exc
    if not isinstance(payload, dict) or not midtrans_signature_valid(payload, settings.midtrans_server_key):
        raise ApiError(401, "invalid_signature", "Tanda tangan notifikasi tidak valid.")
    payment = db.scalar(select(Payment).where(Payment.order_id == payload["order_id"]).with_for_update())
    if payment is None or payment.provider != "midtrans":
        raise not_found()
    try:
        amount_ok = round(float(payload["gross_amount"])) == payment.amount_idr
    except ValueError:
        amount_ok = False
    if not amount_ok:
        db.add(AuditLog(actor_id=None, action="payment.amount_mismatch", object_type="payment", object_id=str(payment.id), meta={}))
        db.commit()
        raise ApiError(409, "amount_mismatch", "Nominal notifikasi tidak sama dengan tagihan.")
    outcome = midtrans_outcome(payload)
    if outcome is None or payment.status != "pending":
        return {"ok": True}  # belum final, atau notifikasi ulang: tidak ada efek ganda
    method = payload.get("payment_type") if isinstance(payload.get("payment_type"), str) else None
    if outcome == "paid":
        apply_paid(db, payment, method=method)
    else:
        payment.status = outcome
        db.add(AuditLog(actor_id=None, action=f"payment.{outcome}", object_type="payment", object_id=str(payment.id),
                        meta={"client_code": payment.client_code}))
    db.commit()
    return {"ok": True}


class AdjustmentIn(Body):
    client_code: str = Field(pattern=CLIENT_CODE_RE)
    credits: int = Field(ge=-100_000, le=100_000)
    note: str = Field(min_length=3, max_length=300)


@router.post("/adjustments", status_code=201)
def adjust(body: AdjustmentIn, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    if body.credits == 0:
        raise ApiError(422, "validation_error", "Request tidak valid: credits")
    require_client(db, ctx, body.client_code)
    ensure_topup_expiry(db, body.client_code)  # top up kedaluwarsa tidak ikut dihitung sebagai saldo yang bisa dikurangi
    if balances(db, body.client_code)["topup"] + body.credits < 0:
        raise ApiError(409, "credit_insufficient", "Saldo kredit tidak cukup untuk dikurangi sebanyak itu.")
    entry = CreditEntry(client_code=body.client_code, delta=body.credits, bucket="topup", reason="adjustment",
                        note=body.note, created_by=ctx.user.id)
    db.add(entry)
    db.flush()
    audit(db, ctx, "credit.adjust", "credit_entry", entry.id, client_code=body.client_code, credits=body.credits)
    db.commit()
    return entry_json(entry)

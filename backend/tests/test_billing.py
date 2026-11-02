"""Langganan & kredit (kontrak core 0.11.0 + 0.14.0 hangus top up + 0.15.0 kredit percobaan, AI-CONSTITUTION v4.0.0 §4b, AI-BOUNDARY 2.0.0), ke PostgreSQL sungguhan.

Menguji: katalog sama dengan registry & harga publik, checkout (peran, nominal dari server, satu tagihan pending),
lunas lewat simulasi owner dan webhook Midtrans bertanda tangan (idempoten, nominal dicek), kredit bulanan (hibah &
hangus per periode), pemotongan kredit saat job AI dibuat (402 bila kurang), refund otomatis saat job dibatalkan, dan
aturan database migrasi 0008 (append-only, tidak ada kredit dari udara, saldo tidak negatif).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.billing import catalog as cat
from app.billing.provider import midtrans_outcome, midtrans_signature_valid
from app.registry import load_registry

# --- Unit (tanpa database) ----------------------------------------------------------------------------------------


def test_every_registry_intent_has_a_credit_price():
    intents = {i for a in load_registry()["agents"] for i in a["intents"]}
    assert intents == set(cat.CREDIT_COSTS), sorted(intents ^ set(cat.CREDIT_COSTS))
    assert all(isinstance(v, int) and v >= 1 for v in cat.CREDIT_COSTS.values())


def test_public_prices_match_pricing_md():
    # clau-market/commercial/pricing.md v1.0.0 & landing page web/src/data/pricing.ts.
    assert cat.PLANS == {1: 149_000, 3: 399_000, 6: 749_000, 12: 1_390_000}
    assert cat.TOPUPS == {250: 50_000, 550: 100_000, 1500: 250_000}
    assert cat.MONTHLY_CREDITS == 500
    assert [cat.save_pct(m) for m in (1, 3, 6, 12)] == [0, 11, 16, 22]
    # Top up tidak pernah lebih murah per kredit daripada batas margin (Rp200 / 1,2 bonus terbesar).
    assert all(price / credits >= cat.CREDIT_PRICE_IDR / 1.25 for credits, price in cat.TOPUPS.items())


def test_add_months_clamps_day():
    add_months = pytest.importorskip("app.billing.ledger").add_months
    t = datetime(2027, 1, 31, 9, tzinfo=timezone.utc)
    assert add_months(t, 1) == datetime(2027, 2, 28, 9, tzinfo=timezone.utc)
    assert add_months(t, 12) == datetime(2028, 1, 31, 9, tzinfo=timezone.utc)
    assert add_months(datetime(2026, 11, 15, tzinfo=timezone.utc), 3) == datetime(2027, 2, 15, tzinfo=timezone.utc)


def sign(order_id: str, status_code: str, gross: str, key: str) -> str:
    return hashlib.sha512(f"{order_id}{status_code}{gross}{key}".encode()).hexdigest()


def test_midtrans_signature_and_outcome():
    p = {"order_id": "CLAU-AB-1-abcdef", "status_code": "200", "gross_amount": "50000.00"}
    good = {**p, "signature_key": sign(p["order_id"], "200", "50000.00", "kunci")}
    assert midtrans_signature_valid(good, "kunci")
    assert not midtrans_signature_valid(good, "kunci-lain")
    assert not midtrans_signature_valid({**good, "gross_amount": "1.00"}, "kunci")
    assert not midtrans_signature_valid(good, "")  # tanpa server key = selalu tolak
    assert not midtrans_signature_valid({**good, "signature_key": 5}, "kunci")
    assert midtrans_outcome({"transaction_status": "settlement"}) == "paid"
    assert midtrans_outcome({"transaction_status": "capture", "fraud_status": "accept"}) == "paid"
    assert midtrans_outcome({"transaction_status": "capture", "fraud_status": "challenge"}) is None
    assert midtrans_outcome({"transaction_status": "pending"}) is None
    assert midtrans_outcome({"transaction_status": "expire"}) == "expired"
    assert midtrans_outcome({"transaction_status": "deny"}) == "failed"


# --- Database & API -----------------------------------------------------------------------------------------------

pytest.importorskip("pyotp")
pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402

import app.billing.routes as billing_routes  # noqa: E402
from app.billing.ledger import balances, ensure_monthly  # noqa: E402
from app.db.models import AiJob, Client, CreditEntry, Payment  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_ai import ai, ai_on, ask_ai  # noqa: E402,F401
from tests.test_workflow import Actor, engine, fact_sheet, factory, new_request, team  # noqa: E402,F401

SERVER_KEY = "uji-server-key-sandbox"


@pytest.fixture(scope="module")
def bill(factory, team):
    with factory() as s, s.begin():
        for code in ("BILA", "BILB", "BILC"):
            s.add(Client(client_code=code, vertical="accommodation", business_type="villa", approver_role="owner"))
    return {code: Actor(factory, "client_approver", scope=code, level="L2") for code in ("BILA", "BILB", "BILC")}


def wallet(actor, code):
    r = actor.get("/billing/wallet", client_code=code)
    assert r.status_code == 200, r.text
    return r.json()


def test_catalog_is_public_and_complete():
    r = TestClient(app).get("/billing/catalog")
    assert r.status_code == 200
    data = r.json()
    assert data["monthly_credits"] == 500 and data["currency"] == "IDR"
    assert (data["trial_credits"], data["trial_days"]) == (50, 3)
    assert [(p["plan_months"], p["price_idr"]) for p in data["plans"]] == [(1, 149000), (3, 399000), (6, 749000), (12, 1390000)]
    caption = next(c for c in data["credit_costs"] if c["intent"] == "caption")
    assert caption == {"intent": "caption", "agent": "Tara", "credits": 8, "status": "active"}


def test_checkout_roles_amount_and_single_pending(factory, team, bill, monkeypatch):
    monkeypatch.setenv("CLAU_PAYMENT_PROVIDER", "fake")
    approver = bill["BILA"]
    assert team["staff"].post("/billing/checkout", {"client_code": "BILA", "kind": "topup", "topup_credits": 250}).status_code == 403
    assert bill["BILB"].post("/billing/checkout", {"client_code": "BILA", "kind": "topup", "topup_credits": 250}).status_code == 404
    bad = approver.post("/billing/checkout", {"client_code": "BILA", "kind": "subscription", "plan_months": 2})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_plan"
    # Nominal tidak bisa dikirim browser.
    assert approver.post("/billing/checkout", {"client_code": "BILA", "kind": "topup", "topup_credits": 250, "amount_idr": 1}).status_code == 422

    r = approver.post("/billing/checkout", {"client_code": "BILA", "kind": "subscription", "plan_months": 3})
    assert r.status_code == 201, r.text
    pay = r.json()
    assert (pay["status"], pay["amount_idr"], pay["provider"], pay["payment_url"]) == ("pending", 399000, "fake", None)
    assert pay["order_id"].startswith("CLAU-BILA-")
    again = approver.post("/billing/checkout", {"client_code": "BILA", "kind": "topup", "topup_credits": 250})
    assert again.status_code == 409 and again.json()["error"]["code"] == "payment_pending_exists"

    # Klien tidak bisa melunasi sendiri; owner hanya lewat simulasi (provider fake, non-produksi).
    assert approver.post(f"/billing/payments/{pay['id']}/simulate-paid", {}).status_code == 403
    monkeypatch.setenv("CLAU_ENV", "production")
    r = team["owner"].post(f"/billing/payments/{pay['id']}/simulate-paid", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "billing_simulation_disabled"
    monkeypatch.delenv("CLAU_ENV", raising=False)  # kembali ke nilai test (cookie sesi tetap sama)
    r = team["owner"].post(f"/billing/payments/{pay['id']}/simulate-paid", {})
    assert r.status_code == 200 and r.json()["status"] == "paid", r.text
    r = team["owner"].post(f"/billing/payments/{pay['id']}/simulate-paid", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment_not_pending"

    w = wallet(approver, "BILA")
    assert w["balance"] == {"monthly": 500, "topup": 0, "trial": 0, "total": 500}
    assert w["subscription"]["plan_months"] == 3 and w["subscription"]["active"] and w["subscription"]["next_reset"]
    reasons = [e["reason"] for e in approver.get("/billing/ledger", client_code="BILA").json()["items"]]
    assert reasons == ["monthly_grant"]
    # Wallet berulang tidak memberi kredit lagi (idempoten).
    assert wallet(approver, "BILA")["balance"]["total"] == 500
    assert team["other"].get("/billing/wallet", client_code="BILA").status_code == 404  # klien lain


def test_monthly_credits_expire_and_renew_each_period(factory, bill):
    approver = bill["BILA"]
    with factory() as s, s.begin():
        ensure_monthly(s, "BILA", datetime.now(timezone.utc) + timedelta(days=40))
    with factory() as s:
        rows = list(s.scalars(select(CreditEntry).where(CreditEntry.client_code == "BILA").order_by(CreditEntry.id)))
        assert [(r.reason, r.delta) for r in rows] == [("monthly_grant", 500), ("monthly_expire", -500), ("monthly_grant", 500)]
        assert balances(s, "BILA")["monthly"] == 500
    assert wallet(approver, "BILA")["balance"]["monthly"] == 500


def test_midtrans_webhook_is_signed_checked_and_idempotent(factory, team, bill, monkeypatch):
    monkeypatch.setenv("CLAU_PAYMENT_PROVIDER", "midtrans")
    monkeypatch.setenv("CLAU_MIDTRANS_SERVER_KEY", SERVER_KEY)
    monkeypatch.setattr(billing_routes, "create_payment_url", lambda *a, **k: "https://app.sandbox.midtrans.com/snap/v2/vtweb/uji")
    approver = bill["BILB"]
    r = approver.post("/billing/checkout", {"client_code": "BILB", "kind": "topup", "topup_credits": 550})
    assert r.status_code == 201, r.text
    pay = r.json()
    assert pay["payment_url"].startswith("https://") and pay["amount_idr"] == 100000
    hook = TestClient(app)
    body = {"order_id": pay["order_id"], "status_code": "200", "gross_amount": "100000.00", "transaction_status": "settlement",
            "payment_type": "qris"}

    forged = hook.post("/billing/webhooks/midtrans", json={**body, "signature_key": sign(pay["order_id"], "200", "100000.00", "salah")})
    assert forged.status_code == 401 and forged.json()["error"]["code"] == "invalid_signature"
    cheap = {**body, "gross_amount": "1000.00"}
    r = hook.post("/billing/webhooks/midtrans", json={**cheap, "signature_key": sign(pay["order_id"], "200", "1000.00", SERVER_KEY)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "amount_mismatch"
    assert wallet(approver, "BILB")["balance"]["topup"] == 0

    good = {**body, "signature_key": sign(pay["order_id"], "200", "100000.00", SERVER_KEY)}
    assert hook.post("/billing/webhooks/midtrans", json=good).json() == {"ok": True}
    assert hook.post("/billing/webhooks/midtrans", json=good).json() == {"ok": True}  # notifikasi ulang
    assert wallet(approver, "BILB")["balance"] == {"monthly": 0, "topup": 550, "trial": 0, "total": 550}
    with factory() as s:
        p = s.get(Payment, pay["id"])
        assert (p.status, p.method) == ("paid", "qris")
    # Notifikasi "expire" setelah lunas tidak mengubah apa pun.
    late = {**body, "transaction_status": "expire", "status_code": "407", "signature_key": sign(pay["order_id"], "407", "100000.00", SERVER_KEY)}
    assert hook.post("/billing/webhooks/midtrans", json=late).json() == {"ok": True}
    assert approver.get("/billing/payments", client_code="BILB").json()["items"][0]["status"] == "paid"


def test_ai_job_charges_credits_and_refunds_on_cancel(factory, team, ai, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    staff, owner = team["staff"], team["owner"]
    before = wallet(owner, "CTH")["balance"]["total"]
    req = new_request(staff, client="CTH")
    r = ask_ai(staff, req["id"])
    assert r.status_code == 202, r.text
    job = r.json()
    assert wallet(owner, "CTH")["balance"]["total"] == before - 8
    usage = [e for e in owner.get("/billing/ledger", client_code="CTH").json()["items"] if e["ai_job_id"] == job["id"]]
    assert [(e["reason"], e["delta"]) for e in usage] == [("usage", -8)]
    assert staff.post(f"/ai-jobs/{job['id']}/cancel", {}).status_code == 200
    assert wallet(owner, "CTH")["balance"]["total"] == before
    entries = {(e["reason"], e["delta"]) for e in owner.get("/billing/ledger", client_code="CTH").json()["items"] if e["ai_job_id"] == job["id"]}
    assert entries == {("usage", -8), ("refund", 8)}


def test_ai_job_refused_without_credits(factory, team, ai, bill, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    fact_sheet(factory, client="BILC", keys=("facility.pool-private",), confirmer=bill["BILC"].id)
    req = new_request(team["staff"], client="BILC")
    r = ask_ai(team["staff"], req["id"])
    assert r.status_code == 402 and r.json()["error"]["code"] == "credits_insufficient"
    with factory() as s:
        assert s.scalar(select(AiJob.id).where(AiJob.request_id == req["id"])) is None  # job ikut batal


def test_simulation_client_is_not_charged(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    assert ask_ai(team["staff"], req["id"]).status_code == 202
    with factory() as s:
        assert s.scalar(select(CreditEntry.id).where(CreditEntry.client_code == "CTHSIM")) is None


def test_owner_adjustment_rules(team, bill):
    r = team["owner"].post("/billing/adjustments", {"client_code": "BILC", "credits": -10, "note": "koreksi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "credit_insufficient"
    assert bill["BILC"].post("/billing/adjustments", {"client_code": "BILC", "credits": 10, "note": "hadiah"}).status_code == 403
    r = team["owner"].post("/billing/adjustments", {"client_code": "BILC", "credits": 20, "note": "kompensasi gangguan"})
    assert r.status_code == 201 and r.json()["reason"] == "adjustment"


def violates(session, rule: str, statement: str, params: dict | None = None):
    from sqlalchemy import text

    with pytest.raises((DBAPIError, IntegrityError)) as err:
        session.execute(text(statement), params or {})
        session.flush()
    session.rollback()
    assert rule in str(err.value), f"diharapkan {rule!r}, dapat: {err.value}"


def test_database_rules_for_credits_and_payments(factory, team, bill):
    with factory() as s:
        # Kredit tidak bisa dibuat dari udara: top up tanpa tagihan lunas, pemakaian positif, saldo negatif.
        violates(s, "credit_entry_invalid", "INSERT INTO credit_ledger (client_code, delta, bucket, reason) VALUES ('BILC', 999, 'topup', 'topup')")
        violates(s, "credit_entry_invalid", "INSERT INTO credit_ledger (client_code, delta, bucket, reason, ai_job_id) VALUES ('BILC', 5, 'topup', 'usage', 1)")
        violates(s, "credit_entry_invalid", "INSERT INTO credit_ledger (client_code, delta, bucket, reason) VALUES ('BILC', 5, 'topup', 'adjustment')")
        violates(s, "credit_insufficient",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, note, created_by) VALUES ('BILC', -999, 'topup', 'adjustment', 'x-x', :u)",
                 {"u": team["owner"].id})
        # Append-only: role aplikasi tidak punya hak ubah/hapus.
        violates(s, "permission denied", "UPDATE credit_ledger SET delta = 1 WHERE client_code = 'BILC'")
        violates(s, "permission denied", "DELETE FROM credit_ledger WHERE client_code = 'BILC'")
        violates(s, "permission denied", "DELETE FROM payments WHERE client_code = 'BILB'")
        # Tagihan lunas beku; tagihan baru wajib pending.
        violates(s, "payment_transition", "UPDATE payments SET status = 'failed' WHERE client_code = 'BILB'")
        violates(s, "payment_transition",
                 "INSERT INTO payments (client_code, kind, credits, amount_idr, provider, order_id, status, paid_at, requested_by)"
                 " VALUES ('BILC', 'topup', 250, 50000, 'fake', 'CLAU-BILC-1-abcdef', 'paid', now(), :u)", {"u": team["owner"].id})
        # Langganan hanya dari tagihan paket yang lunas.
        violates(s, "subscription_payment_mismatch",
                 "INSERT INTO subscriptions (client_code, payment_id, plan_months, starts_at, ends_at)"
                 " SELECT 'BILC', id, 1, now(), now() + interval '1 month' FROM payments WHERE client_code = 'BILB' LIMIT 1")


# --- Hangus top up 12 bulan (kontrak core 0.14.0, migrasi 0011) ------------------------------------------------------


def paid_topup(factory, owner_id: int, code: str, credits: int, paid_at: datetime) -> int:
    from app.billing.ledger import apply_paid

    with factory() as s, s.begin():
        p = Payment(client_code=code, kind="topup", credits=credits, amount_idr=cat.TOPUPS[credits], provider="fake",
                    order_id=f"CLAU-{code}-{int(paid_at.timestamp())}-{credits:06d}", requested_by=owner_id)
        s.add(p)
        s.flush()
        apply_paid(s, p, method="simulasi", at=paid_at)
        return p.id


def test_topup_expires_after_twelve_months_and_wallet_shows_next_expiry(factory, team):
    with factory() as s, s.begin():
        s.add(Client(client_code="BILD", vertical="accommodation", business_type="villa", approver_role="owner"))
    approver = Actor(factory, "client_approver", scope="BILD", level="L2")
    t = datetime.now(timezone.utc)
    old = paid_topup(factory, team["owner"].id, "BILD", 250, t - timedelta(days=400))  # sudah lewat 12 bulan
    new = paid_topup(factory, team["owner"].id, "BILD", 550, t - timedelta(days=30))

    w = wallet(approver, "BILD")
    assert w["balance"] == {"monthly": 0, "topup": 550, "trial": 0, "total": 550}
    assert w["topup_next_expiry"]["credits"] == 550
    items = approver.get("/billing/ledger", client_code="BILD").json()["items"]
    assert [(e["reason"], e["delta"], e["payment_id"]) for e in items if e["reason"] == "topup_expire"] == [("topup_expire", -250, old)]
    # Idempoten: dompet dibuka lagi tidak menghanguskan dua kali.
    assert wallet(approver, "BILD")["balance"]["topup"] == 550

    # Pengurangan setelah top up lama hangus memotong top up yang masih berlaku.
    r = team["owner"].post("/billing/adjustments", {"client_code": "BILD", "credits": -100, "note": "koreksi uji"})
    assert r.status_code == 201, r.text
    w = wallet(approver, "BILD")
    assert w["balance"]["topup"] == 450 and w["topup_next_expiry"]["credits"] == 450

    with factory() as s:
        # Database menolak hangus sebelum waktunya dan hangus ganda.
        violates(s, "credit_entry_invalid",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, payment_id) VALUES ('BILD', -10, 'topup', 'topup_expire', :p)",
                 {"p": new})
        violates(s, "uq_credit_ledger_topup_expire",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, payment_id) VALUES ('BILD', -1, 'topup', 'topup_expire', :p)",
                 {"p": old})
        violates(s, "credit_entry_invalid",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, payment_id) VALUES ('BILD', 5, 'topup', 'topup_expire', :p)",
                 {"p": old})


def test_fresh_topup_is_not_expired_early(factory, team, bill):
    # Top up yang baru lunas berlaku penuh: tidak ada yang dihanguskan sebelum 12 bulan.
    from app.billing.ledger import ensure_credits

    paid_topup(factory, team["owner"].id, "BILA", 250, datetime.now(timezone.utc) - timedelta(days=1))
    with factory() as s, s.begin():
        result = ensure_credits(s, "BILA")
        assert balances(s, "BILA")["topup"] == 250
        assert sum(x.remaining for x in result.open_lots) == 250


# --- Kredit percobaan (kontrak core 0.15.0, migrasi 0012) ------------------------------------------------------------


def test_trial_is_used_first_then_expires_and_database_guards_it(factory, team, ai, monkeypatch):
    from sqlalchemy import text

    from app.billing.ledger import ensure_credits, grant_trial

    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    with factory() as s, s.begin():
        s.add(Client(client_code="BILT", vertical="food-beverage", business_type="cafe", approver_role="pemilik", self_serve=True))
    approver = Actor(factory, "client_approver", scope="BILT", level="L3")
    with factory() as s, s.begin():
        assert grant_trial(s, "BILT") is not None
        assert grant_trial(s, "BILT") is None  # sekali per klien
        assert grant_trial(s, "CTHSIM") is None  # klien SIMULASI tidak dapat
    paid_topup(factory, team["owner"].id, "BILT", 250, datetime.now(timezone.utc) - timedelta(days=1))
    assert wallet(approver, "BILT")["balance"] == {"monthly": 0, "topup": 250, "trial": 50, "total": 300}

    # Pemakaian memotong kredit percobaan lebih dulu.
    fact_sheet(factory, client="BILT", keys=("facility.pool-private",), confirmer=approver.id)
    req = new_request(team["staff"], client="BILT")
    r = ask_ai(team["staff"], req["id"])
    assert r.status_code == 202, r.text
    usage = [(e["bucket"], e["delta"]) for e in approver.get("/billing/ledger", client_code="BILT").json()["items"]
             if e["ai_job_id"] == r.json()["id"]]
    assert usage == [("trial", -8)]
    assert wallet(approver, "BILT")["trial"]["credits"] == 42

    with factory() as s:
        # Hibah kedua, hangus sebelum waktunya, penyesuaian ke trial, dan hibah untuk klien SIMULASI ditolak.
        violates(s, "uq_credit_ledger_trial",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, expires_at) VALUES ('BILT', 50, 'trial', 'trial_grant', now() + interval '3 days')")
        violates(s, "credit_entry_invalid", "INSERT INTO credit_ledger (client_code, delta, bucket, reason) VALUES ('BILT', -1, 'trial', 'trial_expire')")
        violates(s, "credit_entry_invalid",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, note, created_by) VALUES ('BILT', 5, 'trial', 'adjustment', 'bonus', :u)",
                 {"u": team["owner"].id})
        violates(s, "credit_entry_invalid",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, expires_at) VALUES ('CTHSIM', 50, 'trial', 'trial_grant', now() + interval '3 days')")
        violates(s, "credit_entry_invalid",
                 "INSERT INTO credit_ledger (client_code, delta, bucket, reason, expires_at) VALUES ('BILC', 50, 'monthly', 'trial_grant', now() + interval '3 days')")

    # Klien lain dengan kredit percobaan yang sudah lewat: sisa hangus otomatis, pemakaian trial ditolak database.
    with factory() as s, s.begin():
        s.add(Client(client_code="BILU", vertical="food-beverage", business_type="cafe", approver_role="pemilik", self_serve=True))
        s.flush()
        s.execute(text("INSERT INTO credit_ledger (client_code, delta, bucket, reason, expires_at)"
                       " VALUES ('BILU', 50, 'trial', 'trial_grant', now() - interval '1 hour')"))
    with factory() as s, s.begin():
        ensure_credits(s, "BILU")
        assert balances(s, "BILU")["trial"] == 0
        ensure_credits(s, "BILU")  # idempoten
    with factory() as s:
        rows = s.execute(select(CreditEntry.reason, CreditEntry.delta).where(CreditEntry.client_code == "BILU")).all()
        assert sorted(tuple(r) for r in rows) == [("trial_expire", -50), ("trial_grant", 50)]
    bilu = Actor(factory, "client_approver", scope="BILU", level="L3")
    assert wallet(bilu, "BILU")["trial"] is None

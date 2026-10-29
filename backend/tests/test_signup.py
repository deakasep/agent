"""Pendaftaran mandiri, verifikasi email, dan reset password (app/auth/signup.py, migrasi 0009), ke PostgreSQL sungguhan.

Menguji: mati secara default; email wajib siap; satu pendaftaran = klien NYATA baru + client_approver L3 (tidak pernah
peran agency); login ditolak sampai email diverifikasi; respons sama untuk email terdaftar (tanpa akun kedua);
token sekali pakai, kedaluwarsa, hanya hash di database; reset password memutus sesi dan tetap menuntut 2FA;
batas per email dan per jam.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

pytest.importorskip("pyotp")
pytest.importorskip("psycopg")

from sqlalchemy import select, update  # noqa: E402

from app import mail  # noqa: E402
from app.auth import crypto  # noqa: E402
from app.auth.deps import now  # noqa: E402
from app.auth.signup import request_throttle  # noqa: E402
from app.db.models import Client, EmailToken, Membership, User, UserSession  # noqa: E402
from tests.test_auth import PASSWORD, client, engine, factory, login, make_user  # noqa: E402,F401

counter = iter(range(10_000))


@pytest.fixture()
def open_signup(factory, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CLAU_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CLAU_MAIL_BACKEND", "memory")
    monkeypatch.setenv("CLAU_PUBLIC_ORIGIN", "https://app.contoh.test")
    mail.outbox.clear()
    request_throttle._fails.clear()
    return factory


def form(**over) -> dict:
    n = next(counter)
    body = {"business_name": f"Kopi Contoh {n}", "display_name": f"Pemilik {n}", "email": f"daftar{n}@contoh.test",
            "password": PASSWORD, "vertical": "food-beverage", "business_type": "cafe", "location_area": "Denpasar",
            "accept_terms": True}
    return {**body, **over}


def link_token(kind: str) -> str:
    body = mail.outbox[-1].body
    m = re.search(rf"https://app\.contoh\.test/{kind}\?token=([A-Za-z0-9_\-]+)", body)
    assert m, body
    return m.group(1)


def test_signup_closed_by_default_and_without_mail(factory, monkeypatch):  # noqa: F811
    monkeypatch.delenv("CLAU_SIGNUP_ENABLED", raising=False)
    r = client().post("/auth/signup", json=form())
    assert r.status_code == 409 and r.json()["error"]["code"] == "signup_disabled"
    monkeypatch.setenv("CLAU_SIGNUP_ENABLED", "1")
    monkeypatch.setenv("CLAU_MAIL_BACKEND", "disabled")
    assert client().post("/auth/signup", json=form()).json()["error"]["code"] == "signup_disabled"
    # file backend tidak pernah dipakai di produksi
    monkeypatch.setenv("CLAU_MAIL_BACKEND", "file")
    monkeypatch.setenv("CLAU_MAIL_DIR", "/tmp/clau-mail-test")
    monkeypatch.setenv("CLAU_ENV", "production")
    assert client().post("/auth/signup", json=form()).json()["error"]["code"] == "signup_disabled"


def test_signup_creates_real_client_and_approver_then_verify(open_signup):
    body = form()
    r = client().post("/auth/signup", json=body)
    assert r.status_code == 202 and r.json() == {"ok": True}, r.text
    with open_signup() as s:
        user = s.scalar(select(User).where(User.email == body["email"]))
        assert user.email_verified_at is None and not user.must_change_password
        ms = list(s.scalars(select(Membership).where(Membership.user_id == user.id)))
        assert [(m.role, m.max_level) for m in ms] == [("client_approver", "L3")]
        c = s.get(Client, ms[0].scope)
        assert c.simulation is False and c.vertical == "food-beverage" and c.client_code.startswith("KOPICO")
        tokens = list(s.scalars(select(EmailToken).where(EmailToken.user_id == user.id)))
        assert len(tokens) == 1 and re.fullmatch(r"[0-9a-f]{64}", tokens[0].token_hash)

    assert mail.outbox[-1].to == body["email"]
    token = link_token("verifikasi-email")
    with open_signup() as s:
        assert s.scalar(select(EmailToken.id).where(EmailToken.token_hash == token)) is None  # token asli tidak disimpan

    c = client()
    r = c.post("/auth/login", json={"email": body["email"], "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"

    r = c.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["next"] == "ready" and r.json()["user"]["memberships"][0]["role"] == "client_approver"
    assert c.get("/auth/me").status_code == 200
    # sekali pakai
    again = client().post("/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"
    assert client().post("/auth/login", json={"email": body["email"], "password": PASSWORD}).status_code == 200


def test_signup_cannot_request_agency_role_or_simulation(open_signup):
    for extra in ({"role": "owner"}, {"memberships": [{"scope": "agency", "role": "owner", "max_level": "L3"}]}, {"simulation": True}):
        assert client().post("/auth/signup", json={**form(), **extra}).status_code == 422
    assert client().post("/auth/signup", json=form(accept_terms=False)).status_code == 422
    r = client().post("/auth/signup", json=form(password="password12345"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"


def test_existing_email_gets_same_response_and_no_second_account(open_signup):
    user = make_user(open_signup, role="client_approver", scope="CTH", level="L2")
    r = client().post("/auth/signup", json=form(email=user.email.upper()))
    assert r.status_code == 202 and r.json() == {"ok": True}
    with open_signup() as s:
        assert len(list(s.scalars(select(User).where(User.email.ilike(user.email))))) == 1
    assert "sudah ada" in mail.outbox[-1].subject and "token=" not in mail.outbox[-1].body


def test_expired_token_and_new_request_invalidate_old(open_signup):
    body = form()
    client().post("/auth/signup", json=body)
    first = link_token("verifikasi-email")
    assert client().post("/auth/verification-email", json={"email": body["email"]}).status_code == 202
    second = link_token("verifikasi-email")
    assert first != second
    assert client().post("/auth/verify-email", json={"token": first}).json()["error"]["code"] == "invalid_token"
    with open_signup() as s, s.begin():
        s.execute(update(EmailToken).where(EmailToken.token_hash == crypto.token_hash(second))
                  .values(created_at=now() - timedelta(days=3), expires_at=now() - timedelta(days=1)))
    assert client().post("/auth/verify-email", json={"token": second}).json()["error"]["code"] == "invalid_token"
    # email tidak terdaftar: respons sama, tidak ada email
    n = len(mail.outbox)
    assert client().post("/auth/verification-email", json={"email": "tidak-ada@contoh.test"}).json() == {"ok": True}
    assert len(mail.outbox) == n


def test_password_reset_revokes_sessions_and_keeps_2fa(open_signup):
    import pyotp

    secret = pyotp.random_base32()
    user = make_user(open_signup, role="client_approver", scope="CTH", level="L2", mfa_secret=secret)
    c = client()
    assert login(c, user, totp_code=pyotp.TOTP(secret).now()).status_code == 200

    assert client().post("/auth/password-reset", json={"email": user.email}).status_code == 202
    token = link_token("reset-password")
    new = "teras-sawah-pagi-2027"
    r = client().post("/auth/password-reset/confirm", json={"token": token, "new_password": "pendek"})
    assert r.status_code == 422
    # token gagal karena password lemah tidak terpakai (transaksi dibatalkan)
    assert client().post("/auth/password-reset/confirm", json={"token": token, "new_password": new}).status_code == 200
    assert client().post("/auth/password-reset/confirm", json={"token": token, "new_password": new + "x"}).json()["error"]["code"] == "invalid_token"
    with open_signup() as s:
        assert all(x.revoked_at is not None for x in s.scalars(select(UserSession).where(UserSession.user_id == user.id)))
    assert c.get("/auth/me").status_code == 401
    assert client().post("/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 401
    r = client().post("/auth/login", json={"email": user.email, "password": new})
    assert r.status_code == 401 and r.json()["error"]["code"] == "mfa_required"

    # email tidak terdaftar: respons sama, tanpa email
    n = len(mail.outbox)
    assert client().post("/auth/password-reset", json={"email": "siapa@contoh.test"}).json() == {"ok": True}
    assert len(mail.outbox) == n


def test_per_email_and_hourly_limits(open_signup, monkeypatch):
    body = form()
    for _ in range(3):
        assert client().post("/auth/password-reset", json={"email": body["email"]}).status_code == 202
    assert client().post("/auth/password-reset", json={"email": body["email"]}).status_code == 429
    monkeypatch.setenv("CLAU_SIGNUP_MAX_PER_HOUR", "0")
    r = client().post("/auth/signup", json=form())
    assert r.status_code == 429 and r.json()["error"]["code"] == "signup_busy"


def test_signup_requires_allowed_origin(open_signup):
    from fastapi.testclient import TestClient

    from app.main import app

    evil = TestClient(app, base_url="https://testserver", headers={"origin": "https://evil.example"})
    assert evil.post("/auth/signup", json=form()).status_code == 403

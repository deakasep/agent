"""Pendaftaran mandiri, verifikasi email, dan reset password (TASK-003; kontrak core api-contracts 0.12.0).

Aturan:
- Dibuka hanya bila CLAU_SIGNUP_ENABLED=1 **dan** backend email siap (mail.py); selain itu 409 `signup_disabled`.
- Satu pendaftaran = satu klien baru + satu user `client_approver` (L3, pemilik usaha) untuk klien itu. Tidak pernah
  memberi peran agency. Klien selalu NYATA (simulation=false). Tanpa kredit gratis (paket dibayar di muka, §4b).
- Respons pendaftaran, kirim ulang verifikasi, dan lupa password selalu sama untuk email terdaftar maupun tidak
  (tidak bisa dipakai menebak email). Email terdaftar mendapat email pemberitahuan, bukan akun kedua.
- Token di tautan email: acak 32 byte, hanya SHA-256 di database, sekali pakai, kedaluwarsa (verifikasi 48 jam,
  reset 1 jam). Permintaan baru membatalkan token lama dengan tujuan yang sama.
- Batas: per email (memori) dan total pendaftaran per jam (database, tidak bisa dielakkan dengan ganti IP).
"""

from __future__ import annotations

import os
import re
import secrets
import string
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, null, select, update
from sqlalchemy.orm import Session

from app import mail
from app.auth import crypto
from app.auth.access import mfa_required
from app.auth.config import AuthSettings
from app.auth.deps import check_origin, get_db, get_settings, now
from app.auth.routes import EMAIL_PATTERN, LoginThrottle, audit, find_user, me_json, memberships_of, revoke_sessions, start_session
from app.db.models import TIMEZONES, VERTICALS, AuditLog, Client, EmailToken, Membership, User
from app.errors import ApiError

router = APIRouter()

VERIFY_HOURS = 48
RESET_MINUTES = 60
request_throttle = LoginThrottle(limit=3, window_seconds=3600)


def signup_enabled() -> bool:
    return os.environ.get("CLAU_SIGNUP_ENABLED") == "1"


def max_per_hour() -> int:
    return int(os.environ.get("CLAU_SIGNUP_MAX_PER_HOUR") or "30")


def app_url() -> str:
    return (os.environ.get("CLAU_PUBLIC_ORIGIN") or "http://localhost:3000").rstrip("/")


def accepted() -> dict:
    return {"ok": True}


def require_mail() -> None:
    if not mail.mail_settings().can_send:
        raise ApiError(409, "signup_disabled", "Pendaftaran belum dibuka. Hubungi tim CLAU.")


def new_token(db: Session, user: User, purpose: str, lifetime: timedelta) -> str:
    t = now()
    db.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose, EmailToken.used_at.is_(None))
               .values(used_at=t))
    token = secrets.token_urlsafe(32)
    db.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=crypto.token_hash(token), created_at=t, expires_at=t + lifetime))
    return token


def take_token(db: Session, token: str, purpose: str) -> EmailToken:
    # Token 256 bit: menebak tidak praktis, jadi tidak perlu throttle (throttle justru bisa dipakai mengunci orang lain).
    row = db.scalar(select(EmailToken).where(EmailToken.token_hash == crypto.token_hash(token), EmailToken.purpose == purpose)
                    .with_for_update())
    if row is None or row.used_at is not None or row.expires_at <= now():
        raise ApiError(400, "invalid_token", "Tautan tidak berlaku atau sudah dipakai. Minta tautan baru.")
    row.used_at = now()
    return row


def deliver(to: str, subject: str, body: str) -> None:
    try:
        mail.send(to, subject, body)
    except mail.MailError:
        # Respons tetap sama; pengguna bisa meminta ulang. Tidak ada isi email di log.
        pass


def verify_mail(user: User, token: str) -> None:
    link = f"{app_url()}/verifikasi-email?token={token}"
    deliver(user.email, "Verifikasi email akun CLAU AI", (
        f"Halo {user.display_name},\n\n"
        "Terima kasih sudah mendaftar di CLAU AI. Klik tautan berikut untuk memverifikasi email Anda "
        f"(berlaku {VERIFY_HOURS} jam):\n\n{link}\n\n"
        "Bila Anda tidak merasa mendaftar, abaikan email ini; akun tidak akan aktif.\n\nTim CLAU AI\n"
    ))


def client_code_for(db: Session, business_name: str) -> str:
    base = re.sub(r"[^A-Z0-9]", "", business_name.upper())[:6] or "UMKM"
    if len(base) < 2:
        base = (base + "XX")[:2]
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = base + "".join(secrets.choice(alphabet) for _ in range(3))
        if db.get(Client, code) is None:
            return code
    raise ApiError(503, "signup_busy", "Coba lagi sebentar.")


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_name: str = Field(min_length=2, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)
    vertical: Literal[VERTICALS]  # type: ignore[valid-type]
    business_type: str = Field(min_length=1, max_length=60)
    location_area: str | None = Field(default=None, max_length=120)
    timezone: str = Field(default="Asia/Makassar", pattern="^(" + "|".join(TIMEZONES).replace("/", "\\/") + ")$")
    accept_terms: Literal[True]


@router.post("/auth/signup", status_code=202)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    check_origin(request, settings)
    if not signup_enabled():
        raise ApiError(409, "signup_disabled", "Pendaftaran belum dibuka. Hubungi tim CLAU.")
    require_mail()
    email = body.email.strip()
    key = "signup:" + email.lower()
    if request_throttle.blocked(key):
        raise ApiError(429, "too_many_attempts", "Terlalu banyak percobaan. Coba lagi dalam 1 jam.")
    if problem := crypto.password_problem(body.password, email):
        raise ApiError(422, "weak_password", problem)
    request_throttle.fail(key)
    recent = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "signup", AuditLog.created_at > now() - timedelta(hours=1)))
    if recent >= max_per_hour():
        raise ApiError(429, "signup_busy", "Pendaftaran sedang ramai. Coba lagi dalam beberapa menit.")

    existing = find_user(db, email)
    # Hash tetap dihitung di kedua jalur agar waktu respons tidak membedakan email terdaftar.
    password_hash = crypto.hash_password(body.password)
    if existing is not None:
        deliver(existing.email, "Akun CLAU AI Anda sudah ada", (
            f"Halo {existing.display_name},\n\nAda permintaan pendaftaran baru dengan email ini, padahal akun Anda sudah ada. "
            f"Masuk di {app_url()}/login atau atur ulang password di {app_url()}/lupa-password.\n\n"
            "Bila bukan Anda, abaikan email ini.\n\nTim CLAU AI\n"
        ))
        return accepted()

    code = client_code_for(db, body.business_name)
    db.add(Client(client_code=code, vertical=body.vertical, business_type=body.business_type.strip(),
                  location_area=(body.location_area or "").strip() or None, approver_role="pemilik", simulation=False))
    user = User(display_name=body.display_name.strip(), email=email, locale="id", timezone=body.timezone,
                password_hash=password_hash, must_change_password=False, email_verified_at=null())
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, scope=code, role="client_approver", max_level="L3"))
    token = new_token(db, user, "verify_email", timedelta(hours=VERIFY_HOURS))
    audit(db, user.id, "signup", "user", user.id, client_code=code, vertical=body.vertical)
    db.commit()
    verify_mail(user, token)
    return accepted()


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")


@router.post("/auth/verify-email")
def verify_email(body: TokenIn, request: Request, response: Response, db: Session = Depends(get_db),
                 settings: AuthSettings = Depends(get_settings)) -> dict:
    """Tautan valid = email terbukti milik pendaftar; sesi langsung dibuat agar bisa lanjut pilih paket."""
    check_origin(request, settings)
    row = take_token(db, body.token, "verify_email")
    user = db.get(User, row.user_id)
    if user is None or user.disabled_at is not None:
        db.rollback()
        raise ApiError(400, "invalid_token", "Tautan tidak berlaku atau sudah dipakai. Minta tautan baru.")
    if user.email_verified_at is None:
        user.email_verified_at = now()
    user.last_login_at = now()
    memberships = memberships_of(db, user.id)
    ctx = start_session(db, response, settings, user, memberships, mfa_ok=user.totp_enabled or not mfa_required(memberships))
    audit(db, user.id, "email_verified", "user", user.id)
    db.commit()
    return me_json(db, ctx, settings)


class EmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=255, pattern=EMAIL_PATTERN)


@router.post("/auth/verification-email", status_code=202)
def request_verification(body: EmailIn, request: Request, db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    """Minta tautan verifikasi baru (email belum diterima / kedaluwarsa)."""
    check_origin(request, settings)
    require_mail()
    key = "verify:" + body.email.strip().lower()
    if request_throttle.blocked(key):
        raise ApiError(429, "too_many_attempts", "Terlalu banyak permintaan. Coba lagi dalam 1 jam.")
    request_throttle.fail(key)
    user = find_user(db, body.email)
    if user is not None and user.disabled_at is None and user.email_verified_at is None:
        token = new_token(db, user, "verify_email", timedelta(hours=VERIFY_HOURS))
        db.commit()
        verify_mail(user, token)
    return accepted()


@router.post("/auth/password-reset", status_code=202)
def request_password_reset(body: EmailIn, request: Request, db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    check_origin(request, settings)
    require_mail()
    key = "reset:" + body.email.strip().lower()
    if request_throttle.blocked(key):
        raise ApiError(429, "too_many_attempts", "Terlalu banyak permintaan. Coba lagi dalam 1 jam.")
    request_throttle.fail(key)
    user = find_user(db, body.email)
    if user is not None and user.disabled_at is None and user.password_hash is not None:
        token = new_token(db, user, "reset_password", timedelta(minutes=RESET_MINUTES))
        audit(db, None, "password_reset_requested", "user", user.id)
        db.commit()
        deliver(user.email, "Atur ulang password CLAU AI", (
            f"Halo {user.display_name},\n\nKlik tautan berikut untuk membuat password baru (berlaku {RESET_MINUTES} menit):\n\n"
            f"{app_url()}/reset-password?token={token}\n\n"
            "Bila Anda tidak meminta ini, abaikan email ini; password lama tetap berlaku.\n\nTim CLAU AI\n"
        ))
    return accepted()


class ResetIn(TokenIn):
    new_password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)


@router.post("/auth/password-reset/confirm")
def confirm_password_reset(body: ResetIn, request: Request, db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    """Password baru + semua sesi diputus. 2FA tetap berlaku (reset tidak melewati authenticator)."""
    check_origin(request, settings)
    row = take_token(db, body.token, "reset_password")
    user = db.get(User, row.user_id)
    if user is None or user.disabled_at is not None:
        db.rollback()
        raise ApiError(400, "invalid_token", "Tautan tidak berlaku atau sudah dipakai. Minta tautan baru.")
    if problem := crypto.password_problem(body.new_password, user.email):
        db.rollback()
        raise ApiError(422, "weak_password", problem)
    user.password_hash, user.must_change_password = crypto.hash_password(body.new_password), False
    user.failed_logins, user.locked_until = 0, None
    if user.email_verified_at is None:
        user.email_verified_at = now()  # tautan di email juga membuktikan kepemilikan email
    revoke_sessions(db, user.id)
    audit(db, user.id, "password_reset", "user", user.id)
    db.commit()
    return accepted()

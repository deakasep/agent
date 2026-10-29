"""Endpoint login, akun, 2FA, dan manajemen user (khusus owner). docs/security.md § 6.

Owner pertama dibuat lewat `python -m app.auth.cli create-owner`; staf dan approver dibuat owner lewat POST /users
dengan password sementara yang wajib diganti saat login pertama. Pendaftaran mandiri klien (hanya peran
client_approver untuk klien baru) ada di app/auth/signup.py dan mati secara default (CLAU_SIGNUP_ENABLED).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import crypto
from app.auth.access import is_owner, mfa_required
from app.auth.config import AuthSettings
from app.auth.deps import AuthContext, check_origin, current_user, current_user_pending_ok, get_db, get_settings, now, require_owner
from app.db.models import LEVELS, LOCALES, ROLES, TIMEZONES, AuditLog, Client, Membership, MfaRecoveryCode, User, UserSession
from app.errors import ApiError

router = APIRouter()

EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,190}$"
# Kunci advisory Postgres untuk perubahan peran/nonaktif: dua owner yang saling menurunkan bersamaan
# tidak bisa sama-sama lolos cek "minimal satu owner aktif".
OWNER_CHANGE_LOCK = 4_242_001


# --- Throttle per email (di memori) --------------------------------------------------------------


class LoginThrottle:
    """Batas gagal per email, juga untuk email yang tidak terdaftar, sehingga respons untuk email terdaftar dan
    tidak terdaftar sama (tidak bisa dipakai menebak email). Penguncian persisten ada di database
    (users.locked_until); batas per IP dipasang di Nginx saat deploy. Jumlah email yang dilacak dibatasi
    (yang paling lama dibuang) agar penyerang tidak bisa menghabiskan memori dengan jutaan email acak."""

    def __init__(self, limit: int = 5, window_seconds: int = 900, max_keys: int = 50_000) -> None:
        self.limit, self.window, self.max_keys = limit, window_seconds, max_keys
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, t: float) -> deque[float] | None:
        q = self._fails.get(key)
        if q is None:
            return None
        while q and t - q[0] > self.window:
            q.popleft()
        if not q:
            del self._fails[key]
            return None
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            q = self._recent(key, time.monotonic())
            return q is not None and len(q) >= self.limit

    def fail(self, key: str) -> None:
        with self._lock:
            t = time.monotonic()
            q = self._recent(key, t)
            if q is None:
                while len(self._fails) >= self.max_keys:
                    del self._fails[next(iter(self._fails))]
                q = self._fails[key] = deque()
            q.append(t)

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


throttle = LoginThrottle()


# --- Error (instance baru setiap raise: instance bersama menahan frame & password di traceback) ----


def invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", "Email atau password salah.")


def too_many_attempts() -> ApiError:
    return ApiError(429, "too_many_attempts", "Terlalu banyak percobaan gagal. Coba lagi dalam 15 menit.")


# --- Helper ---------------------------------------------------------------------------------------


def audit(db: Session, actor_id: int | None, action: str, object_type: str, object_id: object, **meta: object) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, object_type=object_type, object_id=str(object_id), meta=meta))


def memberships_of(db: Session, user_id: int) -> list[Membership]:
    return list(db.scalars(select(Membership).where(Membership.user_id == user_id).order_by(Membership.scope)))


def user_json(user: User, memberships: list[Membership]) -> dict:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "email": user.email,
        "locale": user.locale,
        "timezone": user.timezone,
        "salutation": user.salutation,
        "memberships": [{"scope": m.scope, "role": m.role, "max_level": m.max_level} for m in memberships],
        "mfa_enabled": user.totp_enabled,
        "disabled": user.disabled_at is not None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def me_json(db: Session, ctx: AuthContext, settings: AuthSettings) -> dict:
    t = now()
    active = db.scalar(select(func.count()).select_from(UserSession).where(
        UserSession.user_id == ctx.user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > t))
    codes_left = db.scalar(select(func.count()).select_from(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == ctx.user.id, MfaRecoveryCode.used_at.is_(None)))
    return {
        "user": user_json(ctx.user, ctx.memberships),
        "mfa_required": mfa_required(ctx.memberships),
        "must_change_password": ctx.user.must_change_password,
        "next": ctx.pending or "ready",
        "active_sessions": active,
        "recovery_codes_left": codes_left,
        "csrf_token": crypto.csrf_token(settings.secret_key, ctx.token),
    }


def set_cookie(response: Response, settings: AuthSettings, token: str) -> None:
    response.set_cookie(settings.cookie_name, token, max_age=settings.session_max_hours * 3600, path="/",
                        secure=settings.cookie_secure, httponly=True, samesite="lax")


def clear_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


def start_session(db: Session, response: Response, settings: AuthSettings, user: User, memberships: list[Membership], mfa_ok: bool) -> AuthContext:
    """Selalu token baru (cegah session fixation). Sesi lama user yang sudah habis/dicabut dibersihkan."""
    token = crypto.new_session_token()
    t = now()
    db.execute(delete(UserSession).where(
        UserSession.user_id == user.id,
        or_(UserSession.expires_at < t - timedelta(days=1), UserSession.revoked_at < t - timedelta(days=1)),
    ))
    session = UserSession(token_hash=crypto.token_hash(token), user_id=user.id, mfa_ok=mfa_ok, created_at=t, last_seen_at=t,
                          expires_at=t + timedelta(hours=settings.session_max_hours))
    db.add(session)
    set_cookie(response, settings, token)
    return AuthContext(user=user, session=session, token=token, memberships=memberships)


def revoke_sessions(db: Session, user_id: int) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)).values(revoked_at=now()))


def find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def register_failure(db: Session, settings: AuthSettings, user: User | None, key: str, reason: str) -> None:
    """Hitung gagal (memori + database). Gagal ke-5 mengunci akun 15 menit dan memutus semua sesinya.
    Email tidak terdaftar tidak dicatat di audit_log (append-only) agar tidak bisa dibanjiri penyerang."""
    throttle.fail(key)
    if user is not None:
        count = db.scalar(update(User).where(User.id == user.id).values(failed_logins=User.failed_logins + 1).returning(User.failed_logins))
        if count >= settings.max_failed_logins:
            db.execute(update(User).where(User.id == user.id).values(locked_until=now() + timedelta(minutes=settings.lockout_minutes), failed_logins=0))
            revoke_sessions(db, user.id)
        audit(db, None, "login_failed", "user", user.id, reason=reason)
    db.commit()


def totp_secret(settings: AuthSettings, user: User) -> str:
    try:
        return crypto.decrypt_totp_secret(settings.secret_key, user.id, user.totp_secret_enc)
    except InvalidTag as exc:
        # CLAU_SECRET_KEY berganti setelah 2FA diaktifkan: secret lama tidak bisa dibuka lagi.
        raise ApiError(503, "mfa_key_mismatch", "2FA tidak bisa diverifikasi karena kunci server berubah. Minta admin server menjalankan reset-mfa.") from exc


def consume_totp(db: Session, user: User, counter: int) -> bool:
    """Tandai jendela TOTP terpakai secara atomik: dua request bersamaan dengan kode yang sama, hanya satu lolos."""
    result = db.execute(update(User).where(
        User.id == user.id, or_(User.totp_last_counter.is_(None), User.totp_last_counter < counter)
    ).values(totp_last_counter=counter))
    return result.rowcount == 1


def consume_recovery_code(db: Session, settings: AuthSettings, user: User, code: str) -> bool:
    code_hash = crypto.recovery_hash(settings.secret_key, user.id, code)
    result = db.execute(update(MfaRecoveryCode).where(
        MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.code_hash == code_hash, MfaRecoveryCode.used_at.is_(None)
    ).values(used_at=now()))
    return result.rowcount == 1


def issue_recovery_codes(db: Session, settings: AuthSettings, user: User) -> list[str]:
    """Kode lama (terpakai atau belum) dihapus; 10 kode baru ditampilkan sekali."""
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = crypto.new_recovery_codes()
    db.add_all(MfaRecoveryCode(user_id=user.id, code_hash=crypto.recovery_hash(settings.secret_key, user.id, c)) for c in codes)
    return codes


# --- Login & sesi ---------------------------------------------------------------------------------


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)
    totp_code: str | None = Field(default=None, max_length=10)
    recovery_code: str | None = Field(default=None, max_length=20)


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    check_origin(request, settings)
    key = body.email.strip().lower()
    if throttle.blocked(key):
        raise too_many_attempts()
    user = find_user(db, key)
    t = now()
    active = user is not None and user.disabled_at is None
    # Argon2 selalu dijalankan (hash pembanding bila akun tidak ada/nonaktif): waktu respons tidak
    # membedakan email terdaftar, tidak terdaftar, atau nonaktif.
    password_ok = crypto.verify_password(user.password_hash if active else None, body.password)
    if active and user.locked_until is not None and user.locked_until > t:
        raise too_many_attempts()
    if not (active and password_ok):
        register_failure(db, settings, user, key, "password")
        raise invalid_credentials()
    if user.email_verified_at is None:
        # Daftar mandiri (app/auth/signup.py): password benar tetapi email belum diverifikasi.
        raise ApiError(403, "email_not_verified", "Verifikasi email dulu lewat tautan yang kami kirim.")

    used_recovery = False
    if user.totp_enabled:
        if body.recovery_code:
            if not consume_recovery_code(db, settings, user, body.recovery_code):
                register_failure(db, settings, user, key, "recovery_code")
                raise ApiError(401, "invalid_recovery_code", "Kode cadangan salah atau sudah dipakai.")
            used_recovery = True
        elif body.totp_code:
            counter = crypto.verify_totp(totp_secret(settings, user), body.totp_code, None)
            if counter is None or not consume_totp(db, user, counter):
                db.rollback()
                register_failure(db, settings, user, key, "totp")
                raise ApiError(401, "invalid_mfa_code", "Kode 2FA salah atau sudah dipakai.")
        else:
            raise ApiError(401, "mfa_required", "Masukkan kode 6 digit dari aplikasi authenticator.")

    throttle.reset(key)
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, t
    if crypto.needs_rehash(user.password_hash):
        user.password_hash = crypto.hash_password(body.password)
    memberships = memberships_of(db, user.id)
    ctx = start_session(db, response, settings, user, memberships, mfa_ok=user.totp_enabled or not mfa_required(memberships))
    audit(db, user.id, "login", "user", user.id, mfa=user.totp_enabled, recovery_code=used_recovery)
    db.commit()
    return me_json(db, ctx, settings)


@router.get("/auth/me")
def me(ctx: AuthContext = Depends(current_user_pending_ok), db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    return me_json(db, ctx, settings)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, ctx: AuthContext = Depends(current_user_pending_ok), db: Session = Depends(get_db),
           settings: AuthSettings = Depends(get_settings)) -> Response:
    ctx.session.revoked_at = now()
    audit(db, ctx.user.id, "logout", "user", ctx.user.id)
    db.commit()
    clear_cookie(response, settings)
    response.status_code = 204
    return response


@router.post("/auth/logout-all", status_code=204)
def logout_all(response: Response, ctx: AuthContext = Depends(current_user_pending_ok), db: Session = Depends(get_db),
               settings: AuthSettings = Depends(get_settings)) -> Response:
    """Keluar dari semua perangkat (mis. laptop hilang), termasuk sesi ini."""
    revoke_sessions(db, ctx.user.id)
    audit(db, ctx.user.id, "logout_all", "user", ctx.user.id)
    db.commit()
    clear_cookie(response, settings)
    response.status_code = 204
    return response


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)
    new_password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)


def reauthenticate(db: Session, settings: AuthSettings, ctx: AuthContext, password: str) -> None:
    """Password saat ini wajib benar untuk aksi sensitif. Salah = dihitung gagal login (cookie curian tidak
    bisa dipakai menebak password tanpa batas); gagal ke-5 mengunci akun dan memutus semua sesi."""
    key = ctx.user.email.strip().lower()
    if throttle.blocked(key) or (ctx.user.locked_until is not None and ctx.user.locked_until > now()):
        raise too_many_attempts()
    if not crypto.verify_password(ctx.user.password_hash, password):
        register_failure(db, settings, ctx.user, key, "reauth")
        raise ApiError(400, "invalid_current_password", "Password saat ini salah.")


@router.post("/auth/password")
def change_password(body: PasswordChange, response: Response, ctx: AuthContext = Depends(current_user_pending_ok),
                    db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    user = ctx.user
    reauthenticate(db, settings, ctx, body.current_password)
    if problem := crypto.password_problem(body.new_password, user.email):
        raise ApiError(422, "weak_password", problem)
    if body.new_password == body.current_password:
        raise ApiError(422, "weak_password", "Password baru harus berbeda dari password lama.")
    user.password_hash, user.must_change_password = crypto.hash_password(body.new_password), False
    # Semua sesi lama (termasuk yang mungkin dicuri) diputus; sesi ini diganti token baru.
    revoke_sessions(db, user.id)
    new = start_session(db, response, settings, user, ctx.memberships, mfa_ok=ctx.session.mfa_ok)
    audit(db, user.id, "password_changed", "user", user.id)
    db.commit()
    return me_json(db, new, settings)


# --- 2FA (TOTP) -----------------------------------------------------------------------------------


@router.post("/auth/mfa/setup")
def mfa_setup(ctx: AuthContext = Depends(current_user_pending_ok), db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    if ctx.user.must_change_password:
        raise ApiError(403, "password_change_required", "Ganti password sementara dulu.")
    if ctx.user.totp_enabled:
        raise ApiError(409, "mfa_already_enabled", "2FA sudah aktif. Reset hanya lewat admin server.")
    secret = crypto.new_totp_secret()
    ctx.user.totp_secret_enc = crypto.encrypt_totp_secret(settings.secret_key, ctx.user.id, secret)
    db.commit()
    uri = crypto.totp_uri(secret, ctx.user.email)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": crypto.totp_qr(uri)}


class MfaConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=6, max_length=10)


@router.post("/auth/mfa/confirm")
def mfa_confirm(body: MfaConfirm, response: Response, ctx: AuthContext = Depends(current_user_pending_ok),
                db: Session = Depends(get_db), settings: AuthSettings = Depends(get_settings)) -> dict:
    user = ctx.user
    if user.totp_enabled:
        raise ApiError(409, "mfa_already_enabled", "2FA sudah aktif.")
    if user.totp_secret_enc is None:
        raise ApiError(409, "mfa_setup_missing", "Mulai pengaturan 2FA dulu.")
    counter = crypto.verify_totp(totp_secret(settings, user), body.code, None)
    if counter is None or not consume_totp(db, user, counter):
        db.rollback()
        raise ApiError(400, "invalid_mfa_code", "Kode salah. Pastikan jam HP otomatis, lalu coba kode berikutnya.")
    user.totp_enabled = True
    codes = issue_recovery_codes(db, settings, user)
    revoke_sessions(db, user.id)
    new = start_session(db, response, settings, user, ctx.memberships, mfa_ok=True)
    audit(db, user.id, "mfa_enabled", "user", user.id)
    db.commit()
    return {**me_json(db, new, settings), "recovery_codes": codes}


class Reauth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)


@router.post("/auth/mfa/recovery-codes")
def regenerate_recovery_codes(body: Reauth, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db),
                              settings: AuthSettings = Depends(get_settings)) -> dict:
    """Buat 10 kode cadangan baru (yang lama tidak berlaku). Wajib password saat ini."""
    if not ctx.user.totp_enabled:
        raise ApiError(409, "mfa_not_enabled", "Aktifkan 2FA dulu.")
    reauthenticate(db, settings, ctx, body.password)
    codes = issue_recovery_codes(db, settings, ctx.user)
    audit(db, ctx.user.id, "mfa_recovery_regenerated", "user", ctx.user.id)
    db.commit()
    return {"recovery_codes": codes}


# --- Manajemen user (owner) -----------------------------------------------------------------------


class MembershipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = Field(max_length=12, pattern=r"^(agency|[A-Z0-9]{2,12})$")
    role: str = Field(pattern="^(" + "|".join(ROLES) + ")$")
    max_level: str = Field(pattern="^(" + "|".join(LEVELS) + ")$")


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    temporary_password: str = Field(min_length=1, max_length=crypto.MAX_PASSWORD)
    locale: str = Field(default="id", pattern="^(" + "|".join(LOCALES) + ")$")
    timezone: str = Field(default="Asia/Makassar", pattern="^(" + "|".join(TIMEZONES).replace("/", "\\/") + ")$")
    memberships: list[MembershipIn] = Field(min_length=1, max_length=50)


def save_memberships(db: Session, user_id: int, items: list[MembershipIn]) -> None:
    if len({m.scope for m in items}) != len(items):
        raise ApiError(422, "invalid_membership", "Satu scope hanya boleh satu peran.")
    clients = {m.scope for m in items if m.scope != "agency"}
    if clients and len(db.scalars(select(Client.client_code).where(Client.client_code.in_(clients))).all()) != len(clients):
        raise ApiError(422, "invalid_membership", "Klien tidak dikenal.")
    db.execute(delete(Membership).where(Membership.user_id == user_id))
    db.add_all(Membership(user_id=user_id, scope=m.scope, role=m.role, max_level=m.max_level) for m in items)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(422, "invalid_membership", "Peran tidak cocok dengan scope atau klien tidak dikenal.") from exc


def lock_owner_changes(db: Session) -> None:
    """Serialisasi perubahan yang bisa mengurangi owner aktif (dilepas otomatis saat commit/rollback)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": OWNER_CHANGE_LOCK})


def ensure_active_owner(db: Session) -> None:
    owners = db.scalar(
        select(func.count()).select_from(Membership).join(User, User.id == Membership.user_id)
        .where(Membership.scope == "agency", Membership.role == "owner", User.disabled_at.is_(None))
    )
    if not owners:
        db.rollback()
        raise ApiError(409, "last_owner", "Harus tetap ada minimal satu owner aktif.")


@router.get("/users")
def list_users(ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    users = db.scalars(select(User).order_by(User.id)).all()
    by_user: dict[int, list[Membership]] = {}
    for m in db.scalars(select(Membership).order_by(Membership.scope)):
        by_user.setdefault(m.user_id, []).append(m)
    clients = db.scalars(select(Client.client_code).order_by(Client.client_code)).all()
    return {"users": [user_json(u, by_user.get(u.id, [])) for u in users], "clients": list(clients)}


@router.post("/users", status_code=201)
def create_user(body: UserCreate, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    if problem := crypto.password_problem(body.temporary_password, body.email):
        raise ApiError(422, "weak_password", problem)
    if find_user(db, body.email):
        raise ApiError(409, "email_taken", "Email sudah dipakai akun lain.")
    user = User(display_name=body.display_name.strip(), email=body.email.strip(), locale=body.locale, timezone=body.timezone,
                password_hash=crypto.hash_password(body.temporary_password), must_change_password=True)
    db.add(user)
    db.flush()
    save_memberships(db, user.id, body.memberships)
    audit(db, ctx.user.id, "user_created", "user", user.id, memberships=[m.model_dump() for m in body.memberships])
    db.commit()
    return user_json(user, memberships_of(db, user.id))


def target_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(404, "not_found", "User tidak ada.")
    return user


@router.put("/users/{user_id}/memberships")
def set_memberships(user_id: int, body: list[MembershipIn], ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    lock_owner_changes(db)
    user = target_user(db, user_id)
    if not body:
        raise ApiError(422, "invalid_membership", "Minimal satu peran.")
    save_memberships(db, user.id, body)
    ensure_active_owner(db)
    if user.id != ctx.user.id:
        revoke_sessions(db, user.id)  # hak berubah: user login ulang dengan hak baru
    audit(db, ctx.user.id, "membership_changed", "user", user.id, memberships=[m.model_dump() for m in body])
    db.commit()
    return user_json(user, memberships_of(db, user.id))


@router.post("/users/{user_id}/disable")
def disable_user(user_id: int, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    lock_owner_changes(db)
    user = target_user(db, user_id)
    if user.id == ctx.user.id:
        raise ApiError(409, "cannot_disable_self", "Owner tidak bisa menonaktifkan akunnya sendiri.")
    user.disabled_at = now()
    db.flush()
    ensure_active_owner(db)
    revoke_sessions(db, user.id)
    audit(db, ctx.user.id, "user_disabled", "user", user.id)
    db.commit()
    return user_json(user, memberships_of(db, user.id))


@router.post("/users/{user_id}/enable")
def enable_user(user_id: int, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    user = target_user(db, user_id)
    user.disabled_at, user.failed_logins, user.locked_until = None, 0, None
    audit(db, ctx.user.id, "user_enabled", "user", user.id)
    db.commit()
    return user_json(user, memberships_of(db, user.id))


def owner_exists(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Membership).where(Membership.scope == "agency", Membership.role == "owner")))


def purge_sessions(db: Session, older_than_days: int = 1) -> int:
    """Hapus sesi yang sudah habis/dicabut lebih dari N hari (CLI purge-sessions; login membersihkan per user)."""
    cutoff = now() - timedelta(days=older_than_days)
    result = db.execute(delete(UserSession).where(or_(UserSession.expires_at < cutoff, UserSession.revoked_at < cutoff)))
    return result.rowcount


__all__ = ["router", "throttle", "is_owner", "owner_exists", "purge_sessions"]

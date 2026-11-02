"""Model database CLAU AI sesuai kontrak core/shared/database-schema.md.

Aturan yang wajib (Constraint Wajib di kontrak) ditegakkan di database sendiri, bukan hanya di kode:
CHECK constraint di sini, dan trigger di migrasi 0001 untuk aturan yang melibatkan tabel lain.
Nilai enum diambil dari sumbernya: label evidence & kategori klaim & vertical dari
clau-market/schemas/content-brief.schema.json, priority dari core/orchestrator/priority-engine.md,
level approval dari rule 08. Enum disimpan sebagai text + CHECK (bukan tipe ENUM Postgres) agar
penambahan nilai cukup satu migrasi kecil.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nama constraint/index deterministik: migrasi dan pesan error bisa merujuk nama yang sama.
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

EVIDENCE_LABELS = ("DATA FINAL", "ASSUMPTION", "CLIENT CONFIRMATION", "FIELD VERIFICATION", "RISK", "NEXT ACTION")
CLAIM_CATEGORIES = (
    "facility", "location", "price", "rating", "certification", "halal-dietary", "food-beverage",
    "treatment", "experience", "capacity", "safety", "license", "itinerary", "other",
)
VERTICALS = ("accommodation", "food-beverage", "spa-wellness", "experience", "wedding-event", "travel-tour",
             # UMKM umum (AI-CONSTITUTION v4.0.0 § 2, migrasi 0009): toko/online shop, jasa, lainnya.
             "retail", "services", "other")
EMAIL_TOKEN_PURPOSES = ("verify_email", "reset_password")
PRIORITIES = ("Low", "Normal", "High", "Urgent")
LEVELS = ("L1", "L2", "L3")
MODES = ("NYATA", "SIMULASI")
QA_RESULTS = ("Pass", "Conditional", "Fail", "N/A")
QA_GATES = ("claim-verification", "content-review", "privacy-rights-review", "visual-ai-review", "publication-checklist")
APPROVAL_DECISIONS = ("Approved", "Revise", "Rejected")
ROLES = ("owner", "content_lead", "content_staff", "viewer", "client_approver")
AGENCY_ROLES = ("owner", "content_lead", "content_staff")
LOCALES = ("id", "en")
TIMEZONES = ("Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura")
NOTIFICATION_CHANNELS = ("in_app", "email", "whatsapp")
FACT_DECISIONS = ("confirmed", "corrected")
REQUEST_STATUSES = ("open", "in_progress", "approved", "rejected", "closed")
# Penanda isi konten (migrasi 0007, kontrak core 0.10.0 § Penanda Isi Konten; Rule 08).
CONTENT_FLAGS = ("price_promo", "people", "ota_listing", "negative_review", "paid_ads", "influencer", "religion_culture", "crisis")
FLAG_LEVELS = {f: ("L2" if f in ("price_promo", "people", "ota_listing") else "L3") for f in CONTENT_FLAGS}
FLAG_SOURCES = ("author", "server", "staff", "qa")
# Antrean AI Tahap 2 (migrasi 0006, kontrak core 0.9.0).
AI_JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
AI_JOB_KINDS = ("draft",)
AI_ERROR_CODES = (
    "provider_error", "provider_unavailable", "refused", "invalid_output", "budget_exceeded", "request_closed",
    "fact_sheet_missing", "worker_timeout", "ai_disabled", "cancelled_by_user",
)
# Kategori klaim yang menyatakan fakta tentang bisnis klien: wajib bisa ditelusuri ke fact sheet (migrasi 0004).
FACTUAL_CATEGORIES = tuple(c for c in CLAIM_CATEGORIES if c not in ("experience", "other"))
FACT_KEY_RE = "^[a-z0-9]+([._-][a-z0-9]+)*$"
# Peran yang boleh mencatat jawaban klien (konfirmasi fakta, persetujuan fact sheet); agency wajib bukti tertulis.
ANSWER_ROLES = ("owner", "content_lead", "client_approver")
# Referensi bukti/dokumen: hanya skema aman (tidak bisa menjadi javascript:/data: saat ditampilkan sebagai link).
# Juga tanpa karakter kontrol C1 dan karakter format tak terlihat (zero-width, bidi override) yang bisa memalsukan
# tampilan link bukti. Sama dengan CHECK di migrasi 0005.
INVISIBLE = "\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff"
REF_RE = f"^(https://|mailto:|workspace://)[^\\s\\x00-\\x1f\\x7f-\\x9f{INVISIBLE}]+$"
REF_SQL_RE = f"^(https://|mailto:|workspace://)[^[:space:][:cntrl:]\u0080-\u009f{INVISIBLE}]+$"

CLIENT_CODE_RE = "^[A-Z0-9]{2,12}$"
SLUG_RE = "^[a-z0-9]+(-[a-z0-9]+)*$"


def one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Client(Base):
    __tablename__ = "clients"
    client_code: Mapped[str] = mapped_column(Text, primary_key=True)
    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    business_type: Mapped[str] = mapped_column(Text, nullable=False)
    location_area: Mapped[str | None] = mapped_column(Text)
    approver_role: Mapped[str] = mapped_column(Text, nullable=False)
    # Klien fiktif (pilot SIMULASI): semua draft-nya otomatis mode SIMULASI, tidak pernah bisa Approved.
    simulation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Klien langganan mandiri (migrasi 0010): approver klien = pemilik usaha; persetujuannya = review manusia (§11).
    self_serve: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        CheckConstraint(f"client_code ~ '{CLIENT_CODE_RE}'", name="client_code_format"),
        CheckConstraint(one_of("vertical", VERTICALS), name="vertical"),
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = pk()
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="id")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Asia/Makassar")
    salutation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    # Login (migrasi 0002, app/auth). Password hanya hash Argon2id; null = akun belum/tidak bisa login.
    password_hash: Mapped[str | None] = mapped_column(Text)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Secret TOTP terenkripsi AES-GCM (kunci dari CLAU_SECRET_KEY), terikat ke id user.
    totp_secret_enc: Mapped[bytes | None] = mapped_column(BYTEA)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    totp_last_counter: Mapped[int | None] = mapped_column(BigInteger)  # cegah kode yang sama dipakai ulang
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Migrasi 0009: null = daftar mandiri dan email belum diverifikasi (belum bisa login). Akun dari owner/CLI
    # terisi otomatis (server default) karena dibuat oleh owner.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("password_hash IS NULL OR password_hash LIKE '$argon2id$%'", name="password_argon2id"),
        CheckConstraint("NOT totp_enabled OR totp_secret_enc IS NOT NULL", name="totp_has_secret"),
        CheckConstraint("failed_logins >= 0", name="failed_logins_positive"),
        CheckConstraint("email ~ '^[^@[:space:]]+@[^@[:space:]]+$'", name="email_format"),
        CheckConstraint(one_of("locale", LOCALES), name="locale"),
        CheckConstraint(one_of("timezone", TIMEZONES), name="timezone"),
        # Satu akun per email, tanpa membedakan huruf besar/kecil.
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )


class UserSession(Base):
    """Sesi login di server. Cookie hanya berisi token acak; database menyimpan SHA-256-nya, jadi kebocoran
    database tidak memberi sesi yang bisa dipakai. Token CSRF diturunkan dari token sesi (HMAC), tidak disimpan."""

    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # false = password benar tetapi 2FA wajib belum diaktifkan: hanya endpoint akun yang boleh dipakai.
    mfa_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = created_at()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )


class MfaRecoveryCode(Base):
    """Kode cadangan 2FA sekali pakai (HP hilang). Hanya HMAC-SHA256 kode yang disimpan; kode asli ditampilkan
    sekali saat dibuat. used_at terisi = sudah dipakai."""

    __tablename__ = "mfa_recovery_codes"
    id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("user_id", "code_hash"),
        CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name="code_hash_sha256"),
    )


class EmailToken(Base):
    """Token sekali pakai di tautan email (verifikasi email, reset password). Hanya SHA-256 token yang disimpan;
    token asli hanya ada di email. Migrasi 0009."""

    __tablename__ = "email_tokens"
    id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(one_of("purpose", EMAIL_TOKEN_PURPOSES), name="purpose"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )


class Membership(Base):
    __tablename__ = "memberships"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)  # 'agency' atau client_code
    role: Mapped[str] = mapped_column(Text, nullable=False)
    max_level: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint(f"scope = 'agency' OR scope ~ '{CLIENT_CODE_RE}'", name="scope_format"),
        CheckConstraint(one_of("role", ROLES), name="role"),
        CheckConstraint(one_of("max_level", LEVELS), name="max_level"),
        # Peran agency hanya di scope agency; approver klien hanya di scope klien.
        CheckConstraint(f"NOT ({one_of('role', AGENCY_ROLES)}) OR scope = 'agency'", name="agency_role_scope"),
        CheckConstraint("role <> 'client_approver' OR scope <> 'agency'", name="client_approver_scope"),
    )


class FactSheet(Base):
    """Satu versi fact sheet klien. Disetujui sekali (approved_*), setelah itu beku (migrasi 0005)."""

    __tablename__ = "fact_sheets"
    id: Mapped[int] = pk()
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_ref: Mapped[str] = mapped_column(Text, nullable=False)  # referensi opaque ke workspace client
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by_role: Mapped[str | None] = mapped_column(Text)
    approval_ref: Mapped[str | None] = mapped_column(Text)  # bukti tertulis klien bila dicatat agency
    __table_args__ = (
        UniqueConstraint("client_code", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(f"approved_by_role IS NULL OR {one_of('approved_by_role', ANSWER_ROLES)}", name="approved_by_role"),
        CheckConstraint("approved_by IS NULL OR (approved_at IS NOT NULL AND approved_by_role IS NOT NULL)", name="approval_complete"),
        CheckConstraint(
            f"char_length(document_ref) <= 500 AND (approval_ref IS NULL OR (approval_ref ~ '{REF_SQL_RE}' AND char_length(approval_ref) <= 500))",
            name="refs",
        ),
    )


class Fact(Base):
    """Satu fakta di versi fact sheet (append-only; koreksi = jawaban klien di fact_confirmations)."""

    __tablename__ = "facts"
    id: Mapped[int] = pk()
    fact_sheet_id: Mapped[int] = mapped_column(ForeignKey("fact_sheets.id"), nullable=False)
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        UniqueConstraint("fact_sheet_id", "fact_key"),
        CheckConstraint(one_of("category", FACTUAL_CATEGORIES), name="category"),
        CheckConstraint(
            f"fact_key ~ '{FACT_KEY_RE}' AND char_length(fact_key) <= 64 AND split_part(fact_key, '.', 1) = category AND strpos(fact_key, '.') > 0",
            name="fact_key_format",
        ),
        CheckConstraint("btrim(label) <> '' AND char_length(label) <= 200 AND btrim(value) <> '' AND char_length(value) <= 1000", name="text"),
    )


class FactConfirmation(Base):
    __tablename__ = "fact_confirmations"
    id: Mapped[int] = pk()
    fact_sheet_id: Mapped[int] = mapped_column(ForeignKey("fact_sheets.id"), nullable=False, index=True)
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    value_before: Mapped[str | None] = mapped_column(Text)
    value_after: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    confirmed_by_role: Mapped[str | None] = mapped_column(Text)
    channel_ref: Mapped[str | None] = mapped_column(Text)  # bukti tertulis klien bila dicatat agency
    __table_args__ = (
        CheckConstraint(one_of("decision", FACT_DECISIONS), name="decision"),
        CheckConstraint(f"confirmed_by_role IS NULL OR {one_of('confirmed_by_role', ANSWER_ROLES)}", name="confirmed_by_role"),
        CheckConstraint(f"channel_ref IS NULL OR (channel_ref ~ '{REF_SQL_RE}' AND char_length(channel_ref) <= 500)", name="channel_ref"),
        CheckConstraint("char_length(coalesce(value_before, '')) <= 1000 AND char_length(coalesce(value_after, '')) <= 1000", name="value_length"),
        # Cek facts_unconfirmed (trigger approval) mencari per (fact_sheet_id, fact_key).
        Index("ix_fact_confirmations_sheet_key", "fact_sheet_id", "fact_key"),
    )


class Brief(Base):
    __tablename__ = "briefs"
    brief_id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    __table_args__ = (
        # Format dari content-brief.schema.json: <CLIENTCODE>-<YYYYMM>-<NN>, dan prefiks = client_code.
        CheckConstraint("brief_id ~ '^[A-Z0-9]{2,12}-[0-9]{6}-[0-9]{2}$'", name="brief_id_format"),
        CheckConstraint("split_part(brief_id, '-', 1) = client_code", name="brief_id_client"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
    )


class Request(Base):
    __tablename__ = "requests"
    id: Mapped[int] = pk()
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    pillar: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Level approval minimum intent ini (router/registry); approval di bawahnya ditolak trigger (migrasi 0004).
    approval_min: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date)
    impact: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    risk: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="Normal")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # null = sistem/seed
    requested_by_role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at()
    # Migrasi 0007: rating review (wajib untuk review-reply) dan draft asal (wajib untuk localize, klien sama).
    review_rating: Mapped[int | None] = mapped_column(SmallInteger)
    source_draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id", use_alter=True), index=True)
    __table_args__ = (
        CheckConstraint(f"intent ~ '{SLUG_RE}'", name="intent_format"),
        CheckConstraint("review_rating IS NULL OR review_rating BETWEEN 1 AND 5", name="review_rating_range"),
        CheckConstraint("pillar BETWEEN 1 AND 5", name="pillar_range"),
        CheckConstraint(one_of("priority", PRIORITIES), name="priority"),
        CheckConstraint(one_of("approval_min", LEVELS), name="approval_min"),
        CheckConstraint(one_of("status", REQUEST_STATUSES), name="status"),
        CheckConstraint("impact BETWEEN 0 AND 3 AND risk BETWEEN 0 AND 3", name="impact_risk_range"),
        CheckConstraint("char_length(text) <= 4000", name="text_length"),
        Index("ix_requests_created_at", "created_at"),
    )


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = pk()
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False, index=True)
    brief_id: Mapped[str | None] = mapped_column(ForeignKey("briefs.brief_id"), index=True)
    fact_sheet_id: Mapped[int | None] = mapped_column(ForeignKey("fact_sheets.id"), index=True)
    skill: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # null = dibuat agent
    agent_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        UniqueConstraint("request_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(one_of("mode", MODES), name="mode"),
        CheckConstraint("created_by IS NOT NULL OR agent_id IS NOT NULL", name="has_author"),
        CheckConstraint(f"agent_id IS NULL OR agent_id ~ '{SLUG_RE}'", name="agent_id_format"),
    )


class DraftFlag(Base):
    """Penanda isi konten draft (migrasi 0007). Hanya removed_* yang boleh diisi, sekali (trigger)."""

    __tablename__ = "draft_flags"
    id: Mapped[int] = pk()
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False, index=True)
    flag: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # null = server / agent
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    removed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(one_of("flag", CONTENT_FLAGS), name="flag"),
        CheckConstraint(one_of("source", FLAG_SOURCES), name="source"),
        CheckConstraint(
            "(removed_at IS NULL AND removed_by IS NULL AND removed_reason IS NULL)"
            " OR (removed_at IS NOT NULL AND removed_by IS NOT NULL AND char_length(removed_reason) BETWEEN 10 AND 500)",
            name="removed_fields"),
        CheckConstraint("source IN ('server', 'author') OR added_by IS NOT NULL", name="added_by"),
        Index("uq_draft_flags_active", "draft_id", "flag", unique=True, postgresql_where=text("removed_at IS NULL")),
    )


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = pk()
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_label: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    source_date: Mapped[date | None] = mapped_column(Date)
    implied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fact_key: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(f"fact_key IS NULL OR (fact_key ~ '{FACT_KEY_RE}' AND char_length(fact_key) <= 64)", name="fact_key_format"),
        # Fakta tentang bisnis klien harus bisa ditelusuri ke fact sheet (facts_unconfirmed di trigger approval), dan
        # kuncinya berawalan kategori klaim (price.*, facility.*): konfirmasi fakta lain tidak bisa "dipinjam".
        CheckConstraint(
            f"NOT ({one_of('category', FACTUAL_CATEGORIES)}) OR (fact_key IS NOT NULL AND split_part(fact_key, '.', 1) = category)",
            name="fact_key_required",
        ),
        CheckConstraint(one_of("category", CLAIM_CATEGORIES), name="category"),
        CheckConstraint(one_of("evidence_label", EVIDENCE_LABELS), name="evidence_label"),
        # Constraint Wajib: DATA FINAL wajib punya sumber dan tanggal sumber.
        CheckConstraint(
            "evidence_label <> 'DATA FINAL' OR (coalesce(btrim(source), '') <> '' AND source_date IS NOT NULL)",
            name="data_final_sourced",
        ),
    )


class QARecord(Base):
    __tablename__ = "qa_records"
    id: Mapped[int] = pk()
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False, index=True)
    gate: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # null = agent
    reviewer_role: Mapped[str] = mapped_column(Text, nullable=False)
    independent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        CheckConstraint(one_of("gate", QA_GATES), name="gate"),
        CheckConstraint(one_of("result", QA_RESULTS), name="result"),
        # Constraint Wajib: review oleh agent (reviewer_id null) tidak pernah independen.
        # Reviewer ≠ pembuat draft dicek trigger (butuh tabel drafts).
        CheckConstraint("NOT independent OR reviewer_id IS NOT NULL", name="independent_is_human"),
    )


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = pk()
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False, index=True)  # versi yang disetujui
    level: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    approver_role: Mapped[str] = mapped_column(Text, nullable=False)
    channel_ref: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint(one_of("level", LEVELS), name="level"),
        CheckConstraint(one_of("decision", APPROVAL_DECISIONS), name="decision"),
        CheckConstraint(one_of("mode", MODES), name="mode"),
        # Constraint Wajib: mode SIMULASI tidak pernah Approved.
        CheckConstraint("NOT (decision = 'Approved' AND mode = 'SIMULASI')", name="simulasi_not_approved"),
    )


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[int] = pk()
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url_ref: Mapped[str | None] = mapped_column(Text)
    published_by_role: Mapped[str] = mapped_column(Text, nullable=False)


class ConsentRef(Base):
    __tablename__ = "consent_refs"
    id: Mapped[int] = pk()
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    consent_ref: Mapped[str] = mapped_column(Text, nullable=False)  # opaque, tanpa nama/foto
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    object_ref: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint(one_of("channel", NOTIFICATION_CHANNELS), name="channel"),)


class AuditLog(Base):
    """Append-only: UPDATE/DELETE/TRUNCATE ditolak trigger, dan role aplikasi tidak punya hak itu."""

    __tablename__ = "audit_log"
    id: Mapped[int] = pk()
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # null = system/agent
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (Index("ix_audit_log_object", "object_type", "object_id"),)


class AiJob(Base):
    """Antrean kerja AI (Tahap 2). Worker mengambil job `queued` dengan FOR UPDATE SKIP LOCKED; transisi status,
    beku setelah selesai, dan draft hasil yang cocok ditegakkan trigger (migrasi 0006). Tanpa isi prompt."""

    __tablename__ = "ai_jobs"
    id: Mapped[int] = pk()
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    fact_sheet_id: Mapped[int | None] = mapped_column(ForeignKey("fact_sheets.id"))
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), unique=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(one_of("status", AI_JOB_STATUSES), name="status"),
        CheckConstraint(one_of("kind", AI_JOB_KINDS), name="kind"),
        CheckConstraint(f"error_code IS NULL OR {one_of('error_code', AI_ERROR_CODES)}", name="error_code"),
        CheckConstraint(f"agent_id ~ '{SLUG_RE}' AND intent ~ '{SLUG_RE}'", name="ids_format"),
        CheckConstraint("max_attempts BETWEEN 1 AND 5 AND attempts BETWEEN 0 AND max_attempts", name="attempts_range"),
        CheckConstraint("locked_by IS NULL OR char_length(locked_by) <= 100", name="locked_by_length"),
        # Status menentukan kolom hasil: hanya succeeded yang punya draft; failed wajib kode error; selesai = finished_at.
        CheckConstraint(
            "(status IN ('queued', 'running') AND finished_at IS NULL AND draft_id IS NULL AND error_code IS NULL)"
            " OR (status = 'succeeded' AND finished_at IS NOT NULL AND draft_id IS NOT NULL AND error_code IS NULL)"
            " OR (status = 'failed' AND finished_at IS NOT NULL AND draft_id IS NULL AND error_code IS NOT NULL)"
            " OR (status = 'cancelled' AND finished_at IS NOT NULL AND draft_id IS NULL)",
            name="status_fields",
        ),
        # Satu job aktif per request (ai_job_active); antrean diambil dari job queued yang sudah waktunya.
        Index("uq_ai_jobs_one_active", "request_id", unique=True, postgresql_where=text("status IN ('queued', 'running')")),
        Index("ix_ai_jobs_queue", "run_after", postgresql_where=text("status = 'queued'")),
    )


class AiCall(Base):
    """Satu panggilan model AI (AI-BOUNDARY § Data ke Provider AI). Append-only; tanpa isi prompt/jawaban."""

    __tablename__ = "ai_calls"
    id: Mapped[int] = pk()
    job_id: Mapped[int] = mapped_column(ForeignKey("ai_jobs.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    stop_reason: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0 AND cache_write_tokens >= 0"
            " AND cost_micro_usd >= 0 AND latency_ms >= 0",
            name="non_negative",
        ),
        CheckConstraint(
            "char_length(provider) BETWEEN 1 AND 50 AND char_length(model) BETWEEN 1 AND 100"
            " AND char_length(prompt_version) BETWEEN 1 AND 64 AND char_length(coalesce(stop_reason, '')) <= 50"
            " AND char_length(coalesce(provider_request_id, '')) <= 200",
            name="text_length",
        ),
        Index("ix_ai_calls_created_at", "created_at"),
    )


class AiBudget(Base):
    """Batas biaya AI per bulan: `global` atau per client_code. Tanpa batas global bulan berjalan = AI ditolak."""

    __tablename__ = "ai_budgets"
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)
    limit_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alert_at_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="80")
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        CheckConstraint(f"scope = 'global' OR scope ~ '{CLIENT_CODE_RE}'", name="scope"),
        CheckConstraint("month = date_trunc('month', month)::date", name="month_first_day"),
        CheckConstraint("limit_micro_usd > 0 AND limit_micro_usd <= 100000000000", name="limit_range"),
        CheckConstraint("alert_at_pct BETWEEN 1 AND 100", name="alert_range"),
    )


# --- Langganan & kredit (migrasi 0008, kontrak core 0.11.0, AI-CONSTITUTION v4.0.0 §4b) -------------------------
PAYMENT_KINDS = ("subscription", "topup")
PAYMENT_STATUSES = ("pending", "paid", "expired", "failed")
PAYMENT_PROVIDERS = ("fake", "midtrans")
PLAN_MONTHS = (1, 3, 6, 12)
CREDIT_BUCKETS = ("monthly", "topup", "trial")
CREDIT_REASONS = ("monthly_grant", "monthly_expire", "topup", "topup_expire", "trial_grant", "trial_expire", "usage", "refund", "adjustment")


class Payment(Base):
    """Tagihan paket / top up. Nominal dari katalog server; status lunas hanya dari webhook terverifikasi atau simulasi
    provider `fake`. Transisi & kolom identitas dijaga trigger (migrasi 0008). Tanpa data kartu/rekening."""

    __tablename__ = "payments"
    id: Mapped[int] = pk()
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    plan_months: Mapped[int | None] = mapped_column(SmallInteger)
    credits: Mapped[int | None] = mapped_column(Integer)
    amount_idr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    method: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = created_at()
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(one_of("kind", PAYMENT_KINDS), name="kind"),
        CheckConstraint(one_of("status", PAYMENT_STATUSES), name="status"),
        CheckConstraint(one_of("provider", PAYMENT_PROVIDERS), name="provider"),
        CheckConstraint(
            "(kind = 'subscription' AND plan_months IN (1, 3, 6, 12) AND credits IS NULL)"
            " OR (kind = 'topup' AND plan_months IS NULL AND credits BETWEEN 1 AND 1000000)",
            name="kind_fields",
        ),
        CheckConstraint("amount_idr BETWEEN 1000 AND 1000000000", name="amount_range"),
        CheckConstraint("(status = 'paid') = (paid_at IS NOT NULL)", name="paid_at"),
        CheckConstraint("order_id ~ '^CLAU-[A-Z0-9]{2,12}-[0-9]+-[a-z0-9]{6,16}$'", name="order_id_format"),
        CheckConstraint("method IS NULL OR char_length(method) <= 40", name="method_length"),
    )


class Subscription(Base):
    """Paket yang sudah lunas (satu per pembayaran). Append-only; perpanjangan dimulai saat paket sebelumnya habis."""

    __tablename__ = "subscriptions"
    id: Mapped[int] = pk()
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False, unique=True)
    plan_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        CheckConstraint("plan_months IN (1, 3, 6, 12)", name="plan_months"),
        CheckConstraint("ends_at > starts_at", name="period"),
    )


class CreditEntry(Base):
    """Buku kredit append-only. Saldo = jumlah delta per bucket; aturan per reason, saldo tidak negatif, dan tidak ada
    hibah/refund ganda ditegakkan trigger + indeks unik (migrasi 0008). Top up hangus 12 bulan setelah lunas (`topup_expire`, 0011).
    Kredit percobaan sekali per klien di bucket `trial` (`trial_grant` / `trial_expire`, 0012)."""

    __tablename__ = "credit_ledger"
    id: Mapped[int] = pk()
    client_code: Mapped[str] = mapped_column(ForeignKey("clients.client_code"), nullable=False, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"))
    period_start: Mapped[date | None] = mapped_column(Date)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    ai_job_id: Mapped[int | None] = mapped_column(ForeignKey("ai_jobs.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
    __table_args__ = (
        CheckConstraint(one_of("bucket", CREDIT_BUCKETS), name="bucket"),
        CheckConstraint(one_of("reason", CREDIT_REASONS), name="reason"),
        CheckConstraint("delta <> 0 AND delta BETWEEN -1000000 AND 1000000", name="delta_range"),
        CheckConstraint("note IS NULL OR char_length(note) BETWEEN 3 AND 300", name="note_length"),
        Index("uq_credit_ledger_monthly", "subscription_id", "period_start", "reason", unique=True,
              postgresql_where=text("reason IN ('monthly_grant', 'monthly_expire')")),
        Index("uq_credit_ledger_topup", "payment_id", unique=True, postgresql_where=text("reason = 'topup'")),
        Index("uq_credit_ledger_topup_expire", "payment_id", unique=True, postgresql_where=text("reason = 'topup_expire'")),
        Index("uq_credit_ledger_trial", "client_code", unique=True, postgresql_where=text("reason = 'trial_grant'")),
        Index("uq_credit_ledger_job", "ai_job_id", "bucket", "reason", unique=True, postgresql_where=text("ai_job_id IS NOT NULL")),
        Index("ix_credit_ledger_created_at", "created_at"),
    )

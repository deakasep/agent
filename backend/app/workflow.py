"""Workflow request → draft → QA → approval (Tahap 1 PR 3, kontrak core/shared/api-contracts.md 0.7.0; penanda isi
konten & level approval otomatis 0.10.0, TASK-032).

Pembagian tugas pengamanan:
- Database (migrasi 0001 & 0004) menegakkan aturan data: fakta dikonfirmasi, versi terbaru, level minimum,
  bukan self-approve, bukti tertulis L2/L3 dari agency, mode SIMULASI, catatan keputusan append-only.
- Modul ini menegakkan siapa boleh melakukan apa (matriks izin Rule 08) dan isolasi data per klien.
  Peran, id user, mode, versi, pilar, dan prioritas tidak pernah diambil dari body request.

Tidak ada endpoint publish atau kirim ke pihak luar (core/AI-CONSTITUTION.md §4).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.access import AGENCY, LEVEL_ORDER, can_access_client, visible_client_codes
from app.auth.deps import AuthContext, current_user, get_db
from app.db.models import (
    APPROVAL_DECISIONS,
    CLAIM_CATEGORIES,
    CONTENT_FLAGS,
    EVIDENCE_LABELS,
    FACT_KEY_RE,
    FACTUAL_CATEGORIES,
    LEVELS,
    Membership,
    QA_GATES,
    QA_RESULTS,
    REF_RE,
    REQUEST_STATUSES,
    Approval,
    AuditLog,
    Brief,
    Claim,
    Client,
    Draft,
    DraftFlag,
    FactSheet,
    QARecord,
    Request,
)
from app.errors import ApiError
from app.registry import agent_for_intent

router = APIRouter()

# Matriks izin (api-contracts.md § Matriks Izin Workflow, rule 08).
AGENCY_WRITERS = {"owner", "content_lead", "content_staff"}
SENIOR = {"owner", "content_lead"}  # QA independen & approval oleh agency
WITA = timezone(timedelta(hours=8))  # tanggal kerja tim (Bali); dipakai untuk urgensi priority engine

Level = Literal["L1", "L2", "L3"]
assert tuple(Level.__args__) == LEVELS


# --- Body ----------------------------------------------------------------------------------------


class Body(BaseModel):
    """Field lain ditolak; spasi di tepi dibuang (isi kosong = tidak valid); byte NUL ditolak (Postgres tidak menerimanya)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def no_nul(cls, data: object) -> object:
        def walk(v: object) -> None:
            if isinstance(v, str) and "\x00" in v:
                raise ValueError("teks tidak boleh memuat karakter NUL")
            if isinstance(v, dict):
                for item in v.values():
                    walk(item)
            elif isinstance(v, list):
                for item in v:
                    walk(item)

        walk(data)
        return data


class RequestIn(Body):
    client_code: str = Field(pattern=r"^[A-Z0-9]{2,12}$")
    intent: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    text: str = Field(min_length=1, max_length=4000)
    deadline: date | None = None
    impact: int = Field(default=1, ge=0, le=3)
    risk: int = Field(default=1, ge=0, le=3)
    # 0.10.0: rating review (wajib untuk review-reply; ≤ 3 = L3) dan draft asal (wajib untuk localize).
    review_rating: int | None = Field(default=None, ge=1, le=5)
    source_draft_id: int | None = Field(default=None, ge=1)


Flag = Literal[CONTENT_FLAGS]  # type: ignore[valid-type]


class ClaimIn(Body):
    text: str = Field(min_length=1, max_length=300)
    category: Literal[CLAIM_CATEGORIES]  # type: ignore[valid-type]
    evidence_label: Literal[EVIDENCE_LABELS]  # type: ignore[valid-type]
    source: str | None = Field(default=None, max_length=300)
    source_date: date | None = None
    implied: bool = False
    fact_key: str | None = Field(default=None, max_length=64, pattern=FACT_KEY_RE)


class DraftIn(Body):
    request_id: int = Field(ge=1)
    brief_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2,12}-[0-9]{6}-[0-9]{2}$")
    fact_sheet_id: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=1, max_length=10_000)
    claims: list[ClaimIn] = Field(default_factory=list, max_length=30)
    # 0.10.0: wajib dikirim (daftar kosong = pembuat menyatakan tidak ada penanda); None = field tidak dikirim.
    content_flags: list[Flag] | None = Field(default=None, max_length=len(CONTENT_FLAGS))


class FlagIn(Body):
    flag: Flag


class FlagRemoveIn(Body):
    reason: str = Field(min_length=10, max_length=500)


class QAIn(Body):
    draft_id: int = Field(ge=1)
    gate: Literal[QA_GATES]  # type: ignore[valid-type]
    result: Literal[QA_RESULTS]  # type: ignore[valid-type]
    independent: bool


class ApprovalIn(Body):
    draft_id: int = Field(ge=1)
    level: Level
    decision: Literal[APPROVAL_DECISIONS]  # type: ignore[valid-type]
    # Referensi bukti tertulis klien (link email/pesan arsip), bukan isi pesannya. Hanya skema aman: tidak bisa
    # menjadi javascript:/data: bila nanti ditampilkan sebagai link.
    channel_ref: str | None = Field(default=None, max_length=500, pattern=REF_RE)


class Page(BaseModel):
    limit: int
    offset: int


def page(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=10_000)) -> Page:
    return Page(limit=limit, offset=offset)


# --- Akses ---------------------------------------------------------------------------------------


def membership_for(ctx: AuthContext, client_code: str) -> Membership | None:
    """Membership yang berlaku untuk klien ini: agency (semua klien) diutamakan, lalu scope klien itu. Peran dan
    batas level selalu diambil dari membership yang SAMA."""
    return next((m for m in ctx.memberships if m.scope == AGENCY), None) or next((m for m in ctx.memberships if m.scope == client_code), None)


def role_for(ctx: AuthContext, client_code: str) -> str | None:
    m = membership_for(ctx, client_code)
    return m.role if m else None


def is_self_serve_owner(db: Session, ctx: AuthContext, client_code: str) -> bool:
    """Pemilik usaha langganan mandiri (migrasi 0010): `client_approver` klien `self_serve` itu. Boleh meminta draft
    AI, mengisi Brain bisnis sendiri, dan menyetujui hasil agen (AI-CONSTITUTION v4.0.0 §11)."""
    if role_for(ctx, client_code) != "client_approver":
        return False
    client = db.get(Client, client_code)
    return bool(client and client.self_serve)


def forbidden(message: str = "Peranmu tidak boleh melakukan ini.") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found() -> ApiError:
    # Data klien lain dijawab sama dengan data yang tidak ada: keberadaan objek tidak dibocorkan.
    return ApiError(404, "not_found", "Data tidak ditemukan.")


def check_list_scope(ctx: AuthContext, client_code: str | None) -> set[str] | None:
    """Klien yang boleh dibaca di list; client_code di luar akses = 403 (yang diminta jelas)."""
    visible = visible_client_codes(ctx.memberships)
    if client_code is not None and visible is not None and client_code not in visible:
        raise forbidden("Kamu tidak punya akses ke klien ini.")
    return visible


def visible_request(db: Session, ctx: AuthContext, request_id: int, lock: bool = False) -> Request:
    stmt = select(Request).where(Request.id == request_id)
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if row is None or not can_access_client(ctx.memberships, row.client_code):
        raise not_found()
    return row


def visible_draft(db: Session, ctx: AuthContext, draft_id: int) -> tuple[Draft, Request]:
    row = db.execute(select(Draft, Request).join(Request, Request.id == Draft.request_id).where(Draft.id == draft_id)).first()
    if row is None or not can_access_client(ctx.memberships, row[1].client_code):
        raise not_found()
    return row[0], row[1]


def audit(db: Session, ctx: AuthContext, action: str, object_type: str, object_id: int | str, **meta: object) -> None:
    # Tanpa isi konten/klaim (bisa memuat data klien): cukup id dan keputusan.
    db.add(AuditLog(actor_id=ctx.user.id, action=action, object_type=object_type, object_id=str(object_id), meta=meta))


# --- Priority engine (core/orchestrator/priority-engine.md) ---------------------------------------


def urgency(deadline: date | None, today: date) -> int:
    if deadline is None:
        return 0
    days = (deadline - today).days
    return 3 if days < 2 else 2 if days <= 7 else 1 if days <= 14 else 0


def priority_of(score: int, risk: int) -> str:
    if score >= 8 or risk == 3:
        return "Urgent"
    return "High" if score >= 6 else "Normal" if score >= 3 else "Low"


def priority_score(req: Request) -> int:
    return urgency(req.deadline, req.created_at.astimezone(WITA).date()) + req.impact + req.risk


# --- JSON ----------------------------------------------------------------------------------------


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def request_json(r: Request) -> dict:
    agent = agent_for_intent(r.intent)
    return {
        "id": r.id, "client_code": r.client_code, "intent": r.intent, "pillar": r.pillar,
        "agent": agent["id"] if agent else None, "approval_min": r.approval_min, "text": r.text,
        "deadline": iso(r.deadline), "impact": r.impact, "risk": r.risk, "priority": r.priority,
        "priority_score": priority_score(r), "status": r.status, "requested_by": r.requested_by,
        "requested_by_role": r.requested_by_role, "created_at": iso(r.created_at),
        "review_rating": r.review_rating, "source_draft_id": r.source_draft_id,
    }


def draft_json(d: Draft, client_code: str, latest: bool, claims: list[Claim] | None = None) -> dict:
    out = {
        "id": d.id, "request_id": d.request_id, "client_code": client_code, "brief_id": d.brief_id,
        "fact_sheet_id": d.fact_sheet_id, "skill": d.skill, "version": d.version, "mode": d.mode,
        "created_by": d.created_by, "agent_id": d.agent_id, "created_at": iso(d.created_at), "latest": latest,
    }
    if claims is not None:
        out["content"] = d.content
        out["claims"] = [
            {"id": c.id, "text": c.text, "category": c.category, "evidence_label": c.evidence_label, "source": c.source,
             "source_date": iso(c.source_date), "implied": c.implied, "fact_key": c.fact_key}
            for c in claims
        ]
    return out


def flag_json(f: DraftFlag) -> dict:
    return {"flag": f.flag, "source": f.source, "added_by": f.added_by, "added_at": iso(f.added_at),
            "removed_by": f.removed_by, "removed_at": iso(f.removed_at), "removed_reason": f.removed_reason}


def active_flags(db: Session, draft_id: int) -> list[DraftFlag]:
    return list(db.scalars(select(DraftFlag).where(DraftFlag.draft_id == draft_id, DraftFlag.removed_at.is_(None)).order_by(DraftFlag.id)))


def level_reasons(db: Session, draft_id: int) -> list[dict]:
    """Alasan level minimum dari fungsi database yang sama dengan trigger approval (satu sumber kebenaran)."""
    rows = db.execute(text(
        "SELECT x.rule, x.level FROM drafts d JOIN requests r ON r.id = d.request_id,"
        " LATERAL clau_draft_level_reasons(d, r) AS x WHERE d.id = :id"), {"id": draft_id}).all()
    return [{"rule": rule, "level": level} for rule, level in rows]


def with_levels(db: Session, out: dict, draft_id: int) -> dict:
    reasons = level_reasons(db, draft_id)
    out["content_flags"] = [flag_json(f) for f in active_flags(db, draft_id)]
    out["min_level"] = max((x["level"] for x in reasons), key=LEVEL_ORDER.__getitem__)
    out["min_level_reasons"] = [x for x in reasons if LEVEL_ORDER[x["level"]] > 1]
    return out


def qa_json(q: QARecord) -> dict:
    return {"id": q.id, "draft_id": q.draft_id, "gate": q.gate, "result": q.result, "reviewer_id": q.reviewer_id,
            "reviewer_role": q.reviewer_role, "independent": q.independent, "created_at": iso(q.created_at)}


def approval_json(a: Approval) -> dict:
    return {"id": a.id, "draft_id": a.draft_id, "level": a.level, "decision": a.decision, "approver_id": a.approver_id,
            "approver_role": a.approver_role, "channel_ref": a.channel_ref, "mode": a.mode, "decided_at": iso(a.decided_at)}


def latest_version(db: Session, request_id: int) -> int:
    return db.scalar(select(func.max(Draft.version)).where(Draft.request_id == request_id)) or 0


def paged(db: Session, stmt, p: Page) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return list(db.execute(stmt.limit(p.limit).offset(p.offset)).all()), total


# --- Requests ------------------------------------------------------------------------------------


@router.post("/requests", status_code=201)
def create_request(body: RequestIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    role = role_for(ctx, body.client_code)
    if role not in AGENCY_WRITERS and role != "client_approver":
        raise forbidden("Peranmu tidak boleh membuat request untuk klien ini.")
    if db.get(Client, body.client_code) is None:
        raise ApiError(404, "client_not_found", "Klien tidak dikenal.")
    agent = agent_for_intent(body.intent)
    if agent is None:
        raise ApiError(422, "unknown_intent", f"Intent '{body.intent}' tidak dikenal (core/orchestrator/router.md).")
    if body.intent == "review-reply" and body.review_rating is None:
        raise ApiError(422, "review_rating_required", "Request balasan review wajib rating review 1–5.")
    if body.intent == "localize" and body.source_draft_id is None:
        raise ApiError(422, "source_draft_required", "Request terjemahan wajib menunjuk draft asal.")
    if body.source_draft_id is not None:
        source = db.execute(select(Request.client_code).join(Draft, Draft.request_id == Request.id).where(Draft.id == body.source_draft_id)).scalar()
        if source != body.client_code:  # klien lain dijawab sama dengan yang tidak ada (trigger juga menolak)
            raise ApiError(409, "source_draft_invalid", "Draft asal tidak ditemukan untuk klien ini.")
    # Risiko 3 (legal, privacy, keselamatan, krisis, review negatif) = L3 (rule 08), apa pun minimum intent-nya.
    approval_min = "L3" if body.risk == 3 else agent["approval_min"]
    req = Request(
        client_code=body.client_code, intent=body.intent, pillar=agent["pillar"], approval_min=approval_min,
        text=body.text, deadline=body.deadline, impact=body.impact, risk=body.risk,
        priority=priority_of(urgency(body.deadline, datetime.now(WITA).date()) + body.impact + body.risk, body.risk),
        status="open", requested_by=ctx.user.id, requested_by_role=role,
        review_rating=body.review_rating, source_draft_id=body.source_draft_id,
    )
    db.add(req)
    db.flush()
    audit(db, ctx, "request.create", "request", req.id, client_code=req.client_code, intent=req.intent, priority=req.priority)
    db.commit()
    return request_json(req)


@router.get("/requests")
def list_requests(
    client_code: str | None = Query(None, pattern=r"^[A-Z0-9]{2,12}$"),
    status: Literal[REQUEST_STATUSES] | None = None,  # type: ignore[valid-type]
    p: Page = Depends(page),
    ctx: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    visible = check_list_scope(ctx, client_code)
    stmt = select(Request).order_by(Request.created_at.desc(), Request.id.desc())
    if visible is not None:
        stmt = stmt.where(Request.client_code.in_(visible))
    if client_code:
        stmt = stmt.where(Request.client_code == client_code)
    if status:
        stmt = stmt.where(Request.status == status)
    rows, total = paged(db, stmt, p)
    return {"items": [request_json(r[0]) for r in rows], "total": total, "limit": p.limit, "offset": p.offset}


@router.get("/requests/{request_id}")
def get_request(request_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return request_json(visible_request(db, ctx, request_id))


# --- Drafts --------------------------------------------------------------------------------------


@router.post("/drafts", status_code=201)
def create_draft(body: DraftIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if body.content_flags is None:
        raise ApiError(422, "content_flags_required", "Pilih penanda isi konten, atau nyatakan tidak ada (daftar kosong).")
    for i, claim in enumerate(body.claims, start=1):
        if claim.category in FACTUAL_CATEGORIES and not claim.fact_key:
            raise ApiError(422, "claim_fact_key_required", f"Klaim #{i} ({claim.category}) wajib fact_key dari fact sheet klien.")
        if claim.evidence_label == "DATA FINAL" and not ((claim.source or "").strip() and claim.source_date):
            raise ApiError(422, "claim_source_required", f"Klaim #{i} berlabel DATA FINAL wajib source dan source_date.")
    # Kunci request: versi berikutnya dan approval versi lama tidak bisa balapan (trigger juga mengunci).
    req = visible_request(db, ctx, body.request_id, lock=True)
    if role_for(ctx, req.client_code) not in AGENCY_WRITERS:
        raise forbidden("Hanya staf agency yang menulis draft.")
    agent = agent_for_intent(req.intent)
    if agent is None or agent["status"] != "active":
        raise ApiError(409, "intent_not_active", "Pilar/agent untuk intent ini belum aktif; eskalasi ke owner.")
    # Brief/fact sheet klien lain dijawab sama dengan yang tidak ada (trigger juga menolak).
    if body.brief_id is not None and db.scalar(select(Brief.client_code).where(Brief.brief_id == body.brief_id)) != req.client_code:
        raise ApiError(409, "draft_client_mismatch", "Brief tidak ditemukan untuk klien request ini.")
    if body.fact_sheet_id is not None and db.scalar(select(FactSheet.client_code).where(FactSheet.id == body.fact_sheet_id)) != req.client_code:
        raise ApiError(409, "draft_client_mismatch", "Fact sheet tidak ditemukan untuk klien request ini.")
    client = db.get(Client, req.client_code)
    draft = Draft(
        request_id=req.id, brief_id=body.brief_id, fact_sheet_id=body.fact_sheet_id,
        skill=agent["skill"] or agent["prompt"] or agent["template"], version=latest_version(db, req.id) + 1,
        content=body.content, mode="SIMULASI" if client.simulation else "NYATA", created_by=ctx.user.id,
    )
    db.add(draft)
    db.flush()
    claims = [Claim(draft_id=draft.id, **c.model_dump()) for c in body.claims]
    db.add_all(claims)
    # Trigger sudah menambah penanda server dan mewarisi penanda manusia versi sebelumnya (migrasi 0007); penanda
    # pembuat yang sama tidak diduplikasi.
    present = {f.flag for f in active_flags(db, draft.id)}
    db.add_all(DraftFlag(draft_id=draft.id, flag=f, source="author", added_by=ctx.user.id)
               for f in dict.fromkeys(body.content_flags) if f not in present)
    req.status = "in_progress"
    db.flush()
    audit(db, ctx, "draft.create", "draft", draft.id, request_id=req.id, version=draft.version, claims=len(claims), mode=draft.mode,
          flags=sorted(f.flag for f in active_flags(db, draft.id)))
    db.commit()
    return with_levels(db, draft_json(draft, req.client_code, True, claims), draft.id)


@router.get("/drafts")
def list_drafts(
    request_id: int | None = Query(None, ge=1),
    client_code: str | None = Query(None, pattern=r"^[A-Z0-9]{2,12}$"),
    p: Page = Depends(page),
    ctx: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    visible = check_list_scope(ctx, client_code)
    latest = select(Draft.request_id, func.max(Draft.version).label("v")).group_by(Draft.request_id).subquery()
    stmt = (
        select(Draft, Request.client_code, (Draft.version == latest.c.v).label("latest"))
        .join(Request, Request.id == Draft.request_id)
        .join(latest, latest.c.request_id == Draft.request_id)
        .order_by(Draft.created_at.desc(), Draft.id.desc())
    )
    if visible is not None:
        stmt = stmt.where(Request.client_code.in_(visible))
    if client_code:
        stmt = stmt.where(Request.client_code == client_code)
    if request_id:
        stmt = stmt.where(Draft.request_id == request_id)
    rows, total = paged(db, stmt, p)
    return {"items": [draft_json(d, code, is_latest) for d, code, is_latest in rows], "total": total, "limit": p.limit, "offset": p.offset}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    draft, req = visible_draft(db, ctx, draft_id)
    claims = list(db.scalars(select(Claim).where(Claim.draft_id == draft.id).order_by(Claim.id)))
    return with_levels(db, draft_json(draft, req.client_code, draft.version == latest_version(db, req.id), claims), draft.id)


@router.post("/drafts/{draft_id}/flags", status_code=201)
def add_flag(draft_id: int, body: FlagIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Menambah penanda (hanya menaikkan level). Request selesai ditolak trigger (request_closed)."""
    draft, req = visible_draft(db, ctx, draft_id)
    if role_for(ctx, req.client_code) not in AGENCY_WRITERS:
        raise forbidden("Hanya staf agency yang menambah penanda.")
    if any(f.flag == body.flag for f in active_flags(db, draft.id)):
        raise ApiError(409, "flag_exists", "Penanda ini sudah ada di draft.")
    reviewed = db.scalar(select(func.count()).select_from(QARecord).where(QARecord.draft_id == draft.id, QARecord.reviewer_id == ctx.user.id))
    flag = DraftFlag(draft_id=draft.id, flag=body.flag, source="qa" if reviewed else "staff", added_by=ctx.user.id)
    db.add(flag)
    db.flush()
    audit(db, ctx, "draft_flag.add", "draft", draft.id, flag=flag.flag, source=flag.source)
    db.commit()
    return flag_json(flag)


@router.post("/drafts/{draft_id}/flags/{flag}/remove")
def remove_flag(draft_id: int, flag: Flag, body: FlagRemoveIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Menghapus penanda: hanya owner/content lead, dengan alasan, sekali; penanda server tidak bisa dihapus."""
    draft, req = visible_draft(db, ctx, draft_id)
    if role_for(ctx, req.client_code) not in SENIOR:
        raise forbidden("Hanya owner/content lead yang menghapus penanda.")
    row = next((f for f in active_flags(db, draft.id) if f.flag == flag), None)
    if row is None:
        raise ApiError(409, "flag_not_active", "Penanda ini tidak aktif di draft.")
    if row.source == "server":
        raise ApiError(409, "flag_not_removable", "Penanda dari jaring pengaman server tidak bisa dihapus; buat draft versi baru.")
    row.removed_by, row.removed_at, row.removed_reason = ctx.user.id, func.now(), body.reason
    db.flush()
    db.refresh(row)
    audit(db, ctx, "draft_flag.remove", "draft", draft.id, flag=row.flag, source=row.source)
    db.commit()
    return flag_json(row)


# --- QA ------------------------------------------------------------------------------------------


@router.post("/qa-records", status_code=201)
def create_qa(body: QAIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    draft, req = visible_draft(db, ctx, body.draft_id)
    role = role_for(ctx, req.client_code)
    if role not in AGENCY_WRITERS:
        raise forbidden("Hanya staf agency yang mencatat QA.")
    if body.independent and role not in SENIOR:
        raise ApiError(403, "independent_review_not_allowed", "Review independen hanya oleh owner/content lead (rule 08).")
    record = QARecord(draft_id=draft.id, gate=body.gate, result=body.result, reviewer_id=ctx.user.id, reviewer_role=role, independent=body.independent)
    db.add(record)
    db.flush()  # trigger: reviewer independen ≠ pembuat draft
    audit(db, ctx, "qa.create", "qa_record", record.id, draft_id=draft.id, gate=record.gate, result=record.result, independent=record.independent)
    db.commit()
    return qa_json(record)


@router.get("/qa-records")
def list_qa(
    draft_id: int | None = Query(None, ge=1),
    p: Page = Depends(page),
    ctx: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    visible = visible_client_codes(ctx.memberships)
    stmt = (
        select(QARecord).join(Draft, Draft.id == QARecord.draft_id).join(Request, Request.id == Draft.request_id)
        .order_by(QARecord.created_at.desc(), QARecord.id.desc())
    )
    if visible is not None:
        stmt = stmt.where(Request.client_code.in_(visible))
    if draft_id:
        stmt = stmt.where(QARecord.draft_id == draft_id)
    rows, total = paged(db, stmt, p)
    return {"items": [qa_json(r[0]) for r in rows], "total": total, "limit": p.limit, "offset": p.offset}


@router.get("/qa-records/{record_id}")
def get_qa(record_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    record = db.get(QARecord, record_id)
    if record is None:
        raise not_found()
    visible_draft(db, ctx, record.draft_id)
    return qa_json(record)


# --- Approvals -----------------------------------------------------------------------------------


@router.post("/approvals", status_code=201)
def create_approval(body: ApprovalIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    draft, req = visible_draft(db, ctx, body.draft_id)
    member = membership_for(ctx, req.client_code)
    role = member.role if member else None
    if role not in SENIOR and role != "client_approver":
        raise forbidden("Hanya approver klien atau owner/content lead yang mencatat approval.")
    allowed = member.max_level
    if LEVEL_ORDER[body.level] > LEVEL_ORDER[allowed]:
        raise ApiError(403, "level_not_allowed", f"Batas approval-mu {allowed or '-'}; level {body.level} butuh approver yang lebih tinggi.")
    channel_ref = body.channel_ref or None
    approval = Approval(
        draft_id=draft.id, level=body.level, decision=body.decision, approver_id=ctx.user.id,
        approver_role=role, channel_ref=channel_ref, mode=draft.mode,
    )
    db.add(approval)
    db.flush()  # trigger: fakta, versi terbaru, level minimum, bukan pembuat, bukti tertulis, review independen
    if draft.version == latest_version(db, req.id):
        req.status = {"Approved": "approved", "Rejected": "rejected", "Revise": "in_progress"}[body.decision]
    audit(db, ctx, "approval.create", "approval", approval.id, draft_id=draft.id, level=approval.level,
          decision=approval.decision, written_evidence=channel_ref is not None, scope=AGENCY if role in SENIOR else req.client_code)
    db.commit()
    return approval_json(approval)


@router.get("/approvals")
def list_approvals(
    draft_id: int | None = Query(None, ge=1),
    p: Page = Depends(page),
    ctx: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    visible = visible_client_codes(ctx.memberships)
    stmt = (
        select(Approval).join(Draft, Draft.id == Approval.draft_id).join(Request, Request.id == Draft.request_id)
        .order_by(Approval.decided_at.desc(), Approval.id.desc())
    )
    if visible is not None:
        stmt = stmt.where(Request.client_code.in_(visible))
    if draft_id:
        stmt = stmt.where(Approval.draft_id == draft_id)
    rows, total = paged(db, stmt, p)
    return {"items": [approval_json(r[0]) for r in rows], "total": total, "limit": p.limit, "offset": p.offset}


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise not_found()
    visible_draft(db, ctx, approval.draft_id)
    return approval_json(approval)

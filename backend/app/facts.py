"""Klien, fact sheet, dan konfirmasi fakta (Tahap 1 PR 3b, kontrak core/shared/api-contracts.md 0.8.0).

Alur Konfirmasi Fakta (clau-content design/user-flow/client-portal-flow.md, rule 08):
1. Agency membuat versi fact sheet + daftar fakta (`POST /fact-sheets`).
2. Approver klien menjawab setiap fakta: benar (`confirmed`) atau koreksi (`corrected` + nilai yang benar).
   Owner/content lead boleh mencatat jawaban tertulis klien, dengan bukti (`channel_ref`).
3. Fact sheet disetujui setelah semua fakta dijawab (`POST /fact-sheets/{id}/approve`), lalu beku.
   Draft yang klaimnya merujuk fakta di fact sheet yang disetujui boleh di-approve (trigger migrasi 0004).

Aturan data ditegakkan database (migrasi 0005); modul ini menegakkan siapa boleh apa dan isolasi per klien.
Nilai fakta adalah data klien: tidak pernah ditulis ke audit_log, hanya id dan keputusan.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.access import AGENCY, visible_client_codes
from app.auth.deps import AuthContext, current_user, get_db, require_owner
from app.db.models import (
    CLIENT_CODE_RE,
    FACT_DECISIONS,
    FACT_KEY_RE,
    FACTUAL_CATEGORIES,
    REF_RE,
    VERTICALS,
    Client,
    Fact,
    FactConfirmation,
    FactSheet,
    INVISIBLE,
)
from app.errors import ApiError
from app.workflow import (
    AGENCY_WRITERS,
    SENIOR,
    Body,
    Page,
    audit,
    check_list_scope,
    forbidden,
    is_self_serve_owner,
    iso,
    not_found,
    page,
    paged,
    role_for,
)

router = APIRouter()

ANSWERERS = SENIOR | {"client_approver"}  # menjawab/menyetujui atas nama klien (agency: dengan bukti tertulis)
BLANK_RE = re.compile(f"[\\s{INVISIBLE}]+")


def visible_text(value: str | None, field: str) -> None:
    """Teks yang hanya berisi spasi/karakter tak terlihat (zero-width, bidi) dianggap kosong."""
    if value is not None and not BLANK_RE.sub("", value):
        raise ValueError(f"{field} tidak boleh kosong")


# --- Body ----------------------------------------------------------------------------------------


class ClientIn(Body):
    client_code: str = Field(pattern=CLIENT_CODE_RE)
    vertical: Literal[VERTICALS]  # type: ignore[valid-type]
    business_type: str = Field(min_length=1, max_length=60)
    location_area: str | None = Field(default=None, max_length=120)
    approver_role: str = Field(min_length=1, max_length=60)  # jabatan approver di klien (mis. owner, GM), bukan nama
    simulation: bool = False


class FactIn(Body):
    fact_key: str = Field(max_length=64, pattern=FACT_KEY_RE)
    category: Literal[FACTUAL_CATEGORIES]  # type: ignore[valid-type]
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def key_matches_category(self) -> FactIn:
        if not self.fact_key.startswith(f"{self.category}."):
            raise ValueError(f"fact_key harus berbentuk {self.category}.<nama>")
        visible_text(self.label, "label")
        visible_text(self.value, "value")
        return self


class FactSheetIn(Body):
    client_code: str = Field(pattern=CLIENT_CODE_RE)
    # Wajib untuk agency (dokumen sumber). Pemilik usaha mandiri mengisi Brain di dashboard: boleh kosong (0.13.0).
    document_ref: str | None = Field(default=None, max_length=500, pattern=REF_RE)
    facts: list[FactIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_keys(self) -> FactSheetIn:
        keys = [f.fact_key for f in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("fact_key tidak boleh dobel dalam satu fact sheet")
        return self


class ConfirmationIn(Body):
    fact_key: str = Field(max_length=64, pattern=FACT_KEY_RE)
    decision: Literal[FACT_DECISIONS]  # type: ignore[valid-type]
    value_after: str | None = Field(default=None, max_length=1000)
    channel_ref: str | None = Field(default=None, max_length=500, pattern=REF_RE)

    @model_validator(mode="after")
    def correction_has_value(self) -> ConfirmationIn:
        if self.decision == "corrected" and not self.value_after:
            raise ValueError("koreksi wajib berisi nilai yang benar (value_after)")
        visible_text(self.value_after, "value_after")
        if self.decision == "confirmed":
            self.value_after = None
        return self


class ApproveIn(Body):
    approval_ref: str | None = Field(default=None, max_length=500, pattern=REF_RE)


# --- JSON ----------------------------------------------------------------------------------------


def client_json(c: Client) -> dict:
    return {"client_code": c.client_code, "vertical": c.vertical, "business_type": c.business_type,
            "location_area": c.location_area, "approver_role": c.approver_role, "simulation": c.simulation,
            "self_serve": c.self_serve, "created_at": iso(c.created_at)}


def confirmation_json(c: FactConfirmation) -> dict:
    return {"id": c.id, "fact_sheet_id": c.fact_sheet_id, "fact_key": c.fact_key, "decision": c.decision,
            "value_before": c.value_before, "value_after": c.value_after, "confirmed_by": c.confirmed_by,
            "confirmed_by_role": c.confirmed_by_role, "channel_ref": c.channel_ref, "confirmed_at": iso(c.confirmed_at)}


def sheet_json(s: FactSheet, facts_total: int, facts_answered: int) -> dict:
    return {"id": s.id, "client_code": s.client_code, "version": s.version, "document_ref": s.document_ref,
            "created_by": s.created_by, "created_at": iso(s.created_at), "approved_at": iso(s.approved_at),
            "approved_by": s.approved_by, "approved_by_role": s.approved_by_role, "approval_ref": s.approval_ref,
            "status": "approved" if s.approved_at else "ready" if facts_total and facts_answered == facts_total else "pending",
            "facts_total": facts_total, "facts_answered": facts_answered}


def sheet_detail(db: Session, s: FactSheet) -> dict:
    facts = list(db.scalars(select(Fact).where(Fact.fact_sheet_id == s.id).order_by(Fact.category, Fact.fact_key)))
    answers: dict[str, list[FactConfirmation]] = {}
    for c in db.scalars(select(FactConfirmation).where(FactConfirmation.fact_sheet_id == s.id)
                        .order_by(FactConfirmation.confirmed_at, FactConfirmation.id)):
        answers.setdefault(c.fact_key, []).append(c)
    items = []
    for f in facts:
        history = answers.get(f.fact_key, [])
        last = history[-1] if history else None
        items.append({
            "fact_key": f.fact_key, "category": f.category, "label": f.label, "value": f.value,
            "status": last.decision if last else "pending",
            # Nilai yang berlaku: koreksi klien terakhir, atau nilai awal bila dikonfirmasi/belum dijawab.
            "current_value": (last.value_after if last and last.decision == "corrected" else f.value),
            "answers": [confirmation_json(c) for c in history],
        })
    out = sheet_json(s, len(items), sum(1 for i in items if i["status"] != "pending"))
    out["facts"] = items
    return out


def counts_subquery():
    answered = (
        select(FactConfirmation.fact_sheet_id, func.count(func.distinct(FactConfirmation.fact_key)).label("n"))
        .group_by(FactConfirmation.fact_sheet_id).subquery()
    )
    total = select(Fact.fact_sheet_id, func.count().label("n")).group_by(Fact.fact_sheet_id).subquery()
    return total, answered


def visible_sheet(db: Session, ctx: AuthContext, sheet_id: int, lock: bool = False) -> FactSheet:
    # Akses dicek dulu: user klien lain tidak pernah sempat mengunci fact sheet yang bukan miliknya.
    sheet = db.get(FactSheet, sheet_id)
    visible = visible_client_codes(ctx.memberships)
    if sheet is None or (visible is not None and sheet.client_code not in visible):
        raise not_found()
    if lock:
        db.refresh(sheet, with_for_update=True)
    return sheet


# --- Klien ---------------------------------------------------------------------------------------


@router.get("/clients")
def list_clients(ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    visible = visible_client_codes(ctx.memberships)
    stmt = select(Client).order_by(Client.client_code)
    if visible is not None:
        stmt = stmt.where(Client.client_code.in_(visible))
    return {"items": [client_json(c) for c in db.scalars(stmt)]}


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    if db.get(Client, body.client_code) is not None:
        raise ApiError(409, "client_exists", "Kode klien itu sudah dipakai.")
    client = Client(**body.model_dump())
    db.add(client)
    db.flush()
    audit(db, ctx, "client.create", "client", client.client_code, simulation=client.simulation)
    db.commit()
    return client_json(client)


# --- Fact sheet ----------------------------------------------------------------------------------


@router.post("/fact-sheets", status_code=201)
def create_fact_sheet(body: FactSheetIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    owner = is_self_serve_owner(db, ctx, body.client_code)
    if role_for(ctx, body.client_code) not in AGENCY_WRITERS and not owner:
        raise forbidden("Hanya staf agency atau pemilik usaha langganan mandiri yang menyusun fact sheet.")
    if body.document_ref is None and not owner:
        raise ApiError(422, "document_ref_required", "Fact sheet dari agency wajib menyebut dokumen sumbernya (document_ref).")
    # Klien dikunci: versi berikutnya tidak bisa balapan (trigger juga mengunci).
    if db.scalar(select(Client).where(Client.client_code == body.client_code).with_for_update(key_share=True)) is None:
        raise ApiError(404, "client_not_found", "Klien tidak dikenal.")
    version = (db.scalar(select(func.max(FactSheet.version)).where(FactSheet.client_code == body.client_code)) or 0) + 1
    document_ref = body.document_ref or f"workspace://brain/{body.client_code}/v{version}"
    sheet = FactSheet(client_code=body.client_code, version=version, document_ref=document_ref, created_by=ctx.user.id)
    db.add(sheet)
    db.flush()
    db.add_all(Fact(fact_sheet_id=sheet.id, **f.model_dump()) for f in body.facts)
    db.flush()
    audit(db, ctx, "fact_sheet.create", "fact_sheet", sheet.id, client_code=sheet.client_code, version=version, facts=len(body.facts))
    if owner:
        # Brain bisnis langganan mandiri (0.13.0): fakta yang ditulis pemilik usaha = jawaban klien. Dikonfirmasi dan
        # disetujui sekaligus oleh dia sendiri (trigger migrasi 0010 mengizinkannya hanya untuk klien self_serve).
        db.add_all(FactConfirmation(fact_sheet_id=sheet.id, fact_key=f.fact_key, decision="confirmed",
                                    confirmed_by=ctx.user.id, confirmed_by_role="client_approver") for f in body.facts)
        db.flush()
        sheet.approved_at = datetime.now(timezone.utc)
        sheet.approved_by = ctx.user.id
        sheet.approved_by_role = "client_approver"
        db.flush()
        audit(db, ctx, "fact_sheet.approve", "fact_sheet", sheet.id, client_code=sheet.client_code, version=version,
              written_evidence=False, scope=sheet.client_code, self_serve=True)
    db.commit()
    return sheet_detail(db, sheet)


@router.get("/fact-sheets")
def list_fact_sheets(
    client_code: str | None = Query(None, pattern=CLIENT_CODE_RE),
    approved: bool | None = None,
    p: Page = Depends(page),
    ctx: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    visible = check_list_scope(ctx, client_code)
    total, answered = counts_subquery()
    stmt = (
        select(FactSheet, func.coalesce(total.c.n, 0), func.coalesce(answered.c.n, 0))
        .outerjoin(total, total.c.fact_sheet_id == FactSheet.id)
        .outerjoin(answered, answered.c.fact_sheet_id == FactSheet.id)
        .order_by(FactSheet.client_code, FactSheet.version.desc())
    )
    if visible is not None:
        stmt = stmt.where(FactSheet.client_code.in_(visible))
    if client_code:
        stmt = stmt.where(FactSheet.client_code == client_code)
    if approved is not None:
        stmt = stmt.where(FactSheet.approved_at.is_not(None) if approved else FactSheet.approved_at.is_(None))
    rows, n = paged(db, stmt, p)
    return {"items": [sheet_json(s, t, a) for s, t, a in rows], "total": n, "limit": p.limit, "offset": p.offset}


@router.get("/fact-sheets/{sheet_id}")
def get_fact_sheet(sheet_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return sheet_detail(db, visible_sheet(db, ctx, sheet_id))


@router.post("/fact-sheets/{sheet_id}/confirmations", status_code=201)
def confirm_fact(sheet_id: int, body: ConfirmationIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    sheet = visible_sheet(db, ctx, sheet_id, lock=True)
    role = role_for(ctx, sheet.client_code)
    if role not in ANSWERERS:
        raise forbidden("Hanya approver klien (atau owner/content lead dengan bukti tertulis klien) yang menjawab fakta.")
    if sheet.approved_at is not None:
        raise ApiError(409, "fact_sheet_frozen", "Fact sheet ini sudah disetujui; buat versi baru.")
    answer = FactConfirmation(
        fact_sheet_id=sheet.id, fact_key=body.fact_key, decision=body.decision, value_after=body.value_after,
        confirmed_by=ctx.user.id, confirmed_by_role=role, channel_ref=body.channel_ref,
    )
    db.add(answer)
    db.flush()  # trigger: fakta ada, peran, bukti tertulis, bukan pembuat, nilai koreksi
    db.refresh(answer)
    audit(db, ctx, "fact.answer", "fact_sheet", sheet.id, fact_key=answer.fact_key, decision=answer.decision,
          written_evidence=answer.channel_ref is not None, scope=AGENCY if role in SENIOR else sheet.client_code)
    db.commit()
    return confirmation_json(answer)


@router.post("/fact-sheets/{sheet_id}/approve")
def approve_fact_sheet(sheet_id: int, body: ApproveIn, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    sheet = visible_sheet(db, ctx, sheet_id, lock=True)
    role = role_for(ctx, sheet.client_code)
    if role not in ANSWERERS:
        raise forbidden("Hanya approver klien (atau owner/content lead dengan bukti tertulis klien) yang menyetujui fact sheet.")
    if sheet.approved_at is not None:
        raise ApiError(409, "fact_sheet_frozen", "Fact sheet ini sudah disetujui; buat versi baru.")
    sheet.approved_at = datetime.now(timezone.utc)
    sheet.approved_by = ctx.user.id
    sheet.approved_by_role = role
    sheet.approval_ref = body.approval_ref
    db.flush()  # trigger: semua fakta dijawab, peran, bukti tertulis, bukan pembuat
    audit(db, ctx, "fact_sheet.approve", "fact_sheet", sheet.id, client_code=sheet.client_code, version=sheet.version,
          written_evidence=sheet.approval_ref is not None, scope=AGENCY if role in SENIOR else sheet.client_code)
    db.commit()
    return sheet_detail(db, sheet)

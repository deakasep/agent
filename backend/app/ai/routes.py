"""Endpoint AI menulis draft (kontrak core api-contracts 0.9.0 § AI Menulis Draft).

Endpoint hanya membuat/membaca/membatalkan job; draft dibuat worker. Peran, agent, intent, fact sheet, dan pembuat
tidak pernah diambil dari body. Tidak ada endpoint publish.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ai.budget import budget_problem, month_bounds, month_start, spent
from app.ai.config import ai_settings
from app.ai.factcheck import latest_approved_sheet
from app.auth.deps import AuthContext, current_user, get_db, require_owner
from app.billing.catalog import credit_cost
from app.billing.ledger import charge
from app.db.models import AI_JOB_STATUSES, CLIENT_CODE_RE, AiBudget, AiCall, AiJob, Client, Request
from app.errors import ApiError
from app.registry import agent_for_intent
from app.workflow import (
    AGENCY_WRITERS, Body, Page, audit, check_list_scope, forbidden, is_self_serve_owner, iso, not_found, page, paged, role_for,
    visible_request,
)

router = APIRouter()
MONTH_RE = r"^\d{4}-(0[1-9]|1[0-2])$"
BUDGET_MESSAGES = {
    "ai_budget_missing": "Batas biaya AI bulan ini belum diatur owner.",
    "ai_budget_exceeded": "Batas biaya AI bulan ini sudah tercapai.",
}


def job_json(j: AiJob, client_code: str) -> dict:
    return {
        "id": j.id, "request_id": j.request_id, "client_code": client_code, "agent_id": j.agent_id, "intent": j.intent,
        "kind": j.kind, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts, "error_code": j.error_code,
        "fact_sheet_id": j.fact_sheet_id, "draft_id": j.draft_id, "requested_by": j.requested_by,
        "created_at": iso(j.created_at), "finished_at": iso(j.finished_at),
    }


def budget_json(b: AiBudget) -> dict:
    return {"scope": b.scope, "month": b.month.strftime("%Y-%m"), "limit_micro_usd": b.limit_micro_usd,
            "alert_at_pct": b.alert_at_pct, "updated_by": b.updated_by, "updated_at": iso(b.updated_at)}


def parse_month(value: str | None) -> date:
    return month_start() if value is None else date(int(value[:4]), int(value[5:7]), 1)


@router.post("/requests/{request_id}/ai-drafts", status_code=202)
def create_ai_draft(request_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    settings = ai_settings()
    if not settings.enabled:
        raise ApiError(409, "ai_disabled", "Fitur AI sedang dimatikan owner.")
    req = visible_request(db, ctx, request_id, lock=True)
    if role_for(ctx, req.client_code) not in AGENCY_WRITERS and not is_self_serve_owner(db, ctx, req.client_code):
        raise forbidden("Hanya staf agency atau pemilik usaha langganan mandiri yang meminta draft AI.")
    if req.status not in ("open", "in_progress"):
        raise ApiError(409, "request_closed", "Request sudah selesai; buat request baru.")
    agent = agent_for_intent(req.intent)
    if agent is None or agent["status"] != "active":
        raise ApiError(409, "intent_not_active", "Pilar/agent untuk intent ini belum aktif; eskalasi ke owner.")
    if req.intent not in settings.intents:
        raise ApiError(409, "ai_intent_not_enabled", "AI belum diaktifkan untuk jenis konten ini.")
    client = db.get(Client, req.client_code)
    if settings.provider == "fake" and not client.simulation:
        raise ApiError(409, "ai_provider_test_only", "Mode uji AI hanya untuk klien SIMULASI.")
    sheet = latest_approved_sheet(db, req.client_code)
    if sheet is None:
        raise ApiError(409, "fact_sheet_required", "AI hanya menulis dari fakta yang sudah disetujui klien: setujui fact sheet dulu.")
    # Pembuatan job antre bergiliran (kunci transaksi): cadangan biaya job aktif tidak bisa dihitung dua kali.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('clau_ai_budget'))"))
    problem = budget_problem(db, req.client_code, settings.job_estimate_micro_usd, reserve_active=True)
    if problem:
        raise ApiError(409, problem, BUDGET_MESSAGES[problem])
    job = AiJob(request_id=req.id, agent_id=agent["id"], intent=req.intent, kind="draft", fact_sheet_id=sheet.id, requested_by=ctx.user.id)
    db.add(job)
    db.flush()  # indeks unik: satu job aktif per request (ai_job_active)
    # Kredit (AI-CONSTITUTION v4.0.0 §4b): dipotong di transaksi yang sama, sebelum model dipanggil; kurang = 402 dan
    # job ikut batal (rollback). Gagal/dibatalkan = kredit kembali (trigger migrasi 0008). Klien SIMULASI = mode uji.
    credits = 0
    if not client.simulation:
        cost = credit_cost(req.intent)
        if cost is None:
            raise ApiError(409, "credit_cost_missing", "Tarif kredit untuk jenis pekerjaan ini belum diatur.")
        charge(db, req.client_code, cost, job.id)
        credits = cost
    audit(db, ctx, "ai_job.create", "ai_job", job.id, request_id=req.id, agent_id=job.agent_id, fact_sheet_id=sheet.id, credits=credits)
    db.commit()
    return job_json(job, req.client_code)


@router.get("/ai-jobs")
def list_ai_jobs(
    request_id: int | None = Query(None, ge=1),
    client_code: str | None = Query(None, pattern=CLIENT_CODE_RE),
    status: Literal[AI_JOB_STATUSES] | None = None,  # type: ignore[valid-type]
    p: Page = Depends(page),
    ctx: AuthContext = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    visible = check_list_scope(ctx, client_code)
    stmt = select(AiJob, Request.client_code).join(Request, Request.id == AiJob.request_id).order_by(AiJob.created_at.desc(), AiJob.id.desc())
    if visible is not None:
        stmt = stmt.where(Request.client_code.in_(visible))
    if client_code:
        stmt = stmt.where(Request.client_code == client_code)
    if request_id:
        stmt = stmt.where(AiJob.request_id == request_id)
    if status:
        stmt = stmt.where(AiJob.status == status)
    rows, total = paged(db, stmt, p)
    return {"items": [job_json(j, code) for j, code in rows], "total": total, "limit": p.limit, "offset": p.offset}


def visible_job(db: Session, ctx: AuthContext, job_id: int, lock: bool = False) -> tuple[AiJob, str]:
    stmt = select(AiJob).where(AiJob.id == job_id)
    job = db.scalar(stmt.with_for_update() if lock else stmt)
    if job is None:
        raise not_found()
    req = visible_request(db, ctx, job.request_id)  # klien lain = 404 juga
    return job, req.client_code


@router.get("/ai-jobs/{job_id}")
def get_ai_job(job_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job, code = visible_job(db, ctx, job_id)
    return job_json(job, code)


@router.post("/ai-jobs/{job_id}/cancel")
def cancel_ai_job(job_id: int, ctx: AuthContext = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    job, code = visible_job(db, ctx, job_id, lock=True)
    if role_for(ctx, code) not in AGENCY_WRITERS and not is_self_serve_owner(db, ctx, code):
        raise forbidden("Hanya staf agency atau pemilik usaha langganan mandiri yang membatalkan job AI.")
    if job.status != "queued":
        raise ApiError(409, "ai_job_not_cancellable", "Job sudah berjalan atau selesai; tidak bisa dibatalkan.")
    job.status, job.error_code, job.finished_at = "cancelled", "cancelled_by_user", datetime.now(timezone.utc)
    audit(db, ctx, "ai_job.cancel", "ai_job", job.id, request_id=job.request_id)
    db.commit()
    return job_json(job, code)


@router.get("/ai-usage")
def ai_usage(month: str | None = Query(None, pattern=MONTH_RE), ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    m = parse_month(month)
    start, end = month_bounds(m)
    base = (
        select(Request.client_code, AiJob.agent_id, func.sum(AiCall.cost_micro_usd), func.count(AiCall.id))
        .join(AiJob, AiJob.id == AiCall.job_id).join(Request, Request.id == AiJob.request_id)
        .where(AiCall.created_at >= start, AiCall.created_at < end)
        .group_by(Request.client_code, AiJob.agent_id)
    )
    rows = db.execute(base).all()
    by_client: dict[str, list[int]] = {}
    by_agent: dict[str, list[int]] = {}
    for client_code, agent_id, cost, calls in rows:
        for bucket, key in ((by_client, client_code), (by_agent, agent_id)):
            acc = bucket.setdefault(key, [0, 0])
            acc[0] += int(cost)
            acc[1] += int(calls)
    budgets = []
    for b in db.scalars(select(AiBudget).where(AiBudget.month == m).order_by(AiBudget.scope)):
        used = spent(db, m, None if b.scope == "global" else b.scope)
        budgets.append({**budget_json(b), "spent_micro_usd": used, "alert": used * 100 >= b.limit_micro_usd * b.alert_at_pct})
    return {
        "month": m.strftime("%Y-%m"),
        "total_micro_usd": sum(v[0] for v in by_client.values()),
        "calls": sum(v[1] for v in by_client.values()),
        "budgets": budgets,
        "by_client": [{"client_code": k, "cost_micro_usd": v[0], "calls": v[1]} for k, v in sorted(by_client.items())],
        "by_agent": [{"agent_id": k, "cost_micro_usd": v[0], "calls": v[1]} for k, v in sorted(by_agent.items())],
    }


class BudgetIn(Body):
    scope: str = Field(pattern=r"^(global|[A-Z0-9]{2,12})$")
    month: str = Field(pattern=MONTH_RE)
    limit_micro_usd: int = Field(ge=1, le=100_000_000_000)
    alert_at_pct: int = Field(default=80, ge=1, le=100)


@router.put("/ai-budgets")
def put_ai_budget(body: BudgetIn, ctx: AuthContext = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    if body.scope != "global" and db.get(Client, body.scope) is None:
        raise ApiError(404, "client_not_found", "Klien tidak dikenal.")
    m = parse_month(body.month)
    row = db.scalar(select(AiBudget).where(AiBudget.scope == body.scope, AiBudget.month == m).with_for_update())
    if row is None:
        row = AiBudget(scope=body.scope, month=m, limit_micro_usd=body.limit_micro_usd, alert_at_pct=body.alert_at_pct, updated_by=ctx.user.id)
        db.add(row)
    else:
        row.limit_micro_usd, row.alert_at_pct, row.updated_by = body.limit_micro_usd, body.alert_at_pct, ctx.user.id
        row.updated_at = datetime.now(timezone.utc)
    db.flush()
    audit(db, ctx, "ai_budget.set", "ai_budget", f"{body.scope}:{body.month}", limit_micro_usd=body.limit_micro_usd, alert_at_pct=body.alert_at_pct)
    db.commit()
    return budget_json(row)

"""CLAU AI agents backend.

Registry & router statis dari clau-core, login & user (app/auth), dan workflow request → draft → QA →
approval (app/workflow), serta klien, fact sheet & konfirmasi fakta (app/facts), dan langganan & kredit (app/billing). Sengaja tidak ada endpoint yang mem-publish konten, mengirim pesan ke tamu, atau
mengubah sistem client (core/AI-CONSTITUTION.md §4).
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import DataError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.routes import router as ai_router
from app.auth.routes import router as auth_router
from app.auth.signup import router as signup_router
from app.billing.routes import router as billing_router
from app.errors import ApiError, db_rule_code, error_body
from app.facts import router as facts_router
from app.registry import load_registry
from app.workflow import router as workflow_router

__version__ = "0.14.0"

# Pengamanan (docs/security.md §3). Semua bisa diatur lewat environment di server, tanpa ubah kode.
CLAU_ENV = os.environ.get("CLAU_ENV") or "development"
# Swagger /docs dan /openapi.json hanya untuk development; di produksi peta API tidak dibuka ke publik.
# Nilai kosong (mis. dari docker compose) = tidak diatur.
DOCS_ENABLED = (os.environ.get("CLAU_ENABLE_DOCS") or ("1" if CLAU_ENV == "development" else "0")) == "1"
# Hanya Host yang dikenal (cegah Host header injection / DNS rebinding). Di VPS 2 isi dengan domain API.
ALLOWED_HOSTS = [h.strip() for h in (os.environ.get("CLAU_ALLOWED_HOSTS") or "127.0.0.1,localhost,testserver").split(",") if h.strip()]
# Body request maksimum: JSON kecil; terbesar = draft (konten ≤ 10.000 karakter UTF-8 + ≤ 30 klaim).
MAX_BODY_BYTES = 64 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}

app = FastAPI(
    title="CLAU AI Agents",
    version=__version__,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)
# Tanpa CORSMiddleware: browser dari domain lain tidak bisa memanggil API ini (deny by default).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        length = request.headers.get("content-length")
        if length is None:
            # Chunked tanpa Content-Length tidak diterima: ukuran harus diketahui sebelum dibaca.
            response = JSONResponse(status_code=411, content=error_body("length_required", "Content-Length wajib diisi."))
        elif not length.isdigit() or int(length) > MAX_BODY_BYTES:
            response = JSONResponse(status_code=413, content=error_body("payload_too_large", "Body request terlalu besar."))
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    docs = DOCS_ENABLED and request.url.path in {"/docs", "/docs/oauth2-redirect"}
    for key, value in SECURITY_HEADERS.items():
        if docs and key == "Content-Security-Policy":
            continue  # Swagger UI (development saja) memuat script & style dari CDN.
        response.headers.setdefault(key, value)
    return response


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # 404/405 dll. memakai bentuk error kontrak, tanpa detail internal.
    codes = {404: "not_found", 405: "method_not_allowed"}
    message = {404: "Endpoint tidak ada.", 405: "Method tidak diizinkan."}.get(exc.status_code, "Request ditolak.")
    return JSONResponse(status_code=exc.status_code, content=error_body(codes.get(exc.status_code, "http_error"), message), headers=getattr(exc, "headers", None))


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    # Aturan yang ditolak database (CHECK/trigger, migrasi 0001): kode aturan saja, tanpa detail SQL.
    diag = getattr(exc.orig, "diag", None)
    code = db_rule_code(str(exc.orig), getattr(diag, "constraint_name", None))
    return JSONResponse(status_code=409, content=error_body(code, "Data ditolak aturan sistem."))


@app.exception_handler(DataError)
async def data_error_handler(_: Request, __: DataError) -> JSONResponse:
    # Nilai yang ditolak tipe data Postgres (lolos validasi body): 422, bukan 500.
    return JSONResponse(status_code=422, content=error_body("invalid_input", "Isi request tidak bisa disimpan."))


@app.exception_handler(Exception)
async def internal_error_handler(_: Request, __: Exception) -> JSONResponse:
    # Jangan bocorkan stack trace, path file, atau isi registry ke klien.
    return JSONResponse(status_code=500, content=error_body("internal_error", "Terjadi kesalahan di server."))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = ", ".join(".".join(str(p) for p in err["loc"][1:]) or "body" for err in exc.errors())
    return JSONResponse(status_code=422, content=error_body("validation_error", f"Request tidak valid: {fields}"))


class RouteRequest(BaseModel):
    # Field lain ditolak (bukan diabaikan), dan intent dibatasi ke format id registry.
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "clau-ai-agents-backend", "version": __version__}


@app.get("/agents")
def list_agents() -> dict:
    registry = load_registry()
    forbidden = registry["default_forbidden_actions"]
    return {"agents": [{**agent, "forbidden_actions": forbidden} for agent in registry["agents"]]}


@app.get("/pillars")
def list_pillars() -> dict:
    registry = load_registry()
    return {
        "pillars": [
            {**pillar, "agents": [a["id"] for a in registry["agents"] if a["pillar"] == pillar["id"]]}
            for pillar in registry["pillars"]
        ]
    }


@app.post("/route")
def route(request: RouteRequest) -> dict:
    for agent in load_registry()["agents"]:
        if request.intent in agent["intents"]:
            return {
                "intent": request.intent,
                "agent": agent["id"],
                "pillar": agent["pillar"],
                "skill": agent["skill"] or agent["prompt"] or agent["template"],
                "repo": agent["skill_repo"],
                "approval_min": agent["approval_min"],
                # Highest autonomy level allowed (core AI-CONSTITUTION §4a); every intent defaults to B (draft).
                "autonomy_max": agent["autonomy_max"],
                "status": agent["status"],
                # Planned pillars are not worked on: create a board task and escalate (core/orchestrator/router.md).
                "next_step": "produce_draft" if agent["status"] == "active" else "escalate_to_owner",
            }
    raise ApiError(404, "unknown_intent", f"Intent '{request.intent}' tidak dikenal; tanya requester.")


app.include_router(auth_router)
app.include_router(signup_router)
app.include_router(workflow_router)
app.include_router(facts_router)
app.include_router(ai_router)
app.include_router(billing_router)

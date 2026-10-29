"""Klien langganan mandiri memakai agen sendiri (TASK-007, kontrak core 0.13.0, migrasi 0010), ke PostgreSQL sungguhan.

Alur yang harus jalan tanpa staf: pemilik usaha mengisi Brain bisnis → membuat permintaan → meminta draft AI →
menyetujui. Pengecualian review independen hanya untuk klien `self_serve`; klien terkelola tidak berubah, dan
isolasi antarklien tetap berlaku.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pyotp")
pytest.importorskip("psycopg")

from sqlalchemy import text, update  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

from app.ai.provider import ClaimOut  # noqa: E402
from app.db.models import Client, FactSheet  # noqa: E402
from tests.test_ai import StubProvider, ai_on, ask_ai, put_budget, run_all  # noqa: E402,F401
from tests.test_workflow import Actor, code, engine, factory, new_request, team  # noqa: E402,F401

BRAIN = [
    {"fact_key": "facility.pool-private", "category": "facility", "label": "Kolam renang pribadi", "value": "ya"},
    {"fact_key": "price.kopi-susu", "category": "price", "label": "Harga kopi susu", "value": "Rp18.000"},
]


@pytest.fixture(scope="module")
def shop(factory, team):
    """Dua usaha mandiri (seperti hasil /auth/signup) + kredit & budget AI untuk test."""
    with factory() as s, s.begin():
        for c in ("WARUNG", "TOKOB"):
            s.add(Client(client_code=c, vertical="food-beverage", business_type="kedai kopi", approver_role="pemilik", simulation=False, self_serve=True))
    owner_a = Actor(factory, "client_approver", scope="WARUNG", level="L3")
    owner_b = Actor(factory, "client_approver", scope="TOKOB", level="L3")
    put_budget(team["owner"], 50_000_000)
    for c in ("WARUNG", "TOKOB", "CTH"):
        r = team["owner"].post("/billing/adjustments", {"client_code": c, "credits": 5000, "note": "kredit uji test_self_serve"})
        assert r.status_code == 201, r.text
    return {"a": owner_a, "b": owner_b}


def write_brain(actor: Actor, client="WARUNG", facts=BRAIN):
    return actor.post("/fact-sheets", {"client_code": client, "facts": facts})


def test_signup_clients_are_marked_self_serve(factory, team, shop):
    clients = shop["a"].get("/clients").json()["items"]
    assert [(c["client_code"], c["self_serve"]) for c in clients] == [("WARUNG", True)]
    assert {c["client_code"]: c["self_serve"] for c in team["owner"].get("/clients").json()["items"]}["CTH"] is False


def test_owner_writes_brain_and_it_is_approved_at_once(factory, team, shop):
    r = write_brain(shop["a"])
    assert r.status_code == 201, r.text
    sheet = r.json()
    assert sheet["status"] == "approved" and sheet["approved_by"] == shop["a"].id and sheet["approved_by_role"] == "client_approver"
    assert sheet["document_ref"] == f"workspace://brain/WARUNG/v{sheet['version']}"
    assert {f["fact_key"]: (f["status"], f["current_value"]) for f in sheet["facts"]} == {
        "facility.pool-private": ("confirmed", "ya"), "price.kopi-susu": ("confirmed", "Rp18.000")}
    # Versi baru = Brain diperbarui; yang lama tetap tersimpan (beku).
    again = write_brain(shop["a"], facts=[{**BRAIN[1], "value": "Rp20.000"}])
    assert again.status_code == 201 and again.json()["version"] == sheet["version"] + 1


def test_brain_rights_stay_narrow(factory, team, shop):
    # Klien lain, approver klien terkelola, dan viewer tidak bisa menulis Brain usaha lain / tanpa hak.
    assert write_brain(shop["b"], client="WARUNG").status_code == 403
    assert write_brain(team["approver"], client="CTH").status_code == 403
    assert write_brain(team["viewer"], client="CTH").status_code == 403
    # Agency tetap wajib menyebut dokumen sumber, dan fact sheet-nya tetap menunggu jawaban klien.
    r = team["staff"].post("/fact-sheets", {"client_code": "CTH", "facts": BRAIN})
    assert r.status_code == 422 and code(r) == "document_ref_required"
    r = team["staff"].post("/fact-sheets", {"client_code": "WARUNG", "document_ref": "workspace://fs", "facts": BRAIN})
    assert r.status_code == 201 and r.json()["status"] == "pending"


def test_full_flow_without_staff(factory, team, shop, monkeypatch):
    """Selesai bila TASK-007: daftar → bayar → isi Brain → minta caption → setujui, tanpa bantuan staf."""
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    owner = shop["a"]
    assert write_brain(owner).status_code == 201
    req = new_request(owner, client="WARUNG", text="Caption promo kopi susu pagi ini")
    r = ask_ai(owner, req["id"])
    assert r.status_code == 202, r.text
    assert owner.get("/billing/wallet", client_code="WARUNG").json()["balance"]["total"] < 5000  # kredit terpotong
    # Pemeriksa fakta hanya meloloskan kutipan persis (nilai, atau "label: nilai"), bukan parafrase.
    claims = [ClaimOut("Harga kopi susu: Rp18.000", "price", "price.kopi-susu")]
    assert run_all(factory, StubProvider(claims=claims)) == ["succeeded"]
    draft = owner.get("/drafts", request_id=req["id"]).json()["items"][0]
    detail = owner.get(f"/drafts/{draft['id']}").json()
    assert draft["mode"] == "NYATA" and draft["created_by"] is None and detail["min_level"] in ("L2", "L3")
    r = owner.post("/approvals", {"draft_id": draft["id"], "level": detail["min_level"], "decision": "Approved"})
    assert r.status_code == 201, r.text
    assert owner.get(f"/requests/{req['id']}").json()["status"] == "approved"


def test_unconfirmed_claims_still_block_self_serve_approval(factory, team, shop, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    owner = shop["a"]
    assert write_brain(owner).status_code == 201
    req = new_request(owner, client="WARUNG")
    assert ask_ai(owner, req["id"]).status_code == 202
    assert run_all(factory, StubProvider(claims=[ClaimOut("Ada pantai pribadi", "facility", "facility.private-beach")])) == ["succeeded"]
    draft = owner.get("/drafts", request_id=req["id"]).json()["items"][0]
    r = owner.post("/approvals", {"draft_id": draft["id"], "level": "L3", "decision": "Approved"})
    assert r.status_code == 409 and code(r) == "facts_unconfirmed"
    # Minta revisi tetap bisa.
    assert owner.post("/approvals", {"draft_id": draft["id"], "level": "L3", "decision": "Revise"}).status_code == 201


def test_owner_can_cancel_own_queued_job_only(factory, team, shop, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    owner = shop["a"]
    assert write_brain(owner).status_code == 201
    req = new_request(owner, client="WARUNG")
    r = ask_ai(owner, req["id"])
    assert r.status_code == 202, r.text
    job = r.json()
    assert shop["b"].post(f"/ai-jobs/{job['id']}/cancel", {}).status_code == 404
    r = owner.post(f"/ai-jobs/{job['id']}/cancel", {})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_managed_clients_keep_independent_review(factory, team, shop, monkeypatch):
    """Klien terkelola: approver klien tetap tidak bisa meminta draft AI, dan draft agent tetap butuh review independen."""
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    req = new_request(team["approver"], client="CTH")
    r = ask_ai(team["approver"], req["id"])
    assert r.status_code == 403 and code(r) == "forbidden"
    write = team["staff"].post("/fact-sheets", {"client_code": "CTH", "document_ref": "workspace://fs", "facts": BRAIN[:1]})
    sheet = write.json()
    assert team["approver"].post(f"/fact-sheets/{sheet['id']}/confirmations", {"fact_key": BRAIN[0]["fact_key"], "decision": "confirmed"}).status_code == 201
    assert team["approver"].post(f"/fact-sheets/{sheet['id']}/approve", {}).status_code == 200
    assert ask_ai(team["staff"], req["id"]).status_code == 202
    assert run_all(factory, StubProvider()) == ["succeeded"]
    draft = team["staff"].get("/drafts", request_id=req["id"]).json()["items"][0]
    r = team["approver"].post("/approvals", {"draft_id": draft["id"], "level": "L2", "decision": "Approved"})
    assert r.status_code == 409 and code(r) == "approval_needs_independent_review"


def test_database_exception_only_for_self_serve_clients(factory, team, shop):
    """Trigger 0010: menandai ulang klien self_serve = false langsung mengembalikan aturan lama."""
    owner = shop["b"]
    with factory() as s, s.begin():
        s.execute(update(Client).where(Client.client_code == "TOKOB").values(self_serve=False))
    try:
        r = write_brain(owner, client="TOKOB")
        assert r.status_code == 403  # API: bukan lagi pemilik usaha mandiri
        with factory() as s, s.begin():  # langsung ke database: pembuat fact sheet tidak boleh menyetujuinya
            version = (s.scalar(text("SELECT max(version) FROM fact_sheets WHERE client_code = 'TOKOB'")) or 0) + 1
            sheet = FactSheet(client_code="TOKOB", version=version, document_ref="workspace://x", created_by=owner.id)
            s.add(sheet)
            s.flush()
            s.execute(text("INSERT INTO facts (fact_sheet_id, fact_key, category, label, value) VALUES (:i, 'price.a', 'price', 'a', '1')"), {"i": sheet.id})
            with pytest.raises(DBAPIError, match="approval_by_author"):
                with s.begin_nested():
                    s.execute(text("INSERT INTO fact_confirmations (fact_sheet_id, fact_key, decision, confirmed_by, confirmed_by_role) "
                                   "VALUES (:i, 'price.a', 'confirmed', :u, 'client_approver')"), {"i": sheet.id, "u": owner.id})
    finally:
        with factory() as s, s.begin():
            s.execute(update(Client).where(Client.client_code == "TOKOB").values(self_serve=True))

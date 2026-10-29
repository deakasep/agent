"""AI menulis draft (Tahap 2, kontrak core 0.9.0, AI-BOUNDARY 1.4.0), ke PostgreSQL sungguhan.

Alur owner (2026-10-15): AI menghasilkan → AI fact-check ke fakta klien → manusia review → approve → final.
Menguji: penjaga endpoint (tombol mati, intent, provider uji hanya SIMULASI, fact sheet wajib, budget, satu job aktif,
peran & isolasi klien), worker (antrean SKIP LOCKED, retry, tolak, request ditutup, job macet), fact-check (klaim tanpa
fakta mengunci approval), penyamaran data sebelum ke provider, aturan database 0006, dan jejak tanpa isi konten.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta

import pytest

pytest.importorskip("pyotp")
pytest.importorskip("psycopg")

from sqlalchemy import func, select, text, update  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402

import app.ai.config as ai_config  # noqa: E402
from app.ai import worker  # noqa: E402
from app.ai.budget import month_start  # noqa: E402
from app.ai.factcheck import ClientFacts, check_claims  # noqa: E402
from app.ai.prompt import build_prompt, redact  # noqa: E402
from app.ai.provider import ClaimOut, FactForPrompt, FakeProvider, Generation, ProviderFailure, Usage  # noqa: E402
from app.db.models import AiCall, AiJob, AuditLog, Claim, Client, Draft, FactConfirmation, FactSheet, QARecord, Request  # noqa: E402
from tests.test_workflow import EVIDENCE, Actor, engine, factory, fact_sheet, new_request, team  # noqa: E402,F401

MONTH = month_start().strftime("%Y-%m")


# --- Unit: penyamaran & fact-check (tanpa database) ----------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [
    # Data pribadi → disamarkan
    ("Hubungi tamu di budi.santoso@mail.com ya", "Hubungi tamu di <KONTAK> ya"),
    ("budi[at]mail.com", "<KONTAK>"),
    ("budi @ mail.com", "<KONTAK>"),
    ("WA +62 812-3456-7890 sebelum jam 9", "WA <KONTAK> sebelum jam 9"),
    ("telp 081234567890", "telp <KONTAK>"),
    ("0812.3456.7890", "<KONTAK>"),
    ("kantor 021 1234567", "kantor <KONTAK>"),
    ("telp (0361) 123456", "telp <KONTAK>"),
    ("booking BK2026-8891 kamar 12", "booking <NO_BOOKING> kamar <NO_KAMAR>"),
    ("booking 123456", "booking <NO_BOOKING>"),
    ("PNR ABC12D", "PNR <NO_BOOKING>"),
    ("kode HMABCXYZ12", "kode <NO_BOOKING>"),
    ("reservasi 1234567890123", "reservasi <NO_BOOKING>"),
    ("NIK 3171234567890001", "NIK <NO_BOOKING>"),
    # Isi konten normal → utuh (temuan audit 2026-10-16: harga, tanggal, jam, luas, kode promo)
    ("caption untuk 2026-10-16 sore", "caption untuk 2026-10-16 sore"),
    ("promo 3 malam, 2 kolam, 15 menit ke pantai", "promo 3 malam, 2 kolam, 15 menit ke pantai"),
    ("Rp 125.000.000", "Rp 125.000.000"),
    ("Rp 1.250.000 - 2.500.000", "Rp 1.250.000 - 2.500.000"),
    ("Rp15000000 per malam", "Rp15000000 per malam"),
    ("20.12.2026 - 05.01.2027", "20.12.2026 - 05.01.2027"),
    ("12.12.2026 19.00", "12.12.2026 19.00"),
    ("2026-12-31 20:00-23:59", "2026-12-31 20:00-23:59"),
    ("1200m2, 1500k, NYE2026, Q4-2026", "1200m2, 1500k, NYE2026, Q4-2026"),
    ("villa 3 kamar tidur, kamar 2 tamu", "villa 3 kamar tidur, kamar 2 tamu"),
    ("kode promo HEMAT20", "kode promo HEMAT20"),
])
def test_redact_personal_data_before_provider(raw, expected):
    assert redact(raw) == expected


def facts_of(**values) -> ClientFacts:
    facts = {k.replace("__", "."): FactForPrompt(k.replace("__", "."), k.split("__")[0], k, v) for k, v in values.items()}
    return ClientFacts(sheet_id=1, client_code="CTHSIM", version=2, facts=facts, answered_on={k: date(2026, 10, 15) for k in facts})


def test_fact_check_labels_are_decided_by_the_worker_not_the_model():
    cf = facts_of(facility__pool_private="ya", location__ubud="10 menit ke Ubud")
    checked = check_claims((
        ClaimOut("facility__pool_private: ya", "facility", "facility.pool_private"),  # kutipan berlabel
        ClaimOut("Nikmati pantai pribadi kami", "facility", "facility.pantai-pribadi"),  # tidak ada di fact sheet
        ClaimOut("Harga mulai 1 juta", "price", None),  # fakta tanpa kunci
        ClaimOut("Kolam pribadi", "location", "facility.pool_private"),  # kunci kategori lain tidak dipinjam
        ClaimOut("Suasana tenang", "experience", None),
        ClaimOut("Klaim aneh", "bukan-kategori", "x"),  # kategori tak dikenal: ditandai, tidak pernah "aman"
        ClaimOut("Enjoy our private beach", "Facility", "facility.private-beach"),  # huruf besar: tetap dicek
        ClaimOut("Pantai pribadi", "amenity", None),
        ClaimOut("10 menit ke Ubud", "location", "location.ubud"),  # nilai fakta utuh
        ClaimOut("Dekat pantai Kuta", "location", "location.ubud"),  # kunci benar, isi tidak sesuai nilai fakta
    ), cf)
    assert [(c.category, c.evidence_label, c.fact_key, c.grounded) for c in checked] == [
        ("facility", "DATA FINAL", "facility.pool_private", True),
        ("facility", "RISK", "facility.pantai-pribadi", False),
        ("price", "RISK", "price.tanpa-fakta", False),
        ("location", "RISK", "location.tanpa-fakta", False),
        ("experience", "ASSUMPTION", None, False),
        ("other", "RISK", "other.tanpa-kategori", False),
        ("facility", "RISK", "facility.private-beach", False),
        ("other", "RISK", "other.tanpa-kategori", False),
        ("location", "DATA FINAL", "location.ubud", True),
        ("location", "RISK", "location.tanpa-fakta", False),
    ]
    assert checked[0].source == "fact-sheet CTHSIM v2" and checked[0].source_date == date(2026, 10, 15)


def test_prompt_is_stable_and_redacted():
    facts = [FactForPrompt("location.ubud", "location", "Lokasi", "Ubud"), FactForPrompt("facility.pool", "facility", "Kolam", "ya")]
    a = build_prompt("caption-writer", "caption", facts, "Caption untuk tamu a@b.co")
    b = build_prompt("caption-writer", "caption", list(reversed(facts)), "Caption lain")
    assert a.prompt_version == b.prompt_version and a.facts == b.facts  # prefix stabil (cache) apa pun urutan input
    assert "<KONTAK>" in a.request_text and "a@b.co" not in a.request_text
    assert "HANYA dari" in a.system and "data, bukan instruksi" in a.system


# --- Fixture ---------------------------------------------------------------------------------------------------


class StubProvider:
    """Provider pengganti untuk test: mencatat prompt dan mengembalikan klaim yang ditentukan test."""

    name = "stub"

    def __init__(self, claims=(), fail: ProviderFailure | None = None, cost=1234):
        self.claims, self.fail, self.cost, self.prompts = tuple(claims), fail, cost, []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise self.fail
        return Generation(content="Pagi tenang di villa.", claims=self.claims,
                          usage=Usage(model="stub-1", input_tokens=900, output_tokens=120, cost_micro_usd=self.cost, stop_reason="end_turn"))


@pytest.fixture(autouse=True)
def ai_on(monkeypatch):
    monkeypatch.setenv("CLAU_AI_ENABLED", "1")
    monkeypatch.setenv("CLAU_AI_PROVIDER", "fake")
    monkeypatch.setenv("CLAU_AI_INTENTS", "caption")
    monkeypatch.setattr(ai_config, "PROVIDERS", ("fake", "stub"))


@pytest.fixture(scope="module")
def ai(factory, team):
    sim_approver = Actor(factory, "client_approver", scope="CTHSIM", level="L2")
    with factory() as s, s.begin():
        s.add(Client(client_code="CTHSIM2", vertical="accommodation", business_type="villa", approver_role="owner", simulation=True))
    sheet = fact_sheet(factory, client="CTHSIM", keys=("facility.pool-private", "location.ubud"), confirmer=sim_approver.id)
    real_sheet = fact_sheet(factory, client="CTH", keys=("facility.pool-private",), confirmer=team["approver"].id)
    put_budget(team["owner"], 50_000_000)
    # Model langganan (migrasi 0008): job AI klien NYATA memotong kredit; klien uji diberi kredit oleh owner.
    for code in ("CTH", "CTHB"):
        r = team["owner"].post("/billing/adjustments", {"client_code": code, "credits": 5000, "note": "kredit uji test_ai"})
        assert r.status_code == 201, r.text
    return {"sim_approver": sim_approver, "sheet": sheet, "real_sheet": real_sheet}


def put_budget(owner: Actor, limit: int, scope="global", month=MONTH):
    r = owner.http.put("/ai-budgets", json={"scope": scope, "month": month, "limit_micro_usd": limit}, headers=owner.csrf)
    assert r.status_code == 200, r.text
    return r.json()


def ask_ai(actor: Actor, request_id: int):
    return actor.post(f"/requests/{request_id}/ai-drafts", {})


def run_all(factory, provider=None) -> list[str]:
    done = []
    while (status := worker.run_once(factory, provider or FakeProvider(), "test-worker")) is not None:
        done.append(status)
    return done


def job_row(factory, job_id) -> AiJob:
    with factory() as s:
        return s.get(AiJob, job_id)


# --- Alur utama --------------------------------------------------------------------------------------------------


def test_ai_draft_end_to_end_on_simulasi_client(factory, team, ai):
    staff = team["staff"]
    req = new_request(staff, client="CTHSIM", text="Caption pagi, kontak tamu budi@mail.com")
    r = ask_ai(staff, req["id"])
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["agent_id"] == "caption-writer" and job["fact_sheet_id"] == ai["sheet"]
    assert run_all(factory) == ["succeeded"]

    job = staff.get(f"/ai-jobs/{job['id']}").json()
    assert job["status"] == "succeeded" and job["attempts"] == 1
    draft = staff.get(f"/drafts/{job['draft_id']}").json()
    assert draft["created_by"] is None and draft["agent_id"] == "caption-writer" and draft["mode"] == "SIMULASI"
    assert draft["fact_sheet_id"] == ai["sheet"] and "provider tiruan" in draft["content"]
    assert {c["evidence_label"] for c in draft["claims"]} == {"DATA FINAL"}
    assert all(c["source"].startswith("fact-sheet CTHSIM v") for c in draft["claims"])
    qa = staff.get("/qa-records", draft_id=draft["id"]).json()["items"]
    assert [(q["gate"], q["result"], q["reviewer_id"], q["independent"]) for q in qa] == [("claim-verification", "Conditional", None, False)]
    assert staff.get(f"/requests/{req['id']}").json()["status"] == "in_progress"

    with factory() as s:
        calls = list(s.scalars(select(AiCall).where(AiCall.job_id == job["id"])))
        assert [(c.provider, c.model, c.cost_micro_usd) for c in calls] == [("fake", "fake-0", 0)]
        metas = [a.meta for a in s.scalars(select(AuditLog).where(AuditLog.action.like("ai_job.%") | (AuditLog.object_id == str(draft["id"]))))]
    blob = repr(metas)
    assert "budi" not in blob and "Caption pagi" not in blob and "Kolam" not in blob  # jejak tanpa isi


def test_private_beach_is_flagged_and_blocks_approval(factory, team, ai, monkeypatch):
    """Contoh owner: AI menulis "private beach" padahal tidak ada di fakta → ditandai, tidak bisa di-approve."""
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    staff, lead, approver = team["staff"], team["lead"], team["approver"]
    req = new_request(staff, client="CTH")
    assert ask_ai(staff, req["id"]).status_code == 202
    beach = StubProvider(claims=[ClaimOut("facility.pool-private: ya", "facility", "facility.pool-private"),
                                 ClaimOut("Enjoy our private beach", "facility", "facility.private-beach")])
    assert run_all(factory, beach) == ["succeeded"]
    draft = staff.get("/drafts", request_id=req["id"]).json()["items"][0]
    claims = {c["fact_key"]: c["evidence_label"] for c in staff.get(f"/drafts/{draft['id']}").json()["claims"]}
    assert claims == {"facility.pool-private": "DATA FINAL", "facility.private-beach": "RISK"}
    assert draft["mode"] == "NYATA" and draft["created_by"] is None
    qa = staff.get("/qa-records", draft_id=draft["id"]).json()["items"]
    assert [q["result"] for q in qa] == ["Fail"]
    # Review manusia lulus pun, approval tetap terkunci: klaim pantai tidak dikonfirmasi klien.
    assert lead.post("/qa-records", {"draft_id": draft["id"], "gate": "claim-verification", "result": "Pass", "independent": True}).status_code == 201
    r = approver.post("/approvals", {"draft_id": draft["id"], "level": "L2", "decision": "Approved"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "facts_unconfirmed"

    # Versi berikutnya tanpa klaim pantai (AI diminta ulang): bisa direview & di-approve klien.
    assert ask_ai(staff, req["id"]).status_code == 202
    grounded = StubProvider(claims=[ClaimOut("facility.pool-private: ya", "facility", "facility.pool-private")])
    assert run_all(factory, grounded) == ["succeeded"]
    v2 = staff.get("/drafts", request_id=req["id"]).json()["items"][0]
    assert v2["version"] == 2 and v2["latest"]
    assert lead.post("/qa-records", {"draft_id": v2["id"], "gate": "claim-verification", "result": "Pass", "independent": True}).status_code == 201
    r = approver.post("/approvals", {"draft_id": v2["id"], "level": "L2", "decision": "Approved"})
    assert r.status_code == 201, r.text
    assert staff.get(f"/requests/{req['id']}").json()["status"] == "approved"


def test_prompt_gets_only_confirmed_latest_facts_and_redacted_text(factory, team, ai, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    staff, approver = team["staff"], team["approver"]
    # Versi fact sheet baru yang disetujui, dengan koreksi klien; versi lama tidak boleh ikut.
    with factory() as s, s.begin():
        version = s.scalar(select(func.max(FactSheet.version)).where(FactSheet.client_code == "CTH")) + 1
        sheet = FactSheet(client_code="CTH", version=version, document_ref="workspace://fs")
        s.add(sheet)
        s.flush()
        from app.db.models import Fact
        s.add(Fact(fact_sheet_id=sheet.id, fact_key="capacity.guests", category="capacity", label="Kapasitas", value="4 tamu"))
        s.flush()
        s.add(FactConfirmation(fact_sheet_id=sheet.id, fact_key="capacity.guests", decision="corrected", value_after="6 tamu",
                               confirmed_by=approver.id, confirmed_by_role="client_approver"))
        s.flush()
        sheet.approved_at, sheet.approved_by, sheet.approved_by_role = func.now(), approver.id, "client_approver"
    req = new_request(staff, client="CTH", text="Untuk tamu booking BK2026-8891, WA 0812 3456 7890")
    assert ask_ai(staff, req["id"]).status_code == 202
    stub = StubProvider()
    assert run_all(factory, stub) == ["succeeded"]
    prompt = stub.prompts[0]
    assert [(f.fact_key, f.value) for f in prompt.facts] == [("capacity.guests", "6 tamu")]
    assert "BK2026" not in prompt.request_text and "0812" not in prompt.request_text
    assert "<NO_BOOKING>" in prompt.request_text and "<KONTAK>" in prompt.request_text


# --- Penjaga endpoint ----------------------------------------------------------------------------------------------


def test_who_can_ask_for_an_ai_draft(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    for who in ("viewer", "approver", "other"):
        r = ask_ai(team[who], req["id"])
        assert r.status_code in (403, 404), (who, r.text)  # klien lain = 404, peran lain = 403
    sim_viewer = Actor(factory, "viewer", scope="CTHSIM", level="L1")
    assert ask_ai(sim_viewer, req["id"]).status_code == 403
    assert ask_ai(ai["sim_approver"], req["id"]).status_code == 403  # approver klien tidak memesan draft
    assert ask_ai(team["lead"], req["id"]).status_code == 202
    r = ask_ai(team["staff"], req["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_job_active"
    run_all(factory)


def test_endpoint_guards(factory, team, ai, monkeypatch):
    staff = team["staff"]

    def code(req_id):
        r = ask_ai(staff, req_id)
        assert r.status_code == 409, r.text
        return r.json()["error"]["code"]

    sim = new_request(staff, client="CTHSIM")
    monkeypatch.setenv("CLAU_AI_ENABLED", "0")
    assert code(sim["id"]) == "ai_disabled"
    monkeypatch.setenv("CLAU_AI_ENABLED", "1")
    monkeypatch.setenv("CLAU_AI_PROVIDER", "openai-palsu")  # provider tak dikenal = mati (fail closed)
    assert code(sim["id"]) == "ai_disabled"
    monkeypatch.setenv("CLAU_AI_PROVIDER", "fake")
    assert code(new_request(staff, client="CTHSIM", intent="reel-script")["id"]) == "ai_intent_not_enabled"
    assert code(new_request(staff, client="CTH")["id"]) == "ai_provider_test_only"
    assert code(new_request(staff, client="CTHSIM2")["id"]) == "fact_sheet_required"
    import app.ai.budget as budget

    real_month_start = budget.month_start
    monkeypatch.setattr(budget, "month_start", lambda day=None: date(2001, 1, 1))  # bulan tanpa batas biaya
    assert code(sim["id"]) == "ai_budget_missing"
    monkeypatch.setattr(budget, "month_start", real_month_start)
    put_budget(team["owner"], 1, scope="CTHSIM")
    try:
        assert code(sim["id"]) == "ai_budget_exceeded"  # perkiraan per job > batas klien
    finally:
        put_budget(team["owner"], 50_000_000, scope="CTHSIM")
    with factory() as s, s.begin():
        s.execute(update(Request).where(Request.id == sim["id"]).values(status="closed"))
    assert code(sim["id"]) == "request_closed"


def test_cancel_only_queued_jobs(factory, team, ai):
    staff = team["staff"]
    req = new_request(staff, client="CTHSIM")
    job = ask_ai(staff, req["id"]).json()
    assert team["viewer"].post(f"/ai-jobs/{job['id']}/cancel", {}).status_code == 404  # viewer CTH, job klien lain
    r = staff.post(f"/ai-jobs/{job['id']}/cancel", {})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["error_code"] == "cancelled_by_user"
    r = staff.post(f"/ai-jobs/{job['id']}/cancel", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_job_not_cancellable"
    assert run_all(factory) == []
    assert ask_ai(staff, req["id"]).status_code == 202  # job baru boleh setelah dibatalkan
    run_all(factory)


def test_jobs_of_other_clients_are_invisible(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    job = ask_ai(team["staff"], req["id"]).json()
    run_all(factory)
    assert team["other"].get(f"/ai-jobs/{job['id']}").status_code == 404
    assert all(j["client_code"] == "CTHB" for j in team["other"].get("/ai-jobs").json()["items"])
    assert team["other"].get("/ai-jobs", client_code="CTHSIM").status_code == 403


# --- Worker --------------------------------------------------------------------------------------------------------


def test_temporary_provider_failure_is_retried_then_fails(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM", text="[uji:gagal-sementara]")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    for attempt in (1, 2):
        assert run_all(factory) == ["queued"]
        job = job_row(factory, job_id)
        assert job.status == "queued" and job.attempts == attempt and job.run_after > job.created_at
        with factory() as s, s.begin():  # jeda retry dipercepat untuk test (queued → queued: jadwal ulang)
            s.execute(update(AiJob).where(AiJob.id == job_id).values(run_after=func.now()))
    assert run_all(factory) == ["failed"]
    job = job_row(factory, job_id)
    assert (job.status, job.error_code, job.attempts) == ("failed", "provider_unavailable", 3)


def test_refusal_fails_the_job_but_is_still_recorded(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM", text="[uji:tolak]")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    assert run_all(factory) == ["failed"]
    assert job_row(factory, job_id).error_code == "refused"
    with factory() as s:
        assert [c.stop_reason for c in s.scalars(select(AiCall).where(AiCall.job_id == job_id))] == ["refusal"]
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.request_id == req["id"])) == 0


def test_request_closed_while_job_runs(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    with factory() as s:
        lease = worker.claim(s, "w1")
    assert lease.job_id == job_id
    with factory() as s, s.begin():
        s.execute(update(Request).where(Request.id == req["id"]).values(status="closed"))
    assert worker.process(factory, FakeProvider(), lease) == "failed"
    assert job_row(factory, job_id).error_code == "request_closed"


def test_stuck_job_is_requeued_then_times_out(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    for _ in range(3):
        with factory() as s:
            assert worker.claim(s, "mati").job_id == job_id
        with factory() as s:
            assert worker.reap(s, timeout_s=-1) == 1  # worker "mati" di tengah jalan
    job = job_row(factory, job_id)
    assert (job.status, job.error_code, job.attempts) == ("failed", "worker_timeout", 3)


def test_two_workers_never_take_the_same_job(factory, team, ai):
    ids = [ask_ai(team["staff"], new_request(team["staff"], client="CTHSIM")["id"]).json()["id"] for _ in range(2)]
    got, barrier = [], threading.Barrier(3)

    def take():
        with factory() as s:
            barrier.wait()
            got.append(worker.claim(s, threading.current_thread().name))

    threads = [threading.Thread(target=take) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    leases = [x for x in got if x is not None]
    assert sorted(x.job_id for x in leases) == sorted(ids) and got.count(None) == 1
    for lease in leases:
        assert worker.process(factory, FakeProvider(), lease) == "succeeded"


def test_fake_provider_never_writes_for_a_real_client(factory, team, ai):
    """Job klien NYATA yang lolos ke antrean (mis. dibuat sebelum provider diganti) ditolak worker provider tiruan."""
    req = new_request(team["staff"], client="CTH")
    with factory() as s, s.begin():
        s.add(AiJob(request_id=req["id"], agent_id="caption-writer", intent="caption", requested_by=team["staff"].id))
    assert run_all(factory) == ["failed"]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.request_id == req["id"])) == 0


def test_kill_switch_stops_queued_jobs(factory, team, ai, monkeypatch):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    monkeypatch.setenv("CLAU_AI_ENABLED", "0")
    assert run_all(factory) == []  # worker mati tidak mengambil job, tetapi menggagalkan antrean
    job = job_row(factory, job_id)
    assert (job.status, job.error_code) == ("failed", "ai_disabled")
    monkeypatch.setenv("CLAU_AI_ENABLED", "1")
    assert ask_ai(team["staff"], req["id"]).status_code == 202  # request tidak terkunci job lama
    run_all(factory)


def test_kill_switch_during_model_call_discards_result_but_records_cost(factory, team, ai, monkeypatch):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]

    class SwitchOff(StubProvider):
        def generate(self, prompt):
            monkeypatch.setenv("CLAU_AI_ENABLED", "0")  # owner mematikan AI saat model sedang menulis
            return super().generate(prompt)

    assert run_all(factory, SwitchOff(cost=500)) == ["failed"]
    assert job_row(factory, job_id).error_code == "ai_disabled"
    with factory() as s:
        assert [c.cost_micro_usd for c in s.scalars(select(AiCall).where(AiCall.job_id == job_id))] == [500]
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.request_id == req["id"])) == 0


# --- Aturan database 0006 --------------------------------------------------------------------------------------------


def db_error(factory, statement, **params) -> str:
    with factory() as s:
        with pytest.raises(DBAPIError) as e:
            s.execute(text(statement), params)
            s.commit()
        return str(e.value.orig)


def test_ai_records_cannot_be_rewritten(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    run_all(factory)
    assert "ai_job_transition" in db_error(factory, "UPDATE ai_jobs SET status = 'queued', finished_at = NULL, draft_id = NULL WHERE id = :i", i=job_id)
    msg = db_error(factory, "DELETE FROM ai_jobs WHERE id = :i", i=job_id)
    assert "permission denied" in msg or "ai_record_append_only" in msg
    msg = db_error(factory, "UPDATE ai_calls SET cost_micro_usd = 0 WHERE job_id = :i", i=job_id)
    assert "permission denied" in msg or "ai_record_append_only" in msg


def test_agent_draft_for_real_client_needs_running_job(factory, team, ai):
    req = new_request(team["staff"], client="CTH")
    msg = db_error(factory, "INSERT INTO drafts (request_id, skill, version, content, mode, agent_id) "
                            "VALUES (:r, 'draft-caption', 1, 'x', 'NYATA', 'caption-writer')", r=req["id"])
    assert "ai_draft_without_job" in msg


def test_succeeded_job_must_point_to_its_own_agent_draft(factory, team, ai):
    staff = team["staff"]
    req = new_request(staff, client="CTHSIM")
    human = staff.post("/drafts", {"content_flags": [], "request_id": req["id"], "content": "manual"}).json()
    job_id = ask_ai(staff, req["id"]).json()["id"]
    with factory() as s:
        lease = worker.claim(s, "w")
    msg = db_error(factory, "UPDATE ai_jobs SET status = 'succeeded', draft_id = :d, finished_at = now() WHERE id = :i", d=human["id"], i=job_id)
    assert "ai_job_draft_mismatch" in msg
    assert worker.process(factory, FakeProvider(), lease) == "succeeded"


# --- Biaya --------------------------------------------------------------------------------------------------------


def test_usage_and_budget_are_owner_only(factory, team, ai, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    req = new_request(team["staff"], client="CTH")
    assert ask_ai(team["staff"], req["id"]).status_code == 202
    assert run_all(factory, StubProvider(cost=7000)) == ["succeeded"]
    usage = team["owner"].get("/ai-usage").json()
    assert usage["month"] == MONTH and usage["total_micro_usd"] >= 7000
    assert any(c["client_code"] == "CTH" and c["cost_micro_usd"] >= 7000 for c in usage["by_client"])
    glob = next(b for b in usage["budgets"] if b["scope"] == "global")
    assert glob["limit_micro_usd"] == 50_000_000 and glob["spent_micro_usd"] >= 7000 and glob["alert"] is False
    assert team["lead"].get("/ai-usage").status_code == 403
    r = team["lead"].http.put("/ai-budgets", json={"scope": "global", "month": MONTH, "limit_micro_usd": 1}, headers=team["lead"].csrf)
    assert r.status_code == 403
    r = team["owner"].http.put("/ai-budgets", json={"scope": "NOPE", "month": MONTH, "limit_micro_usd": 5}, headers=team["owner"].csrf)
    assert r.status_code == 404
    for bad in ({"scope": "global", "month": "2026-13", "limit_micro_usd": 5}, {"scope": "global", "month": MONTH, "limit_micro_usd": 0}):
        assert team["owner"].http.put("/ai-budgets", json=bad, headers=team["owner"].csrf).status_code == 422


def test_budget_reached_stops_the_worker(factory, team, ai, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    monkeypatch.setenv("CLAU_AI_JOB_ESTIMATE_MICRO_USD", "0")
    req = new_request(team["staff"], client="CTH")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    with factory() as s:
        used = s.scalar(select(func.coalesce(func.sum(AiCall.cost_micro_usd), 0)))
    put_budget(team["owner"], max(int(used), 1), scope="global")  # sudah habis terpakai
    try:
        assert run_all(factory, StubProvider()) == ["failed"]
        assert job_row(factory, job_id).error_code == "budget_exceeded"
    finally:
        put_budget(team["owner"], 50_000_000)


# --- Regresi audit 2026-10-16 ---------------------------------------------------------------------------------------


def agent_draft(factory, team, actor, client="CTH", claims=()):
    req = new_request(actor, client=client)
    assert ask_ai(actor, req["id"]).status_code == 202
    assert run_all(factory, StubProvider(claims=claims)) == ["succeeded"]
    return req, actor.get("/drafts", request_id=req["id"]).json()["items"][0]


def test_real_client_agent_draft_always_needs_independent_human_review(factory, team, ai, monkeypatch):
    """Model yang tidak melaporkan klaim / memakai kategori aneh tidak boleh membuka jalur approval L1."""
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    _, draft = agent_draft(factory, team, team["staff"], claims=[ClaimOut("Pantai pribadi", "amenity", None),
                                                                   ClaimOut("Suasana tenang", "experience", None)])
    claims = team["staff"].get(f"/drafts/{draft['id']}").json()["claims"]
    assert [(c["category"], c["evidence_label"], c["fact_key"]) for c in claims] == [
        ("other", "RISK", "other.tanpa-kategori"), ("experience", "ASSUMPTION", None)]
    r = team["approver_l1"].post("/approvals", {"draft_id": draft["id"], "level": "L1", "decision": "Approved"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_level_too_low"

    # Tanpa klaim sama sekali pun (model diam): draft agent NYATA tetap minimal L2.
    _, silent = agent_draft(factory, team, team["staff"])
    r = team["approver_l1"].post("/approvals", {"draft_id": silent["id"], "level": "L1", "decision": "Approved"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_level_too_low"


def test_simulasi_agent_draft_without_claims_keeps_request_level(factory, team, ai):
    req, draft = agent_draft(factory, team, team["staff"], client="CTHSIM")
    with factory() as s:
        assert s.scalar(text("SELECT clau_draft_min_level(d, r) FROM drafts d JOIN requests r ON r.id = d.request_id "
                             "WHERE d.id = :i"), {"i": draft["id"]}) == "L1"


def test_requester_of_ai_draft_counts_as_its_author(factory, team, ai, monkeypatch):
    monkeypatch.setenv("CLAU_AI_PROVIDER", "stub")
    lead, lead2 = team["lead"], team["lead2"]
    _, draft = agent_draft(factory, team, lead, claims=[ClaimOut("Suasana tenang", "experience", None)])
    r = lead.post("/qa-records", {"draft_id": draft["id"], "gate": "claim-verification", "result": "Pass", "independent": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "qa_reviewer_is_author"
    assert lead2.post("/qa-records", {"draft_id": draft["id"], "gate": "claim-verification", "result": "Pass", "independent": True}).status_code == 201
    for decision in ("Approved", "Revise", "Rejected"):
        r = lead.post("/approvals", {"draft_id": draft["id"], "level": "L2", "decision": decision, **EVIDENCE})
        assert r.status_code == 409 and r.json()["error"]["code"] == "approval_by_author", r.text
    r = team["approver"].post("/approvals", {"draft_id": draft["id"], "level": "L2", "decision": "Approved"})
    assert r.status_code == 201, r.text


def test_too_many_claims_fail_the_job_instead_of_dropping_claims(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    many = [ClaimOut(f"Klaim {i}", "experience", None) for i in range(worker.MAX_CLAIMS)] + [
        ClaimOut("Enjoy our private beach", "facility", "facility.private-beach")]  # klaim ke-31: tidak boleh hilang
    assert run_all(factory, StubProvider(claims=many, cost=900)) == ["failed"]
    assert job_row(factory, job_id).error_code == "invalid_output"
    with factory() as s:
        assert [c.cost_micro_usd for c in s.scalars(select(AiCall).where(AiCall.job_id == job_id))] == [900]
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.request_id == req["id"])) == 0


@pytest.mark.parametrize("content,claims", [
    ("x" * 10_001, ()), (" ", ()),
    ("Konten Contoh", (ClaimOut("x" * 301, "experience"),)),
])
def test_invalid_output_keeps_usage_without_creating_partial_draft(factory, team, ai, content, claims):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]

    class Invalid(StubProvider):
        def generate(self, prompt):
            return Generation(content, claims, Usage(model="stub", cost_micro_usd=901))

    assert run_all(factory, Invalid()) == ["failed"]
    assert job_row(factory, job_id).error_code == "invalid_output"
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.request_id == req["id"])) == 0
        assert [c.cost_micro_usd for c in s.scalars(select(AiCall).where(AiCall.job_id == job_id))] == [901]


def test_omitted_claims_do_not_receive_automatic_qa_pass(factory, team, ai):
    _, draft = agent_draft(factory, team, team["staff"], client="CTHSIM")
    qa = team["staff"].get("/qa-records", draft_id=draft["id"]).json()["items"]
    assert [(q["result"], q["independent"]) for q in qa] == [("Conditional", False)]


def test_unexpected_error_while_saving_fails_the_job_and_keeps_the_cost(factory, team, ai, monkeypatch):
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]

    def broken(*_a, **_k):
        raise ValueError("nilai tak terduga dari model")

    monkeypatch.setattr(worker, "check_claims", broken)
    assert run_all(factory, StubProvider(cost=321)) == ["failed"]
    job = job_row(factory, job_id)
    assert (job.status, job.error_code) == ("failed", "invalid_output")  # tidak macet di running
    with factory() as s:
        assert [c.cost_micro_usd for c in s.scalars(select(AiCall).where(AiCall.job_id == job_id))] == [321]


def test_nul_characters_from_the_model_do_not_break_saving(factory, team, ai):
    req = new_request(team["staff"], client="CTHSIM")
    ask_ai(team["staff"], req["id"])

    class Nul(StubProvider):
        def generate(self, prompt):
            gen = super().generate(prompt)
            return Generation(content="Pagi\x00 tenang", claims=(ClaimOut("Sua\x00sana", "experience\x00", None),), usage=gen.usage)

    assert run_all(factory, Nul()) == ["succeeded"]
    draft = team["staff"].get("/drafts", request_id=req["id"]).json()["items"][0]
    full = team["staff"].get(f"/drafts/{draft['id']}").json()
    assert full["content"] == "Pagi tenang" and full["claims"][0]["text"] == "Suasana"


def test_job_taken_over_after_timeout_is_saved_only_once(factory, team, ai):
    """Worker lambat yang job-nya sudah diambil alih tidak boleh menyimpan draft kedua; biayanya tetap tercatat."""
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    with factory() as s:
        slow = worker.claim(s, "lambat")
    taken = {}

    class TakenOver(StubProvider):
        def generate(self, prompt):  # worker lambat masih menunggu model; job dianggap macet dan diambil worker lain
            with factory() as s:
                assert worker.reap(s, timeout_s=-1) == 1
            with factory() as s:
                taken["fast"] = worker.claim(s, "cepat")
            return super().generate(prompt)

    assert worker.process(factory, TakenOver(cost=111), slow) == "skipped"
    fast = taken["fast"]
    assert (slow.job_id, fast.job_id) == (job_id, job_id) and fast.attempts == slow.attempts + 1
    assert worker.process(factory, StubProvider(cost=222), fast) == "succeeded"
    with factory() as s:
        assert sorted(c.cost_micro_usd for c in s.scalars(select(AiCall).where(AiCall.job_id == job_id))) == [111, 222]
        assert s.scalar(select(func.count()).select_from(Draft).where(Draft.request_id == req["id"])) == 1


def test_cancelled_while_running_is_not_possible_but_closed_request_wins(factory, team, ai):
    """Pembatalan hanya untuk job antre; job yang sedang berjalan selesai atau gagal dengan kode jelas."""
    req = new_request(team["staff"], client="CTHSIM")
    job_id = ask_ai(team["staff"], req["id"]).json()["id"]
    with factory() as s:
        lease = worker.claim(s, "w")
    r = team["staff"].post(f"/ai-jobs/{job_id}/cancel", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_job_not_cancellable"
    assert worker.process(factory, FakeProvider(), lease) == "succeeded"


def test_budget_reserves_estimates_of_jobs_still_in_queue(factory, team, ai, monkeypatch):
    """Banyak job dibuat bersamaan tidak boleh melewati batas: perkiraan job yang masih antre ikut dihitung."""
    monkeypatch.setenv("CLAU_AI_JOB_ESTIMATE_MICRO_USD", "200000")
    with factory() as s:
        used = int(s.scalar(select(func.coalesce(func.sum(AiCall.cost_micro_usd), 0))))
    put_budget(team["owner"], used + 250_000)  # cukup untuk satu job, tidak untuk dua
    try:
        first = new_request(team["staff"], client="CTHSIM")
        second = new_request(team["staff"], client="CTHSIM")
        assert ask_ai(team["staff"], first["id"]).status_code == 202
        r = ask_ai(team["staff"], second["id"])
        assert r.status_code == 409 and r.json()["error"]["code"] == "ai_budget_exceeded"
        assert run_all(factory) == ["succeeded"]  # provider tiruan: biaya 0, sisa tetap cukup
        assert ask_ai(team["staff"], second["id"]).status_code == 202
        run_all(factory)
    finally:
        put_budget(team["owner"], 50_000_000)


def test_concurrent_job_creation_respects_budget(factory, team, ai, monkeypatch):
    monkeypatch.setenv("CLAU_AI_JOB_ESTIMATE_MICRO_USD", "200000")
    with factory() as s:
        used = int(s.scalar(select(func.coalesce(func.sum(AiCall.cost_micro_usd), 0))))
    put_budget(team["owner"], used + 250_000)
    reqs = [new_request(team["staff"], client="CTHSIM") for _ in range(4)]
    codes, barrier = [], threading.Barrier(len(reqs))

    def go(req):
        barrier.wait()
        codes.append(ask_ai(team["staff"], req["id"]).status_code)

    threads = [threading.Thread(target=go, args=(r,)) for r in reqs]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(codes) == [202, 409, 409, 409]
    finally:
        put_budget(team["owner"], 50_000_000)
        run_all(factory)

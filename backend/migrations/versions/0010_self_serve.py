"""Klien mandiri memakai agen sendiri (TASK-007, AI-CONSTITUTION v4.0.0 §11 langganan mandiri).

- clients.self_serve: klien dari pendaftaran mandiri. Klien lama dari pendaftaran (audit_log `signup`) ikut ditandai.
- Untuk klien self_serve, approver klien (`client_approver` klien itu) adalah pemilik usaha:
  * menyetujui draft L2/L3 tanpa claim verification independen agency: persetujuan klien di dashboard = review
    manusia untuk kanal miliknya (§11). Fakta tetap wajib dari fact sheet yang disetujui (aturan lain tidak berubah);
  * boleh memutuskan draft AI yang ia minta sendiri (pembuat draft = agen AI, bukan dia);
  * menulis Brain bisnis (fact sheet) miliknya sendiri lalu mengonfirmasi & menyetujuinya: fakta yang ditulis
    pemilik usaha = jawaban klien.
  Klien terkelola (self_serve = false) dan peran agency tidak berubah sama sekali.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

HELPERS_SQL = """
CREATE FUNCTION clau_client_self_serve(client text) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT coalesce((SELECT self_serve FROM clients WHERE client_code = $1), false)
$$;
"""

# Isi fungsi = versi terakhir (0004/0005/0006) dengan satu pengecualian {..}. Downgrade memakai teks yang sama
# dengan pengecualian `false` (perilaku persis seperti sebelum migrasi ini).
APPROVAL_RULES = """
CREATE OR REPLACE FUNCTION clau_approval_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d drafts%ROWTYPE; req requests%ROWTYPE; min_level text; missing text; last_cv text;
BEGIN
  SELECT * INTO d FROM drafts WHERE id = NEW.draft_id;
  SELECT * INTO req FROM requests WHERE id = d.request_id FOR UPDATE;
  IF NEW.mode IS DISTINCT FROM d.mode THEN
    RAISE EXCEPTION 'approval_mode_mismatch: mode approval (%) harus sama dengan mode draft (%)', NEW.mode, d.mode
      USING ERRCODE = 'check_violation';
  END IF;
  PERFORM clau_request_open(req);
  IF NOT (
       (NEW.approver_role IN ('owner', 'content_lead') AND clau_has_role(NEW.approver_id, 'agency', NEW.approver_role))
    OR (NEW.approver_role = 'client_approver' AND clau_has_role(NEW.approver_id, req.client_code, 'client_approver'))) THEN
    RAISE EXCEPTION 'approval_role_mismatch: approver tidak punya peran % untuk klien ini', NEW.approver_role
      USING ERRCODE = 'check_violation';
  END IF;
  IF d.created_by IS NOT NULL AND d.created_by = NEW.approver_id THEN
    RAISE EXCEPTION 'approval_by_author: pembuat draft tidak boleh memutuskan approval drafnya sendiri'
      USING ERRCODE = 'check_violation';
  END IF;
  min_level := clau_draft_min_level(d, req);
  IF array_position(ARRAY['L1','L2','L3'], NEW.level) < array_position(ARRAY['L1','L2','L3'], min_level) THEN
    RAISE EXCEPTION 'approval_level_too_low: draft ini butuh approval minimal %', min_level
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.decision <> 'Approved' THEN
    RETURN NEW;
  END IF;
  -- Rule 08: persetujuan selalu dari klien. Agency hanya mencatat persetujuan tertulis klien (bukti wajib).
  IF NEW.approver_role <> 'client_approver' AND coalesce(btrim(NEW.channel_ref), '') = '' THEN
    RAISE EXCEPTION 'approval_needs_written_evidence: approval oleh agency wajib bukti tertulis klien (channel_ref)'
      USING ERRCODE = 'check_violation';
  END IF;
  -- 0010: klien mandiri = persetujuan klien sendiri memenuhi review manusia (AI-CONSTITUTION §11).
  IF NEW.level IN ('L2', 'L3') AND NOT ({approval_self_serve}) THEN
    -- Yang berlaku = claim verification independen TERAKHIR (Fail setelah Pass membatalkan).
    SELECT q.result INTO last_cv FROM qa_records q
     WHERE q.draft_id = NEW.draft_id AND q.gate = 'claim-verification' AND q.independent
     ORDER BY q.created_at DESC, q.id DESC LIMIT 1;
    IF last_cv IS NULL OR last_cv NOT IN ('Pass', 'Conditional') THEN
      RAISE EXCEPTION 'approval_needs_independent_review: approval % butuh claim verification independen terakhir yang lulus', NEW.level
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM drafts WHERE request_id = d.request_id AND version > d.version) THEN
    RAISE EXCEPTION 'approval_version_mismatch: draft versi % bukan versi terbaru request ini', d.version
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT string_agg(DISTINCT c.fact_key, ', ') INTO missing
    FROM claims c
   WHERE c.draft_id = NEW.draft_id AND c.fact_key IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM fact_sheets fs JOIN fact_confirmations fc ON fc.fact_sheet_id = fs.id
        WHERE fs.id = d.fact_sheet_id AND fs.approved_at IS NOT NULL
          AND fc.fact_key = c.fact_key AND fc.decision IN ('confirmed', 'corrected'));
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'facts_unconfirmed: fakta belum dikonfirmasi di fact sheet yang disetujui: %', missing
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""

NOT_AI_REQUESTER = """
CREATE OR REPLACE FUNCTION clau_approval_not_ai_requester() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.approver_id = clau_ai_draft_requester(NEW.draft_id) AND NOT ({requester_self_serve}) THEN
    RAISE EXCEPTION 'approval_by_author: peminta draft AI tidak boleh memutuskan approval draft itu'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""

FACT_SHEET_FROZEN = """
CREATE OR REPLACE FUNCTION clau_fact_sheet_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE missing text;
BEGIN
  IF TG_OP = 'DELETE' OR OLD.approved_at IS NOT NULL THEN
    RAISE EXCEPTION 'decision_record_append_only: fact sheet versi % tidak bisa diubah atau dihapus; buat versi baru', OLD.version
      USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.id, NEW.client_code, NEW.version, NEW.document_ref, NEW.created_by, NEW.created_at)
     IS DISTINCT FROM (OLD.id, OLD.client_code, OLD.version, OLD.document_ref, OLD.created_by, OLD.created_at)
     OR NEW.approved_at IS NULL THEN
    RAISE EXCEPTION 'fact_sheet_approval_flow: fact sheet hanya bisa disetujui; isi lain = versi baru'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.approved_by IS NULL OR NOT clau_client_answer_role_ok(NEW.approved_by, NEW.client_code, NEW.approved_by_role) THEN
    RAISE EXCEPTION 'approval_role_mismatch: penyetuju tidak punya peran % untuk klien ini', NEW.approved_by_role
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.approved_by_role <> 'client_approver' AND coalesce(btrim(NEW.approval_ref), '') = '' THEN
    RAISE EXCEPTION 'approval_needs_written_evidence: persetujuan fact sheet oleh agency wajib bukti tertulis klien'
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.created_by IS NOT NULL AND OLD.created_by = NEW.approved_by AND NOT ({sheet_self_serve}) THEN
    RAISE EXCEPTION 'approval_by_author: pembuat fact sheet tidak boleh menyetujuinya'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM facts WHERE fact_sheet_id = OLD.id) THEN
    RAISE EXCEPTION 'fact_sheet_empty: fact sheet tanpa fakta tidak bisa disetujui' USING ERRCODE = 'check_violation';
  END IF;
  SELECT string_agg(f.fact_key, ', ' ORDER BY f.fact_key) INTO missing FROM facts f
   WHERE f.fact_sheet_id = OLD.id
     AND NOT EXISTS (SELECT 1 FROM fact_confirmations fc WHERE fc.fact_sheet_id = OLD.id AND fc.fact_key = f.fact_key);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'facts_unconfirmed: fakta belum dijawab klien: %', missing USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""

FACT_CONFIRMATION = """
CREATE OR REPLACE FUNCTION clau_fact_confirmation_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE sheet fact_sheets%ROWTYPE; fact_value text;
BEGIN
  SELECT * INTO sheet FROM fact_sheets WHERE id = NEW.fact_sheet_id FOR UPDATE;
  IF sheet.approved_at IS NOT NULL THEN
    RAISE EXCEPTION 'fact_sheet_frozen: fact sheet sudah disetujui; buat versi baru' USING ERRCODE = 'check_violation';
  END IF;
  SELECT value INTO fact_value FROM facts WHERE fact_sheet_id = NEW.fact_sheet_id AND fact_key = NEW.fact_key;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'fact_not_in_sheet: fakta % tidak ada di fact sheet ini', NEW.fact_key USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.confirmed_by_role IS NULL OR NOT clau_client_answer_role_ok(NEW.confirmed_by, sheet.client_code, NEW.confirmed_by_role) THEN
    RAISE EXCEPTION 'approval_role_mismatch: pengonfirmasi tidak punya peran % untuk klien ini', NEW.confirmed_by_role
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.confirmed_by_role <> 'client_approver' AND coalesce(btrim(NEW.channel_ref), '') = '' THEN
    RAISE EXCEPTION 'approval_needs_written_evidence: konfirmasi fakta oleh agency wajib bukti tertulis klien'
      USING ERRCODE = 'check_violation';
  END IF;
  IF sheet.created_by IS NOT NULL AND sheet.created_by = NEW.confirmed_by AND NOT ({confirm_self_serve}) THEN
    RAISE EXCEPTION 'approval_by_author: pembuat fact sheet tidak boleh mengonfirmasi faktanya'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.decision = 'corrected' AND coalesce(btrim(NEW.value_after), '') = '' THEN
    RAISE EXCEPTION 'fact_value_required: koreksi wajib berisi nilai yang benar' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.decision = 'corrected' AND btrim(NEW.value_after) = btrim(fact_value) THEN
    RAISE EXCEPTION 'fact_value_unchanged: koreksi sama dengan nilai awal; pilih "benar" bila nilainya sudah tepat'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.decision = 'confirmed' THEN
    NEW.value_after := NULL;
  END IF;
  NEW.value_before := fact_value;
  RETURN NEW;
END $$;
"""

# Peran sudah dicek di fungsi masing-masing sebelum pengecualian ini (approval_role_mismatch).
SELF_SERVE = {
    "approval_self_serve": "NEW.approver_role = 'client_approver' AND clau_client_self_serve(req.client_code)",
    "requester_self_serve": (
        "NEW.approver_role = 'client_approver' AND clau_client_self_serve("
        "(SELECT r.client_code FROM drafts dr JOIN requests r ON r.id = dr.request_id WHERE dr.id = NEW.draft_id))"
    ),
    "sheet_self_serve": "NEW.approved_by_role = 'client_approver' AND clau_client_self_serve(NEW.client_code)",
    "confirm_self_serve": "NEW.confirmed_by_role = 'client_approver' AND clau_client_self_serve(sheet.client_code)",
}
LEGACY = {k: "false" for k in SELF_SERVE}


def functions_sql(values: dict[str, str]) -> str:
    sql = APPROVAL_RULES + NOT_AI_REQUESTER + FACT_SHEET_FROZEN + FACT_CONFIRMATION
    for key, value in values.items():
        assert sql.count("{" + key + "}") == 1, key
        sql = sql.replace("{" + key + "}", value)
    return sql


def upgrade() -> None:
    op.add_column('clients', sa.Column('self_serve', sa.Boolean(), server_default='false', nullable=False))
    op.execute(
        "UPDATE clients SET self_serve = true WHERE client_code IN "
        "(SELECT meta->>'client_code' FROM audit_log WHERE action = 'signup' AND meta ? 'client_code')"
    )
    op.execute(HELPERS_SQL)
    op.execute(functions_sql(SELF_SERVE))


def downgrade() -> None:
    op.execute(functions_sql(LEGACY))
    op.execute("DROP FUNCTION IF EXISTS clau_client_self_serve(text)")
    op.drop_column('clients', 'self_serve')

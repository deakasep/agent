"""Error berbentuk kontrak {"error": {"code", "message"}} (core/shared/api-contracts.md)."""

from __future__ import annotations

import re

# Kode aturan dari trigger database (migrasi 0001, 0004–0008) yang boleh diteruskan ke klien apa adanya.
DB_RULE_RE = re.compile(r"\b([a-z]+(?:_[a-z]+)+): ")
DB_RULES = {
    "qa_reviewer_is_author",
    "approval_mode_mismatch",
    "approval_needs_independent_review",
    "publication_without_approval",
    "draft_version_immutable",
    "audit_log_append_only",
    # Migrasi 0004 (workflow, kontrak core 0.7.0).
    "facts_unconfirmed",
    "approval_version_mismatch",
    "approval_level_too_low",
    "approval_by_author",
    "approval_needs_written_evidence",
    "draft_client_mismatch",
    "draft_mode_mismatch",
    "draft_version_sequence",
    "decision_record_append_only",
    "request_closed",
    "approval_role_mismatch",
    "qa_role_mismatch",
    "independent_review_not_allowed",
    # Migrasi 0005 (fact sheet & konfirmasi fakta, kontrak core 0.8.0).
    "fact_sheet_approval_flow",
    "fact_sheet_version_sequence",
    "fact_sheet_empty",
    "fact_sheet_frozen",
    "fact_not_in_sheet",
    "fact_value_required",
    "fact_value_unchanged",
    "fact_sheet_superseded",
    # Migrasi 0006 (antrean AI Tahap 2, kontrak core 0.9.0).
    "ai_job_transition",
    "ai_job_draft_mismatch",
    "ai_record_append_only",
    "ai_draft_without_job",
    # Migrasi 0007 (penanda isi konten, kontrak core 0.10.0).
    "review_rating_required",
    "source_draft_required",
    "source_draft_invalid",
    "flag_not_removable",
    # Migrasi 0008 (langganan & kredit, kontrak core 0.11.0).
    "payment_transition",
    "subscription_payment_mismatch",
    "credit_entry_invalid",
    "credit_insufficient",
    "billing_record_append_only",
}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


# CHECK constraint / indeks unik yang punya arti bagi pengguna (nama dari models.py) -> kode kontrak.
DB_CHECKS = {
    "ck_approvals_simulasi_not_approved": "simulasi_not_approved",
    "ck_claims_fact_key_required": "claim_fact_key_required",
    "ck_claims_data_final_sourced": "claim_source_required",
    "uq_ai_jobs_one_active": "ai_job_active",
    "uq_draft_flags_active": "flag_exists",
    "uq_credit_ledger_monthly": "credit_entry_invalid",
    "uq_credit_ledger_topup": "credit_entry_invalid",
    "uq_credit_ledger_job": "credit_entry_invalid",
    "uq_subscriptions_payment_id": "subscription_payment_mismatch",
}


def db_rule_code(message: str, constraint: str | None = None) -> str:
    """Pelanggaran aturan database -> kode aman untuk klien (tanpa nama tabel/kolom/nilai)."""
    if constraint in DB_CHECKS:
        return DB_CHECKS[constraint]
    m = DB_RULE_RE.search(message)
    return m.group(1) if m and m.group(1) in DB_RULES else "constraint_violation"

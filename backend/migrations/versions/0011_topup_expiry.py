"""Kredit top up hangus 12 bulan setelah lunas (kontrak core 0.14.0; clau-market pricing.md §2; model kredit Sintra.ai).

- credit_ledger.reason baru `topup_expire`: menghapus sisa satu top up yang sudah lewat `expires_at`. Trigger
  clau_credit_rules (versi 0008 + satu cabang): bucket `topup`, delta negatif, wajib `payment_id` top up klien itu yang
  sudah kedaluwarsa (`expires_at` <= now()), tidak lebih dari kredit top up itu.
- Indeks unik uq_credit_ledger_topup_expire: satu hangus per tagihan (tidak ada hangus ganda).
- Pembagian pemakaian ke top up (paling cepat kedaluwarsa dulu) dihitung aplikasi (app/billing/topup_expiry.py);
  database tetap menolak saldo negatif (credit_insufficient) dan hangus sebelum waktunya.

Downgrade gagal bila sudah ada baris `topup_expire` (buku kredit append-only), sengaja: riwayat hangus tidak dihapus.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-30
"""

from __future__ import annotations

from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

REASONS_0008 = "'monthly_grant', 'monthly_expire', 'topup', 'usage', 'refund', 'adjustment'"
REASONS_0011 = "'monthly_grant', 'monthly_expire', 'topup', 'topup_expire', 'usage', 'refund', 'adjustment'"

CREDIT_RULES_0011 = r"""
CREATE OR REPLACE FUNCTION clau_credit_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bal bigint; owner_code text; p record; j record; t record; used integer;
BEGIN
  -- Satu penulis per klien: cek saldo & aturan di bawah tidak bisa balapan.
  PERFORM pg_advisory_xact_lock(hashtext('clau_credit:' || NEW.client_code));
  IF NEW.reason IN ('monthly_grant', 'monthly_expire') THEN
    IF NEW.bucket <> 'monthly' OR NEW.subscription_id IS NULL OR NEW.period_start IS NULL
       OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL
       OR (NEW.reason = 'monthly_grant' AND NEW.delta < 0) OR (NEW.reason = 'monthly_expire' AND NEW.delta > 0) THEN
      RAISE EXCEPTION 'credit_entry_invalid: kredit bulanan tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT client_code INTO owner_code FROM subscriptions WHERE id = NEW.subscription_id;
    IF owner_code IS DISTINCT FROM NEW.client_code THEN
      RAISE EXCEPTION 'credit_entry_invalid: langganan milik klien lain' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.reason = 'topup' THEN
    IF NEW.bucket <> 'topup' OR NEW.payment_id IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.ai_job_id IS NOT NULL OR NEW.delta < 0 THEN
      RAISE EXCEPTION 'credit_entry_invalid: top up tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT status, kind, client_code, credits INTO p FROM payments WHERE id = NEW.payment_id;
    IF p.status IS DISTINCT FROM 'paid' OR p.kind IS DISTINCT FROM 'topup'
       OR p.client_code IS DISTINCT FROM NEW.client_code OR p.credits IS DISTINCT FROM NEW.delta THEN
      RAISE EXCEPTION 'credit_entry_invalid: top up hanya dari tagihan top up yang lunas' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.reason = 'topup_expire' THEN
    -- 0011: sisa top up hangus 12 bulan setelah lunas (pricing.md §2). Hanya untuk top up klien itu yang sudah lewat
    -- expires_at, tidak lebih dari kreditnya, satu kali per tagihan (indeks unik uq_credit_ledger_topup_expire).
    IF NEW.bucket <> 'topup' OR NEW.payment_id IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.ai_job_id IS NOT NULL OR NEW.delta > 0 THEN
      RAISE EXCEPTION 'credit_entry_invalid: hangus top up tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT client_code, delta, expires_at INTO t FROM credit_ledger WHERE payment_id = NEW.payment_id AND reason = 'topup';
    IF t.client_code IS DISTINCT FROM NEW.client_code OR t.expires_at IS NULL OR t.expires_at > now() OR -NEW.delta > t.delta THEN
      RAISE EXCEPTION 'credit_entry_invalid: top up belum kedaluwarsa atau bukan milik klien ini' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.reason IN ('usage', 'refund') THEN
    IF NEW.ai_job_id IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL OR NEW.payment_id IS NOT NULL
       OR (NEW.reason = 'usage' AND NEW.delta > 0) OR (NEW.reason = 'refund' AND NEW.delta < 0) THEN
      RAISE EXCEPTION 'credit_entry_invalid: pemakaian/refund tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT jb.status, r.client_code INTO j FROM ai_jobs jb JOIN requests r ON r.id = jb.request_id WHERE jb.id = NEW.ai_job_id;
    IF j.client_code IS DISTINCT FROM NEW.client_code THEN
      RAISE EXCEPTION 'credit_entry_invalid: job AI milik klien lain' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.reason = 'usage' AND j.status IS DISTINCT FROM 'queued' THEN
      RAISE EXCEPTION 'credit_entry_invalid: kredit dipotong saat job dibuat' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.reason = 'refund' THEN
      IF j.status NOT IN ('failed', 'cancelled') THEN
        RAISE EXCEPTION 'credit_entry_invalid: refund hanya untuk job gagal/dibatalkan' USING ERRCODE = 'check_violation';
      END IF;
      SELECT delta INTO used FROM credit_ledger WHERE ai_job_id = NEW.ai_job_id AND bucket = NEW.bucket AND reason = 'usage';
      IF used IS NULL OR NEW.delta <> -used THEN
        RAISE EXCEPTION 'credit_entry_invalid: refund harus sama dengan pemakaian' USING ERRCODE = 'check_violation';
      END IF;
    END IF;
  ELSE  -- adjustment oleh owner
    IF NEW.created_by IS NULL OR NEW.note IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL THEN
      RAISE EXCEPTION 'credit_entry_invalid: penyesuaian wajib pembuat dan catatan' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  SELECT coalesce(sum(delta), 0) INTO bal FROM credit_ledger WHERE client_code = NEW.client_code AND bucket = NEW.bucket;
  IF bal + NEW.delta < 0 THEN
    RAISE EXCEPTION 'credit_insufficient: saldo kredit tidak cukup' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""

CREDIT_RULES_0008 = r"""
CREATE OR REPLACE FUNCTION clau_credit_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bal bigint; owner_code text; p record; j record; used integer;
BEGIN
  -- Satu penulis per klien: cek saldo & aturan di bawah tidak bisa balapan.
  PERFORM pg_advisory_xact_lock(hashtext('clau_credit:' || NEW.client_code));
  IF NEW.reason IN ('monthly_grant', 'monthly_expire') THEN
    IF NEW.bucket <> 'monthly' OR NEW.subscription_id IS NULL OR NEW.period_start IS NULL
       OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL
       OR (NEW.reason = 'monthly_grant' AND NEW.delta < 0) OR (NEW.reason = 'monthly_expire' AND NEW.delta > 0) THEN
      RAISE EXCEPTION 'credit_entry_invalid: kredit bulanan tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT client_code INTO owner_code FROM subscriptions WHERE id = NEW.subscription_id;
    IF owner_code IS DISTINCT FROM NEW.client_code THEN
      RAISE EXCEPTION 'credit_entry_invalid: langganan milik klien lain' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.reason = 'topup' THEN
    IF NEW.bucket <> 'topup' OR NEW.payment_id IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.ai_job_id IS NOT NULL OR NEW.delta < 0 THEN
      RAISE EXCEPTION 'credit_entry_invalid: top up tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT status, kind, client_code, credits INTO p FROM payments WHERE id = NEW.payment_id;
    IF p.status IS DISTINCT FROM 'paid' OR p.kind IS DISTINCT FROM 'topup'
       OR p.client_code IS DISTINCT FROM NEW.client_code OR p.credits IS DISTINCT FROM NEW.delta THEN
      RAISE EXCEPTION 'credit_entry_invalid: top up hanya dari tagihan top up yang lunas' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.reason IN ('usage', 'refund') THEN
    IF NEW.ai_job_id IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL OR NEW.payment_id IS NOT NULL
       OR (NEW.reason = 'usage' AND NEW.delta > 0) OR (NEW.reason = 'refund' AND NEW.delta < 0) THEN
      RAISE EXCEPTION 'credit_entry_invalid: pemakaian/refund tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT jb.status, r.client_code INTO j FROM ai_jobs jb JOIN requests r ON r.id = jb.request_id WHERE jb.id = NEW.ai_job_id;
    IF j.client_code IS DISTINCT FROM NEW.client_code THEN
      RAISE EXCEPTION 'credit_entry_invalid: job AI milik klien lain' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.reason = 'usage' AND j.status IS DISTINCT FROM 'queued' THEN
      RAISE EXCEPTION 'credit_entry_invalid: kredit dipotong saat job dibuat' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.reason = 'refund' THEN
      IF j.status NOT IN ('failed', 'cancelled') THEN
        RAISE EXCEPTION 'credit_entry_invalid: refund hanya untuk job gagal/dibatalkan' USING ERRCODE = 'check_violation';
      END IF;
      SELECT delta INTO used FROM credit_ledger WHERE ai_job_id = NEW.ai_job_id AND bucket = NEW.bucket AND reason = 'usage';
      IF used IS NULL OR NEW.delta <> -used THEN
        RAISE EXCEPTION 'credit_entry_invalid: refund harus sama dengan pemakaian' USING ERRCODE = 'check_violation';
      END IF;
    END IF;
  ELSE  -- adjustment oleh owner
    IF NEW.created_by IS NULL OR NEW.note IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL THEN
      RAISE EXCEPTION 'credit_entry_invalid: penyesuaian wajib pembuat dan catatan' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  SELECT coalesce(sum(delta), 0) INTO bal FROM credit_ledger WHERE client_code = NEW.client_code AND bucket = NEW.bucket;
  IF bal + NEW.delta < 0 THEN
    RAISE EXCEPTION 'credit_insufficient: saldo kredit tidak cukup' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE credit_ledger DROP CONSTRAINT ck_credit_ledger_reason")
    op.execute(f"ALTER TABLE credit_ledger ADD CONSTRAINT ck_credit_ledger_reason CHECK (reason IN ({REASONS_0011}))")
    op.execute("CREATE UNIQUE INDEX uq_credit_ledger_topup_expire ON credit_ledger (payment_id) WHERE reason = 'topup_expire'")
    op.execute(CREDIT_RULES_0011)


def downgrade() -> None:
    op.execute(CREDIT_RULES_0008)
    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_topup_expire")
    op.execute("ALTER TABLE credit_ledger DROP CONSTRAINT ck_credit_ledger_reason")
    op.execute(f"ALTER TABLE credit_ledger ADD CONSTRAINT ck_credit_ledger_reason CHECK (reason IN ({REASONS_0008}))")

"""Kredit percobaan: 50 kredit, berlaku 3 hari, sekali per klien (kontrak core 0.15.0; clau-market pricing.md v1.3.0 §2a;
perintah owner Dea Karisna 2026-11-02, seperti trial Sintra.ai).

- credit_ledger.bucket baru `trial`; reason baru `trial_grant` (positif, wajib `expires_at`, bukan klien SIMULASI,
  satu per klien lewat indeks unik uq_credit_ledger_trial) dan `trial_expire` (negatif, hanya setelah `expires_at`
  hibah klien itu; boleh lebih dari sekali karena refund job ke `trial` setelah hangus ikut dihanguskan).
- `usage` dari bucket `trial` hanya selama masa berlaku; `adjustment` owner tidak boleh ke `trial`.
- Trigger clau_credit_rules = versi 0011 + cabang di atas. Urutan pemakaian (trial → bulanan → top up) dihitung
  aplikasi (app/billing/ledger.py); saldo per bucket tetap tidak boleh negatif (credit_insufficient).

Downgrade gagal bila sudah ada baris `trial` (buku kredit append-only), sengaja: riwayat kredit tidak dihapus.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-02
"""

from __future__ import annotations

from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

BUCKETS_0008 = "'monthly', 'topup'"
BUCKETS_0012 = "'monthly', 'topup', 'trial'"
REASONS_0011 = "'monthly_grant', 'monthly_expire', 'topup', 'topup_expire', 'usage', 'refund', 'adjustment'"
REASONS_0012 = "'monthly_grant', 'monthly_expire', 'topup', 'topup_expire', 'trial_grant', 'trial_expire', 'usage', 'refund', 'adjustment'"

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

CREDIT_RULES_0012 = r"""
CREATE OR REPLACE FUNCTION clau_credit_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bal bigint; owner_code text; p record; j record; t record; used integer; trial_end timestamptz; sim boolean;
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
  ELSIF NEW.reason = 'trial_grant' THEN
    -- 0012: kredit percobaan (pricing.md §2a). Satu per klien (indeks unik uq_credit_ledger_trial), wajib masa berlaku,
    -- bukan klien SIMULASI, tanpa rujukan lain.
    IF NEW.bucket <> 'trial' OR NEW.delta < 0 OR NEW.expires_at IS NULL OR NEW.subscription_id IS NOT NULL
       OR NEW.period_start IS NOT NULL OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL THEN
      RAISE EXCEPTION 'credit_entry_invalid: kredit percobaan tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT simulation INTO sim FROM clients WHERE client_code = NEW.client_code;
    IF sim IS DISTINCT FROM false THEN
      RAISE EXCEPTION 'credit_entry_invalid: klien SIMULASI tidak mendapat kredit percobaan' USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.reason = 'trial_expire' THEN
    -- 0012: sisa kredit percobaan hangus setelah masa berlakunya (boleh lebih dari sekali: refund job setelah hangus).
    IF NEW.bucket <> 'trial' OR NEW.delta > 0 OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL THEN
      RAISE EXCEPTION 'credit_entry_invalid: hangus kredit percobaan tidak sesuai aturan' USING ERRCODE = 'check_violation';
    END IF;
    SELECT expires_at INTO trial_end FROM credit_ledger WHERE client_code = NEW.client_code AND reason = 'trial_grant';
    IF trial_end IS NULL OR trial_end > now() THEN
      RAISE EXCEPTION 'credit_entry_invalid: kredit percobaan belum kedaluwarsa' USING ERRCODE = 'check_violation';
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
    IF NEW.reason = 'usage' AND NEW.bucket = 'trial' THEN
      -- 0012: kredit percobaan hanya bisa dipakai selama masa berlaku.
      SELECT expires_at INTO trial_end FROM credit_ledger WHERE client_code = NEW.client_code AND reason = 'trial_grant';
      IF trial_end IS NULL OR trial_end <= now() THEN
        RAISE EXCEPTION 'credit_entry_invalid: kredit percobaan sudah kedaluwarsa' USING ERRCODE = 'check_violation';
      END IF;
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
  ELSE  -- adjustment oleh owner (0012: tidak ke kredit percobaan)
    IF NEW.created_by IS NULL OR NEW.note IS NULL OR NEW.subscription_id IS NOT NULL OR NEW.period_start IS NOT NULL
       OR NEW.payment_id IS NOT NULL OR NEW.ai_job_id IS NOT NULL OR NEW.bucket = 'trial' THEN
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
    op.execute("ALTER TABLE credit_ledger DROP CONSTRAINT ck_credit_ledger_bucket")
    op.execute(f"ALTER TABLE credit_ledger ADD CONSTRAINT ck_credit_ledger_bucket CHECK (bucket IN ({BUCKETS_0012}))")
    op.execute("ALTER TABLE credit_ledger DROP CONSTRAINT ck_credit_ledger_reason")
    op.execute(f"ALTER TABLE credit_ledger ADD CONSTRAINT ck_credit_ledger_reason CHECK (reason IN ({REASONS_0012}))")
    op.execute("CREATE UNIQUE INDEX uq_credit_ledger_trial ON credit_ledger (client_code) WHERE reason = 'trial_grant'")
    op.execute(CREDIT_RULES_0012)


def downgrade() -> None:
    op.execute(CREDIT_RULES_0011)
    op.execute("DROP INDEX IF EXISTS uq_credit_ledger_trial")
    op.execute("ALTER TABLE credit_ledger DROP CONSTRAINT ck_credit_ledger_reason")
    op.execute(f"ALTER TABLE credit_ledger ADD CONSTRAINT ck_credit_ledger_reason CHECK (reason IN ({REASONS_0011}))")
    op.execute("ALTER TABLE credit_ledger DROP CONSTRAINT ck_credit_ledger_bucket")
    op.execute(f"ALTER TABLE credit_ledger ADD CONSTRAINT ck_credit_ledger_bucket CHECK (bucket IN ({BUCKETS_0008}))")

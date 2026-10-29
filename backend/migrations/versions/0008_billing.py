"""Langganan & kredit: payments, subscriptions, credit_ledger (kontrak core 0.11.0, AI-CONSTITUTION v4.0.0 §4b,
AI-BOUNDARY 2.0.0 § Token Kanal & Pembayaran).

Aturan (pesan berawalan kode aturan, SQLSTATE 23514, seperti 0001/0004–0007):
- payment_transition: tagihan baru selalu `pending`; transisi hanya pending → paid/expired/failed; tagihan selesai
  beku; kolom identitas (klien, jenis, paket, kredit, nominal, provider, order_id, peminta) tidak bisa diubah.
- subscription_payment_mismatch: langganan hanya dari pembayaran `paid` berjenis `subscription` untuk klien & paket
  yang sama (satu langganan per pembayaran, indeks unik).
- credit_entry_invalid: tanda delta & rujukan wajib per reason (lihat kontrak); `topup` = kredit tagihan lunas klien
  itu; `usage` hanya untuk job AI klien itu yang baru dibuat (`queued`); `refund` hanya untuk job `failed`/`cancelled`
  dan persis sebesar pemakaiannya; indeks unik mencegah hibah bulanan, top up, pemakaian, dan refund ganda.
- credit_insufficient: saldo bucket tidak boleh negatif setelah baris masuk (dikunci per klien, aman dari balapan).
- billing_record_append_only: credit_ledger & subscriptions tidak diubah/dihapus, payments tidak dihapus (hak ubah
  juga dicabut dari role aplikasi, seperti audit_log / ai_calls).
- Refund otomatis: job AI yang berubah ke `failed`/`cancelled` mengembalikan seluruh kredit pemakaiannya (trigger),
  jadi semua jalur gagal (endpoint batal, worker, reaper, tombol mati) tercakup tanpa kode tambahan.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

RULES_SQL = r"""
CREATE FUNCTION clau_billing_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'billing_record_append_only: catatan tagihan & kredit tidak bisa diubah atau dihapus'
    USING ERRCODE = 'check_violation';
END $$;

CREATE FUNCTION clau_payment_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'billing_record_append_only: tagihan tidak bisa dihapus' USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.paid_at IS NOT NULL THEN
      RAISE EXCEPTION 'payment_transition: tagihan baru harus pending' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status <> 'pending' THEN
    RAISE EXCEPTION 'payment_transition: tagihan yang sudah selesai tidak bisa diubah' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status NOT IN ('paid', 'expired', 'failed') THEN
    RAISE EXCEPTION 'payment_transition: pending -> % tidak diizinkan', NEW.status USING ERRCODE = 'check_violation';
  END IF;
  IF (NEW.client_code, NEW.kind, NEW.plan_months, NEW.credits, NEW.amount_idr, NEW.provider, NEW.order_id, NEW.requested_by, NEW.created_at)
     IS DISTINCT FROM
     (OLD.client_code, OLD.kind, OLD.plan_months, OLD.credits, OLD.amount_idr, OLD.provider, OLD.order_id, OLD.requested_by, OLD.created_at) THEN
    RAISE EXCEPTION 'payment_transition: identitas tagihan tidak bisa diubah' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_payments_rules BEFORE INSERT OR UPDATE OR DELETE ON payments
  FOR EACH ROW EXECUTE FUNCTION clau_payment_rules();
CREATE TRIGGER trg_payments_no_truncate BEFORE TRUNCATE ON payments
  FOR EACH STATEMENT EXECUTE FUNCTION clau_billing_append_only();

CREATE FUNCTION clau_subscription_rules() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p record;
BEGIN
  SELECT status, kind, client_code, plan_months INTO p FROM payments WHERE id = NEW.payment_id;
  IF p.status IS DISTINCT FROM 'paid' OR p.kind IS DISTINCT FROM 'subscription'
     OR p.client_code IS DISTINCT FROM NEW.client_code OR p.plan_months IS DISTINCT FROM NEW.plan_months THEN
    RAISE EXCEPTION 'subscription_payment_mismatch: langganan hanya dari pembayaran paket yang lunas'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_subscriptions_rules BEFORE INSERT ON subscriptions
  FOR EACH ROW EXECUTE FUNCTION clau_subscription_rules();
CREATE TRIGGER trg_subscriptions_append_only BEFORE UPDATE OR DELETE ON subscriptions
  FOR EACH ROW EXECUTE FUNCTION clau_billing_append_only();
CREATE TRIGGER trg_subscriptions_no_truncate BEFORE TRUNCATE ON subscriptions
  FOR EACH STATEMENT EXECUTE FUNCTION clau_billing_append_only();

CREATE FUNCTION clau_credit_rules() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER trg_credit_ledger_rules BEFORE INSERT ON credit_ledger
  FOR EACH ROW EXECUTE FUNCTION clau_credit_rules();
CREATE TRIGGER trg_credit_ledger_append_only BEFORE UPDATE OR DELETE ON credit_ledger
  FOR EACH ROW EXECUTE FUNCTION clau_billing_append_only();
CREATE TRIGGER trg_credit_ledger_no_truncate BEFORE TRUNCATE ON credit_ledger
  FOR EACH STATEMENT EXECUTE FUNCTION clau_billing_append_only();

-- Job AI gagal/dibatalkan → kredit pemakaiannya kembali penuh (semua jalur: endpoint, worker, reaper, tombol mati).
CREATE FUNCTION clau_ai_job_refund() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IN ('failed', 'cancelled') AND OLD.status IS DISTINCT FROM NEW.status THEN
    INSERT INTO credit_ledger (client_code, delta, bucket, reason, ai_job_id)
    SELECT u.client_code, -u.delta, u.bucket, 'refund', u.ai_job_id
      FROM credit_ledger u WHERE u.ai_job_id = NEW.id AND u.reason = 'usage';
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER trg_ai_jobs_refund AFTER UPDATE OF status ON ai_jobs
  FOR EACH ROW EXECUTE FUNCTION clau_ai_job_refund();

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT DISTINCT grantee, table_name FROM information_schema.role_table_grants
           WHERE table_schema = 'public' AND table_name IN ('credit_ledger', 'subscriptions')
             AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE') AND grantee <> current_user
  LOOP
    EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %I FROM %I', r.table_name, r.grantee);
  END LOOP;
  FOR r IN SELECT DISTINCT grantee FROM information_schema.role_table_grants
           WHERE table_schema = 'public' AND table_name = 'payments'
             AND privilege_type IN ('DELETE', 'TRUNCATE') AND grantee <> current_user
  LOOP
    EXECUTE format('REVOKE DELETE, TRUNCATE ON payments FROM %I', r.grantee);
  END LOOP;
END $$;
"""

DOWN_SQL = """
DROP TRIGGER IF EXISTS trg_ai_jobs_refund ON ai_jobs;
DROP FUNCTION IF EXISTS clau_ai_job_refund();
DROP FUNCTION IF EXISTS clau_credit_rules() CASCADE;
DROP FUNCTION IF EXISTS clau_subscription_rules() CASCADE;
DROP FUNCTION IF EXISTS clau_payment_rules() CASCADE;
DROP FUNCTION IF EXISTS clau_billing_append_only() CASCADE;
"""


def upgrade() -> None:
    op.create_table(
        'payments',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('client_code', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('plan_months', sa.SmallInteger(), nullable=True),
        sa.Column('credits', sa.Integer(), nullable=True),
        sa.Column('amount_idr', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('order_id', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('method', sa.Text(), nullable=True),
        sa.Column('requested_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('subscription', 'topup')", name=op.f('ck_payments_kind')),
        sa.CheckConstraint("status IN ('pending', 'paid', 'expired', 'failed')", name=op.f('ck_payments_status')),
        sa.CheckConstraint("provider IN ('fake', 'midtrans')", name=op.f('ck_payments_provider')),
        sa.CheckConstraint(
            "(kind = 'subscription' AND plan_months IN (1, 3, 6, 12) AND credits IS NULL)"
            " OR (kind = 'topup' AND plan_months IS NULL AND credits BETWEEN 1 AND 1000000)",
            name=op.f('ck_payments_kind_fields')),
        sa.CheckConstraint("amount_idr BETWEEN 1000 AND 1000000000", name=op.f('ck_payments_amount_range')),
        sa.CheckConstraint("(status = 'paid') = (paid_at IS NOT NULL)", name=op.f('ck_payments_paid_at')),
        sa.CheckConstraint("order_id ~ '^CLAU-[A-Z0-9]{2,12}-[0-9]+-[a-z0-9]{6,16}$'", name=op.f('ck_payments_order_id_format')),
        sa.CheckConstraint("method IS NULL OR char_length(method) <= 40", name=op.f('ck_payments_method_length')),
        sa.ForeignKeyConstraint(['client_code'], ['clients.client_code'], name=op.f('fk_payments_client_code_clients')),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_payments_requested_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
        sa.UniqueConstraint('order_id', name=op.f('uq_payments_order_id')),
    )
    op.create_index(op.f('ix_payments_client_code'), 'payments', ['client_code'])

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('client_code', sa.Text(), nullable=False),
        sa.Column('payment_id', sa.BigInteger(), nullable=False),
        sa.Column('plan_months', sa.SmallInteger(), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("plan_months IN (1, 3, 6, 12)", name=op.f('ck_subscriptions_plan_months')),
        sa.CheckConstraint("ends_at > starts_at", name=op.f('ck_subscriptions_period')),
        sa.ForeignKeyConstraint(['client_code'], ['clients.client_code'], name=op.f('fk_subscriptions_client_code_clients')),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_subscriptions_payment_id_payments')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
        sa.UniqueConstraint('payment_id', name=op.f('uq_subscriptions_payment_id')),
    )
    op.create_index(op.f('ix_subscriptions_client_code'), 'subscriptions', ['client_code'])

    op.create_table(
        'credit_ledger',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('client_code', sa.Text(), nullable=False),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('bucket', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('subscription_id', sa.BigInteger(), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('payment_id', sa.BigInteger(), nullable=True),
        sa.Column('ai_job_id', sa.BigInteger(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("bucket IN ('monthly', 'topup')", name=op.f('ck_credit_ledger_bucket')),
        sa.CheckConstraint(
            "reason IN ('monthly_grant', 'monthly_expire', 'topup', 'usage', 'refund', 'adjustment')",
            name=op.f('ck_credit_ledger_reason')),
        sa.CheckConstraint("delta <> 0 AND delta BETWEEN -1000000 AND 1000000", name=op.f('ck_credit_ledger_delta_range')),
        sa.CheckConstraint("note IS NULL OR char_length(note) BETWEEN 3 AND 300", name=op.f('ck_credit_ledger_note_length')),
        sa.ForeignKeyConstraint(['client_code'], ['clients.client_code'], name=op.f('fk_credit_ledger_client_code_clients')),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], name=op.f('fk_credit_ledger_subscription_id_subscriptions')),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_credit_ledger_payment_id_payments')),
        sa.ForeignKeyConstraint(['ai_job_id'], ['ai_jobs.id'], name=op.f('fk_credit_ledger_ai_job_id_ai_jobs')),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_credit_ledger_created_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_ledger')),
    )
    op.create_index(op.f('ix_credit_ledger_client_code'), 'credit_ledger', ['client_code'])
    op.create_index('ix_credit_ledger_created_at', 'credit_ledger', ['created_at'])
    op.create_index('uq_credit_ledger_monthly', 'credit_ledger', ['subscription_id', 'period_start', 'reason'], unique=True,
                    postgresql_where=sa.text("reason IN ('monthly_grant', 'monthly_expire')"))
    op.create_index('uq_credit_ledger_topup', 'credit_ledger', ['payment_id'], unique=True,
                    postgresql_where=sa.text("reason = 'topup'"))
    op.create_index('uq_credit_ledger_job', 'credit_ledger', ['ai_job_id', 'bucket', 'reason'], unique=True,
                    postgresql_where=sa.text("ai_job_id IS NOT NULL"))
    op.execute(RULES_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
    op.drop_index('uq_credit_ledger_job', table_name='credit_ledger')
    op.drop_index('uq_credit_ledger_topup', table_name='credit_ledger')
    op.drop_index('uq_credit_ledger_monthly', table_name='credit_ledger')
    op.drop_index('ix_credit_ledger_created_at', table_name='credit_ledger')
    op.drop_index(op.f('ix_credit_ledger_client_code'), table_name='credit_ledger')
    op.drop_table('credit_ledger')
    op.drop_index(op.f('ix_subscriptions_client_code'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_payments_client_code'), table_name='payments')
    op.drop_table('payments')

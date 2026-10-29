"""Pendaftaran mandiri (TASK-003, AI-CONSTITUTION v4.0.0 § 2 model langganan mandiri).

- users.email_verified_at: null = akun daftar mandiri yang emailnya belum diverifikasi (login ditolak). Akun yang
  sudah ada dan akun buatan owner/CLI terisi otomatis (server default now()).
- email_tokens: token sekali pakai untuk tautan verifikasi email & reset password; hanya SHA-256 yang disimpan.
  Role aplikasi tidak bisa menghapus baris (jejak tetap ada); token dipakai = used_at diisi.
- clients.vertical: tambah UMKM umum (`retail`, `services`, `other`).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

OLD_VERTICALS = ("accommodation", "food-beverage", "spa-wellness", "experience", "wedding-event", "travel-tour")
NEW_VERTICALS = OLD_VERTICALS + ("retail", "services", "other")


def vertical_check(values: tuple[str, ...]) -> str:
    return "vertical IN (" + ", ".join(f"'{v}'" for v in values) + ")"


REVOKE_SQL = """
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT DISTINCT grantee FROM information_schema.role_table_grants
           WHERE table_schema = 'public' AND table_name = 'email_tokens'
             AND privilege_type IN ('DELETE', 'TRUNCATE') AND grantee <> current_user
  LOOP
    EXECUTE format('REVOKE DELETE, TRUNCATE ON email_tokens FROM %I', r.grantee);
  END LOOP;
END $$;
"""


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))
    op.create_table(
        'email_tokens',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('purpose', sa.Text(), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('verify_email', 'reset_password')", name=op.f('ck_email_tokens_purpose')),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_email_tokens_token_hash_sha256')),
        sa.CheckConstraint('expires_at > created_at', name=op.f('ck_email_tokens_expires_after_created')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_tokens_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_tokens')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_email_tokens_token_hash')),
    )
    op.create_index(op.f('ix_email_tokens_user_id'), 'email_tokens', ['user_id'])
    op.drop_constraint(op.f('ck_clients_vertical'), 'clients', type_='check')
    op.create_check_constraint(op.f('ck_clients_vertical'), 'clients', vertical_check(NEW_VERTICALS))
    op.execute(REVOKE_SQL)


def downgrade() -> None:
    op.drop_constraint(op.f('ck_clients_vertical'), 'clients', type_='check')
    op.create_check_constraint(op.f('ck_clients_vertical'), 'clients', vertical_check(OLD_VERTICALS))
    op.drop_index(op.f('ix_email_tokens_user_id'), table_name='email_tokens')
    op.drop_table('email_tokens')
    op.drop_column('users', 'email_verified_at')

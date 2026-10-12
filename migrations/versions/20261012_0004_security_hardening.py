"""security hardening

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12 00:08:24.556909
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index('ix_audit_logs_action_at', ['action', 'at'], unique=False)

    with op.batch_alter_table('session_tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('session_tokens', schema=None) as batch_op:
        batch_op.drop_column('last_seen_at')

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_logs_action_at')


"""model governance

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11 19:51:53.586037
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('model_evaluations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('model_version_id', sa.Integer(), nullable=False),
    sa.Column('baseline_model_version_id', sa.Integer(), nullable=True),
    sa.Column('import_id', sa.Integer(), nullable=False),
    sa.Column('protocol', sa.JSON(), nullable=False),
    sa.Column('protocol_version', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('verdict', sa.String(length=30), nullable=True),
    sa.Column('gates', sa.JSON(), nullable=True),
    sa.Column('results', sa.JSON(), nullable=True),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('reference_sample', sa.JSON(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['baseline_model_version_id'], ['model_versions.id'], name=op.f('fk_model_evaluations_baseline_model_version_id_model_versions')),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_model_evaluations_created_by_id_users')),
    sa.ForeignKeyConstraint(['import_id'], ['dataset_imports.id'], name=op.f('fk_model_evaluations_import_id_dataset_imports')),
    sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], name=op.f('fk_model_evaluations_model_version_id_model_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_evaluations'))
    )
    with op.batch_alter_table('model_evaluations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_model_evaluations_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_model_evaluations_import_id'), ['import_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_model_evaluations_model_version_id'), ['model_version_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_model_evaluations_status'), ['status'], unique=False)

    with op.batch_alter_table('model_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approval_evaluation_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('approval_override', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('reference_sample', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('restore_check', sa.JSON(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_model_versions_approval_evaluation_id_model_evaluations'), 'model_evaluations', ['approval_evaluation_id'], ['id'], ondelete='SET NULL')



def downgrade() -> None:
    with op.batch_alter_table('model_versions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_model_versions_approval_evaluation_id_model_evaluations'), type_='foreignkey')
        batch_op.drop_column('restore_check')
        batch_op.drop_column('reference_sample')
        batch_op.drop_column('approval_override')
        batch_op.drop_column('approval_evaluation_id')

    with op.batch_alter_table('model_evaluations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_evaluations_status'))
        batch_op.drop_index(batch_op.f('ix_model_evaluations_model_version_id'))
        batch_op.drop_index(batch_op.f('ix_model_evaluations_import_id'))
        batch_op.drop_index(batch_op.f('ix_model_evaluations_created_at'))

    op.drop_table('model_evaluations')

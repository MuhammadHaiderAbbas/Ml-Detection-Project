"""prediction explanations

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12 09:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'prediction_explanations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('prediction_id', sa.Integer(), nullable=False),
        sa.Column('model_version_id', sa.Integer(), nullable=False),
        sa.Column('artifact_sha256', sa.String(length=64), nullable=False),
        sa.Column('preprocessing_version', sa.String(length=100), nullable=False),
        sa.Column('method', sa.String(length=100), nullable=False),
        sa.Column('library', sa.String(length=60), nullable=False),
        sa.Column('output_space', sa.String(length=20), nullable=False),
        sa.Column('target_class', sa.String(length=200), nullable=False),
        sa.Column('base_value', sa.Float(), nullable=False),
        sa.Column('model_output', sa.Float(), nullable=False),
        sa.Column('additivity_error', sa.Float(), nullable=False),
        sa.Column('contributions', sa.JSON(), nullable=False),
        sa.Column('limitations', sa.JSON(), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'],
                                name=op.f('fk_prediction_explanations_model_version_id_model_versions')),
        sa.ForeignKeyConstraint(['prediction_id'], ['predictions.id'], ondelete='CASCADE',
                                name=op.f('fk_prediction_explanations_prediction_id_predictions')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_explanations')),
        sa.UniqueConstraint('prediction_id', name=op.f('uq_prediction_explanations_prediction_id')),
    )
    with op.batch_alter_table('prediction_explanations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prediction_explanations_model_version_id'), ['model_version_id'],
                              unique=False)


def downgrade() -> None:
    with op.batch_alter_table('prediction_explanations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prediction_explanations_model_version_id'))
    op.drop_table('prediction_explanations')

"""add validation profiles and profile linkage to validation logs

Revision ID: e6f5a4b3c2d1
Revises: d5e4f3a2b1c0
Create Date: 2026-11-03 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6f5a4b3c2d1'
down_revision = 'd5e4f3a2b1c0'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create validation_profiles table
    op.create_table(
        'validation_profiles',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=True),
        sa.Column('document_kind', sa.String(length=100), nullable=False, server_default='Umum'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scope', sa.String(length=50), nullable=False, server_default='GLOBAL'),
        sa.Column('department_id', sa.String(length=50), nullable=True),
        sa.Column('department_name', sa.String(length=150), nullable=True),
        sa.Column('passing_score_threshold', sa.Float(), nullable=False, server_default='80.0'),
        sa.Column('warning_score_threshold', sa.Float(), nullable=False, server_default='60.0'),
        sa.Column('strict_mandatory_enforcement', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('target_stage_to_clear', sa.String(length=150), nullable=True),
        sa.Column('custom_system_prompt', sa.Text(), nullable=True),
        sa.Column('checklist_rules', sa.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by_id', sa.String(length=50), nullable=True),
        sa.Column('created_by_name', sa.String(length=150), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_validation_profiles_id'), 'validation_profiles', ['id'], unique=False)
    op.create_index(op.f('ix_validation_profiles_name'), 'validation_profiles', ['name'], unique=False)
    op.create_index(op.f('ix_validation_profiles_code'), 'validation_profiles', ['code'], unique=True)
    op.create_index(op.f('ix_validation_profiles_document_kind'), 'validation_profiles', ['document_kind'], unique=False)

    # 2. Add profile_id, profile_name, passing_score_threshold to document_validation_logs
    op.add_column('document_validation_logs', sa.Column('profile_id', sa.String(length=50), nullable=True))
    op.add_column('document_validation_logs', sa.Column('profile_name', sa.String(length=255), nullable=True))
    op.add_column('document_validation_logs', sa.Column('passing_score_threshold', sa.Float(), nullable=True, server_default='80.0'))
    op.create_index(op.f('ix_document_validation_logs_profile_id'), 'document_validation_logs', ['profile_id'], unique=False)
    op.create_foreign_key(
        'fk_doc_val_logs_profile_id',
        'document_validation_logs', 'validation_profiles',
        ['profile_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('fk_doc_val_logs_profile_id', 'document_validation_logs', type_='foreignkey')
    op.drop_index(op.f('ix_document_validation_logs_profile_id'), table_name='document_validation_logs')
    op.drop_column('document_validation_logs', 'passing_score_threshold')
    op.drop_column('document_validation_logs', 'profile_name')
    op.drop_column('document_validation_logs', 'profile_id')

    op.drop_index(op.f('ix_validation_profiles_document_kind'), table_name='validation_profiles')
    op.drop_index(op.f('ix_validation_profiles_code'), table_name='validation_profiles')
    op.drop_index(op.f('ix_validation_profiles_name'), table_name='validation_profiles')
    op.drop_index(op.f('ix_validation_profiles_id'), table_name='validation_profiles')
    op.drop_table('validation_profiles')


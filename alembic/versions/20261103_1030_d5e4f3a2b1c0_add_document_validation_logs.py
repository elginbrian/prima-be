"""add_document_validation_logs

Revision ID: d5e4f3a2b1c0
Revises: c4d3e2f1a0b9
Create Date: 2026-11-03 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e4f3a2b1c0'
down_revision = 'c4d3e2f1a0b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_validation_logs',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('request_id', sa.String(length=50), nullable=True),
        sa.Column('document_id', sa.String(length=50), nullable=True),
        sa.Column('document_name', sa.String(length=255), nullable=False),
        sa.Column('document_file_url', sa.Text(), nullable=True),
        sa.Column('mime_type', sa.String(length=100), nullable=True),
        sa.Column('user_prompt', sa.Text(), nullable=True),
        sa.Column('checklist_snapshot', sa.JSON(), nullable=False),
        sa.Column('validation_result', sa.JSON(), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('compliance_status', sa.String(length=50), nullable=False, server_default='Catatan Procurement'),
        sa.Column('validated_by_id', sa.String(length=50), nullable=True),
        sa.Column('validated_by_name', sa.String(length=150), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['request_id'], ['procurement_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_validation_logs_id'), 'document_validation_logs', ['id'], unique=False)
    op.create_index(op.f('ix_document_validation_logs_request_id'), 'document_validation_logs', ['request_id'], unique=False)
    op.create_index(op.f('ix_document_validation_logs_document_id'), 'document_validation_logs', ['document_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_document_validation_logs_document_id'), table_name='document_validation_logs')
    op.drop_index(op.f('ix_document_validation_logs_request_id'), table_name='document_validation_logs')
    op.drop_index(op.f('ix_document_validation_logs_id'), table_name='document_validation_logs')
    op.drop_table('document_validation_logs')


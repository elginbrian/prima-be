"""add_document_versioning

Revision ID: c4d3e2f1a0b9
Revises: b3c2d1e0f9a8
Create Date: 2026-10-13 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d3e2f1a0b9'
down_revision = 'b3c2d1e0f9a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('documents', sa.Column('parent_document_id', sa.String(), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True))
    op.add_column('documents', sa.Column('revision_notes', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'revision_notes')
    op.drop_column('documents', 'parent_document_id')
    op.drop_column('documents', 'version_number')

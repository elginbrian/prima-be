"""add_documents

Revision ID: 62a1b9c9d4e5
Revises: 52a1b9c9d4e5
Create Date: 2026-10-08 16:27:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '62a1b9c9d4e5'
down_revision = '52a1b9c9d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('documents',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('request_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('document_kind', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('upload_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('pic_id', sa.String(length=50), nullable=False),
    sa.Column('pic_name', sa.String(length=150), nullable=False),
    sa.Column('issues', postgresql.ARRAY(sa.String()), nullable=True),
    sa.Column('next_action', sa.String(), nullable=True),
    sa.Column('procurement_step', sa.String(length=100), nullable=True),
    sa.Column('document_date', sa.String(length=50), nullable=True),
    sa.Column('document_number', sa.String(length=100), nullable=True),
    sa.Column('file_url', sa.String(), nullable=True),
    sa.Column('mime_type', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['request_id'], ['procurement_requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('documents')

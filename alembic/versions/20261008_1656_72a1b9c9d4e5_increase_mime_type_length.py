"""increase mime_type length

Revision ID: 72a1b9c9d4e5
Revises: 62a1b9c9d4e5
Create Date: 2026-10-08 16:56:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '72a1b9c9d4e5'
down_revision = '62a1b9c9d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alter column mime_type type from VARCHAR(50) to VARCHAR(100)
    op.alter_column('documents', 'mime_type',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.String(length=100),
               existing_nullable=True)


def downgrade() -> None:
    # Alter column mime_type type from VARCHAR(100) to VARCHAR(50)
    op.alter_column('documents', 'mime_type',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)

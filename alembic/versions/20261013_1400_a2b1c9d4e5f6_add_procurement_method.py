"""add_procurement_method

Revision ID: a2b1c9d4e5f6
Revises: 92a1b9c9d4e5
Create Date: 2026-10-13 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2b1c9d4e5f6'
down_revision = '92a1b9c9d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('procurement_requests', sa.Column('procurement_method', sa.String(length=100), nullable=False, server_default='Tender Terbuka'))


def downgrade() -> None:
    op.drop_column('procurement_requests', 'procurement_method')

"""add_deadline_escalation_fields

Revision ID: b3c2d1e0f9a8
Revises: a2b1c9d4e5f6
Create Date: 2026-10-13 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3c2d1e0f9a8'
down_revision = 'a2b1c9d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('deadlines', sa.Column('is_escalated', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('deadlines', sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deadlines', sa.Column('escalated_to', sa.String(length=100), nullable=True))
    op.add_column('deadlines', sa.Column('recovery_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('deadlines', sa.Column('recovery_plan', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('deadlines', 'recovery_plan')
    op.drop_column('deadlines', 'recovery_date')
    op.drop_column('deadlines', 'escalated_to')
    op.drop_column('deadlines', 'escalated_at')
    op.drop_column('deadlines', 'is_escalated')

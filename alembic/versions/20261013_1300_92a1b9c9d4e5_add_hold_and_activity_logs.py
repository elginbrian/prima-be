"""add_hold_and_activity_logs

Revision ID: 92a1b9c9d4e5
Revises: 82a1b9c9d4e5
Create Date: 2026-10-13 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '92a1b9c9d4e5'
down_revision = '82a1b9c9d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add hold tracking columns to procurement_requests
    op.add_column('procurement_requests', sa.Column('hold_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('procurement_requests', sa.Column('total_hold_days', sa.Float(), nullable=False, server_default='0.0'))

    # 2. Create procurement_activity_logs table
    op.create_table(
        'procurement_activity_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('user_name', sa.String(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('previous_state', sa.String(length=100), nullable=True),
        sa.Column('new_state', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['procurement_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_procurement_activity_logs_request_id'), 'procurement_activity_logs', ['request_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_procurement_activity_logs_request_id'), table_name='procurement_activity_logs')
    op.drop_table('procurement_activity_logs')
    op.drop_column('procurement_requests', 'total_hold_days')
    op.drop_column('procurement_requests', 'hold_started_at')

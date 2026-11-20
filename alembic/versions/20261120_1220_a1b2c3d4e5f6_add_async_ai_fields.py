"""add async ai processing fields and notification action_url

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-11-20 12:20:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_validation_logs",
        sa.Column("processing_status", sa.String(length=30), nullable=False, server_default="completed"),
    )
    op.add_column(
        "document_validation_logs",
        sa.Column("ai_tier_requested", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "document_validation_logs",
        sa.Column("ai_tier_used", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "document_validation_logs",
        sa.Column("ai_model_used", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "document_validation_logs",
        sa.Column("ai_fallback_notice", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_validation_logs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("action_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "action_url")
    op.drop_column("document_validation_logs", "error_message")
    op.drop_column("document_validation_logs", "ai_fallback_notice")
    op.drop_column("document_validation_logs", "ai_model_used")
    op.drop_column("document_validation_logs", "ai_tier_used")
    op.drop_column("document_validation_logs", "ai_tier_requested")
    op.drop_column("document_validation_logs", "processing_status")

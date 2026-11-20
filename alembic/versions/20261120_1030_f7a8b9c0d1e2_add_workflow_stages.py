"""add configurable workflow stages table

Revision ID: f7a8b9c0d1e2
Revises: e6f5a4b3c2d1
Create Date: 2026-11-20 10:30:00.000000

"""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a8b9c0d1e2'
down_revision = 'e6f5a4b3c2d1'
branch_labels = None
depends_on = None


def upgrade():
    workflow_stages = op.create_table(
        'workflow_stages',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('procurement_method', sa.String(length=100), nullable=False, server_default='Tender Terbuka'),
        sa.Column('step_name', sa.String(length=200), nullable=False),
        sa.Column('stage_group', sa.String(length=50), nullable=False, server_default='Sourcing'),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('default_sla_days', sa.Integer(), nullable=True, server_default='5'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workflow_stages_id'), 'workflow_stages', ['id'], unique=False)
    op.create_index(op.f('ix_workflow_stages_procurement_method'), 'workflow_stages', ['procurement_method'], unique=False)

    # Seed default stages so existing deployments immediately have active workflow stages
    now = datetime.now(timezone.utc)
    default_methods = {
        "Tender Terbuka": [
            ("Penerimaan FPP", "Persiapan", 2),
            ("Penyusunan RKS & Spesifikasi Teknis", "Persiapan", 5),
            ("Rapat Pra-Tender", "Sourcing", 3),
            ("Pengumuman Pengadaan", "Sourcing", 7),
            ("Prebid Meeting", "Sourcing", 3),
            ("Pemasukan Dokumen Penawaran", "Sourcing", 7),
            ("Pembukaan Penawaran", "Evaluasi", 2),
            ("Evaluasi Dokumen Penawaran", "Evaluasi", 7),
            ("Sosialisasi e-Auction", "Evaluasi", 2),
            ("Negosiasi e-Auction", "Evaluasi", 3),
            ("Negosiasi Manual", "Evaluasi", 3),
            ("Laporan Hasil Pemilihan", "Contracting", 3),
            ("Pengumuman Pemenang", "Contracting", 3),
            ("Penunjukan Pemenang", "Selesai", 3),
        ],
        "Pemilihan Langsung": [
            ("Rapat Pra-Tender", "Sourcing", 3),
            ("Undangan Pemilihan", "Sourcing", 3),
            ("Pemasukan Dokumen Penawaran", "Sourcing", 5),
            ("Pembukaan & Evaluasi Penawaran", "Evaluasi", 5),
            ("Klarifikasi & Negosiasi Teknis", "Evaluasi", 3),
            ("Laporan Hasil Pemilihan", "Contracting", 3),
            ("Penetapan Pemenang", "Contracting", 2),
            ("Penunjukan Pemenang", "Selesai", 2),
        ],
        "Penunjukan Langsung": [
            ("Undangan Penunjukan Langsung", "Sourcing", 2),
            ("Pemasukan & Evaluasi Dokumen", "Evaluasi", 4),
            ("Klarifikasi & Negosiasi Harga", "Evaluasi", 3),
            ("Penunjukan Pemenang", "Selesai", 2),
        ],
    }

    rows = []
    idx_counter = 1
    for method_name, steps in default_methods.items():
        for order_idx, (step_name, stage_group, sla_days) in enumerate(steps):
            rows.append({
                "id": f"STG-DEFAULT-{idx_counter:03d}",
                "procurement_method": method_name,
                "step_name": step_name,
                "stage_group": stage_group,
                "order_index": order_idx,
                "default_sla_days": sla_days,
                "description": None,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            })
            idx_counter += 1

    op.bulk_insert(workflow_stages, rows)


def downgrade():
    op.drop_index(op.f('ix_workflow_stages_procurement_method'), table_name='workflow_stages')
    op.drop_index(op.f('ix_workflow_stages_id'), table_name='workflow_stages')
    op.drop_table('workflow_stages')

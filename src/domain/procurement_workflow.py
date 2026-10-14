"""
Procurement workflow definitions (Modul D3)

Single source of truth for the milestone steps of each procurement method and
the mapping from a step to the stage it belongs to.
"""
from typing import List, Optional

DEFAULT_METHOD = "Tender Terbuka"

METHOD_STEPS = {
    "Tender Terbuka": [
        "Rapat Pra-Tender",
        "Pengumuman Pengadaan",
        "Prebid Meeting",
        "Pemasukan Dokumen Penawaran",
        "Pembukaan Penawaran",
        "Evaluasi Dokumen Penawaran",
        "Sosialisasi e-Auction",
        "Negosiasi e-Auction",
        "Negosiasi Manual",
        "Laporan Hasil Pemilihan",
        "Pengumuman Pemenang",
        "Penunjukan Pemenang",
    ],
    "Pemilihan Langsung": [
        "Rapat Pra-Tender",
        "Undangan Pemilihan",
        "Pemasukan Dokumen Penawaran",
        "Pembukaan & Evaluasi Penawaran",
        "Klarifikasi & Negosiasi Teknis",
        "Laporan Hasil Pemilihan",
        "Penetapan Pemenang",
        "Penunjukan Pemenang",
    ],
    "Penunjukan Langsung": [
        "Undangan Penunjukan Langsung",
        "Pemasukan & Evaluasi Dokumen",
        "Klarifikasi & Negosiasi Harga",
        "Penunjukan Pemenang",
    ],
}

PROCUREMENT_STEPS = METHOD_STEPS[DEFAULT_METHOD]

STEP_TO_STAGE = {
    # Tender Terbuka
    "Rapat Pra-Tender": "Sourcing",
    "Pengumuman Pengadaan": "Sourcing",
    "Prebid Meeting": "Sourcing",
    "Pemasukan Dokumen Penawaran": "Sourcing",
    "Pembukaan Penawaran": "Evaluasi",
    "Evaluasi Dokumen Penawaran": "Evaluasi",
    "Sosialisasi e-Auction": "Evaluasi",
    "Negosiasi e-Auction": "Evaluasi",
    "Negosiasi Manual": "Evaluasi",
    "Laporan Hasil Pemilihan": "Contracting",
    "Pengumuman Pemenang": "Contracting",
    "Penunjukan Pemenang": "Selesai",
    # Pemilihan Langsung additions
    "Undangan Pemilihan": "Sourcing",
    "Pembukaan & Evaluasi Penawaran": "Evaluasi",
    "Klarifikasi & Negosiasi Teknis": "Evaluasi",
    "Penetapan Pemenang": "Contracting",
    # Penunjukan Langsung additions
    "Undangan Penunjukan Langsung": "Sourcing",
    "Pemasukan & Evaluasi Dokumen": "Evaluasi",
    "Klarifikasi & Negosiasi Harga": "Evaluasi",
}


def steps_for_method(method: Optional[str]) -> List[str]:
    """Return the ordered milestone steps for a procurement method (falls back to Tender Terbuka)."""
    return METHOD_STEPS.get(method or DEFAULT_METHOD, METHOD_STEPS[DEFAULT_METHOD])


def step_index(step: str, steps: List[str] = PROCUREMENT_STEPS, default: int = 0) -> int:
    """Index of a step inside `steps`, or `default` when unknown."""
    return steps.index(step) if step in steps else default

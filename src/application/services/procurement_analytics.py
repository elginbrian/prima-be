"""
Procurement analytics service (Executive Analytics & SLA Intelligence).

Builds the payload for GET /procurement/analytics/overview:
  1. Overall SLA compliance + summary KPIs
  2. Department compliance ranking
  3. Stage/step bottleneck identifier
  4. Vendor risk index (bank guarantees & claims)
  5. Method / status / stage distribution and document stats
"""
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.models.procurement_model import ProcurementRequestModel
from src.infrastructure.models.deadline_model import DeadlineModel
from src.infrastructure.models.guarantee_model import GuaranteeModel
from src.infrastructure.models.document_model import DocumentModel

DEADLINE_STATUSES = ("On Track", "At Risk", "Overdue", "Selesai")
COMPLIANT_STATUSES = ("On Track", "Selesai")
MAX_BOTTLENECKS = 5
HIGH_SEVERITY_OVERDUE_COUNT = 2
HIGH_RISK_EXPIRING_COUNT = 2


def _summarize_procurements(procs: list) -> dict:
    methods: Dict[str, int] = {}
    status: Dict[str, int] = {"On Going": 0, "On Hold": 0, "Batal": 0}
    stages: Dict[str, int] = {}

    for p in procs:
        method = p.procurement_method or "Tender Terbuka"
        methods[method] = methods.get(method, 0) + 1
        st = p.operational_status or "On Going"
        status[st] = status.get(st, 0) + 1
        stages[p.stage] = stages.get(p.stage, 0) + 1

    return {
        "total": len(procs),
        "budget": sum(float(p.amount) for p in procs) if procs else 0.0,
        "methods": methods,
        "status": status,
        "stages": stages,
    }


def _summarize_deadlines(deadlines: list) -> dict:
    counts = {s: 0 for s in DEADLINE_STATUSES}
    escalated = 0
    dept_map: Dict[str, dict] = {}
    milestone_overdue: Dict[str, int] = {}

    for d in deadlines:
        st = d.status if d.status in counts else "On Track"
        counts[st] += 1
        if d.is_escalated:
            escalated += 1

        dept = dept_map.setdefault(d.department_name or "Umum", {"total": 0, "compliant": 0, "overdue": 0})
        dept["total"] += 1
        if st in COMPLIANT_STATUSES:
            dept["compliant"] += 1
        elif st == "Overdue":
            dept["overdue"] += 1

        if st == "Overdue":
            milestone_overdue[d.milestone] = milestone_overdue.get(d.milestone, 0) + 1

    total = len(deadlines)
    compliance_rate = round(
        ((counts["On Track"] + counts["Selesai"]) / total * 100) if total > 0 else 100.0, 1
    )
    return {
        "total": total,
        "counts": counts,
        "escalated": escalated,
        "dept_map": dept_map,
        "milestone_overdue": milestone_overdue,
        "compliance_rate": compliance_rate,
    }


def _department_ranking(dept_map: Dict[str, dict]) -> List[dict]:
    ranking = [
        {
            "department": name,
            "total_deadlines": s["total"],
            "compliant": s["compliant"],
            "overdue": s["overdue"],
            "compliance_rate": round((s["compliant"] / s["total"] * 100) if s["total"] > 0 else 100.0, 1),
        }
        for name, s in dept_map.items()
    ]
    ranking.sort(key=lambda x: x["compliance_rate"], reverse=True)
    return ranking


def _bottlenecks(milestone_overdue: Dict[str, int]) -> List[dict]:
    top = sorted(milestone_overdue.items(), key=lambda x: x[1], reverse=True)[:MAX_BOTTLENECKS]
    return [
        {
            "milestone": milestone,
            "overdue_count": count,
            "severity": "High" if count >= HIGH_SEVERITY_OVERDUE_COUNT else "Medium",
        }
        for milestone, count in top
    ]


def _vendor_risk_index(guarantees: list) -> List[dict]:
    vendor_map: Dict[str, dict] = {}
    for g in guarantees:
        v = vendor_map.setdefault(
            g.vendor_name or "Vendor Tidak Terdaftar",
            {"total_guarantees": 0, "expiring_soon": 0, "claimed": 0, "total_value": 0.0},
        )
        v["total_guarantees"] += 1
        v["total_value"] += float(g.value) if g.value else 0.0
        if g.status == "Mendekati Expiry":
            v["expiring_soon"] += 1
        elif g.status in ("Klaim Diajukan", "Klaim Selesai"):
            v["claimed"] += 1

    index = []
    for name, s in vendor_map.items():
        if s["claimed"] > 0 or s["expiring_soon"] >= HIGH_RISK_EXPIRING_COUNT:
            risk = "High"
        elif s["expiring_soon"] == 1:
            risk = "Medium"
        else:
            risk = "Low"
        index.append({
            "vendor_name": name,
            "total_guarantees": s["total_guarantees"],
            "total_value": s["total_value"],
            "expiring_soon": s["expiring_soon"],
            "claimed": s["claimed"],
            "risk_level": risk,
        })
    index.sort(
        key=lambda x: (x["risk_level"] == "High", x["risk_level"] == "Medium", x["total_value"]),
        reverse=True,
    )
    return index


def _document_stats(docs: list) -> dict:
    return {
        "total": len(docs),
        "verified": sum(1 for d in docs if d.status == "Lulus Verifikasi"),
        "with_notes": sum(1 for d in docs if d.status == "Catatan Procurement"),
        "follow_up": sum(1 for d in docs if d.status == "Tindak Lanjut FPP"),
    }


async def build_analytics_overview(db: AsyncSession) -> dict:
    """Aggregate procurement, deadline, guarantee and document data into the analytics payload."""
    procs = (await db.execute(select(ProcurementRequestModel))).scalars().all()
    deadlines = (await db.execute(select(DeadlineModel))).scalars().all()
    guarantees = (await db.execute(select(GuaranteeModel))).scalars().all()
    docs = (await db.execute(select(DocumentModel))).scalars().all()

    p = _summarize_procurements(procs)
    d = _summarize_deadlines(deadlines)

    return {
        "summary": {
            "total_procurements": p["total"],
            "total_budget": p["budget"],
            "overall_compliance_rate": d["compliance_rate"],
            "total_deadlines": d["total"],
            "overdue_deadlines": d["counts"]["Overdue"],
            "escalated_deadlines": d["escalated"],
        },
        "deadline_stats": d["counts"],
        "department_compliance": _department_ranking(d["dept_map"]),
        "bottlenecks": _bottlenecks(d["milestone_overdue"]),
        "vendor_risk_index": _vendor_risk_index(guarantees),
        "methods_breakdown": p["methods"],
        "status_breakdown": p["status"],
        "stage_breakdown": p["stages"],
        "document_stats": _document_stats(docs),
    }

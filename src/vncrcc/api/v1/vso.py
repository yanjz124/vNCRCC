from fastapi import APIRouter, Query, HTTPException, Request
from typing import List, Dict, Any, Optional

from ... import storage
from ...rate_limit import limiter
from ...geo.loader import point_from_aircraft
from .sfra import _dca_radial_range

router = APIRouter(prefix="/vso")


def _match_affiliations(remarks: Optional[str], patterns: List[str]) -> List[str]:
    """Return list of matching affiliation patterns found in remarks (case-insensitive)."""
    if not remarks:
        return []
    low = remarks.lower()
    matched = []
    for p in patterns:
        pp = p.strip().lower()
        if not pp:
            continue
        if pp in low:
            matched.append(p.strip())
    return matched


@router.get("/")
@limiter.limit("6/minute")
async def vso_aircraft(request: Request, range_nm: int = Query(60, description="maximum range (nautical miles) from DCA (radius)"),
                       affiliations: Optional[str] = Query(None, description="comma-separated list of flight-plan remark patterns to match (e.g. vusaf.us,vuscg,usnv). If provided, only aircraft whose flight_plan.remarks contain any pattern are returned.")) -> Dict[str, Any]:
    """Return aircraft within `range_nm` nautical miles of DCA that match optional affiliation remark patterns.

    Response structure mirrors other endpoints and includes:
    - aircraft: list of { aircraft: <orig dict>, dca: {radial_range,bearing,range_nm}, matched_affiliations: [patterns] }
    """
    snap = storage.STORAGE.get_latest_snapshot() if storage.STORAGE else None
    if not snap:
        return {"aircraft": []}
    aircraft = snap.get("data", {}).get("pilots") or snap.get("data", {}).get("aircraft") or []

    patterns: List[str] = []
    if affiliations:
        patterns = [p.strip() for p in affiliations.split(",") if p.strip()]

    out: List[Dict[str, Any]] = []
    for a in aircraft:
        pt = point_from_aircraft(a)
        if not pt:
            continue
        dca = _dca_radial_range(pt.y, pt.x)
        # include only within requested range (radius)
        if dca.get("range_nm", 999999) > int(range_nm):
            continue

        # extract remarks from nested flight_plan if present
        fp = a.get("flight_plan") or {}
        remarks = fp.get("remarks") or fp.get("rmk") or fp.get("remark") or None
        matched = _match_affiliations(remarks, patterns) if patterns else []
        # If patterns provided, only include aircraft that matched at least one
        if patterns and not matched:
            continue

        out.append({"aircraft": a, "dca": dca, "matched_affiliations": matched, "position_history": storage.STORAGE.get_aircraft_position_history(a.get("cid"), 10) if storage.STORAGE else []})

    return {"aircraft": out}

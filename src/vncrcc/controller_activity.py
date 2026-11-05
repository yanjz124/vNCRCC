"""Online ATC for the National Capital Region (from the vNAS feed)."""
import httpx
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# vNAS API endpoint
VNAS_CONTROLLERS_URL = "https://live.env.vnas.vatsim.net/data-feed/controllers.json"

# National Capital Region facilities (vNAS primaryFacilityId). Everything
# else in ZDC (RIC, ORF, ROA, CHO, ...) is outside the NCR and not shown.
#   ZDC  - Washington Center: owns the NCR top-down when PCT is unstaffed
#   PCT  - Potomac TRACON
#   DCA/IAD/BWI/ADW/NYG/HEF/MTN/FDK/JYO/DAA - towers in or adjoining the
#   DC SFRA. PCT also parents CHO/HGR/MRB/RIC, which are outside the NCR.
NCR_FACILITIES = frozenset({"ZDC", "PCT", "DCA", "IAD", "BWI", "ADW", "NYG", "HEF", "MTN", "FDK", "JYO", "DAA"})


def is_ncr_controller(controller: Dict) -> bool:
    """True if a vNAS controller record is staffing an NCR facility."""
    if controller.get("isObserver"):
        return False
    return controller.get("primaryFacilityId") in NCR_FACILITIES

# Reusable client to avoid creating a new connection per fetch
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def fetch_zdc_controllers() -> List[Dict]:
    """
    Fetch controllers staffing National Capital Region facilities from vNAS.

    See NCR_FACILITIES; observers are excluded.
    Returns simplified controller info for display.
    """
    try:
        client = _get_client()
        response = await client.get(VNAS_CONTROLLERS_URL)
        response.raise_for_status()
        data = response.json()

        # Extract controllers array from wrapper
        controllers_list = data.get("controllers", [])

        # Filter controllers
        filtered = []
        for controller in controllers_list:
            if not is_ncr_controller(controller):
                continue
            facility_id = controller.get("primaryFacilityId")

            # Extract relevant info
            vatsim_data = controller.get("vatsimData", {})
            positions = controller.get("positions", [])

            # Get primary position info
            primary_position = None
            for pos in positions:
                if pos.get("isPrimary"):
                    primary_position = pos
                    break

            # If no primary, use first position
            if not primary_position and positions:
                primary_position = positions[0]

            controller_info = {
                "cid": vatsim_data.get("cid"),
                "realName": vatsim_data.get("realName"),
                "callsign": vatsim_data.get("callsign"),
                "frequency": format_frequency(vatsim_data.get("primaryFrequency")),
                "facilityId": facility_id,
                "facilityName": primary_position.get("facilityName") if primary_position else None,
                "positionName": primary_position.get("positionName") if primary_position else None,
                "positionType": primary_position.get("positionType") if primary_position else None,
                "radioName": primary_position.get("radioName") if primary_position else None,
                "loginTime": controller.get("loginTime"),
                "rating": vatsim_data.get("userRating"),
            }

            filtered.append(controller_info)

        logger.debug("Fetched %d NCR controllers from vNAS", len(filtered))
        return filtered

    except httpx.HTTPError as e:
        logger.error(f"Error fetching controllers from vNAS: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching controllers: {e}")
        return []


def format_frequency(freq_hz: Optional[int]) -> Optional[str]:
    """Convert frequency from Hz to MHz string (e.g., 126750000 -> '126.750')."""
    if freq_hz is None:
        return None
    try:
        freq_mhz = freq_hz / 1_000_000
        return f"{freq_mhz:.3f}"
    except Exception:
        return None

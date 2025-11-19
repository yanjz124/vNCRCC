"""Controller activity tracking for ZDC controllers."""
import httpx
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# vNAS API endpoint
VNAS_CONTROLLERS_URL = "https://live.env.vnas.vatsim.net/data-feed/controllers.json"

# Filter criteria
TARGET_ARTCC = "ZDC"
TARGET_FACILITIES = {"PCT", "DCA", "NYG", "ZDC", "ADW"}


async def fetch_zdc_controllers() -> List[Dict]:
    """
    Fetch active ZDC controllers from vNAS API.
    
    Filters for artccId=ZDC and primaryFacilityId in {PCT, DCA, NYG, ZDC, ADW}.
    Returns simplified controller info for display.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(VNAS_CONTROLLERS_URL)
            response.raise_for_status()
            data = response.json()
            
            # Filter controllers
            filtered = []
            for controller in data:
                artcc_id = controller.get("artccId")
                facility_id = controller.get("primaryFacilityId")
                
                # Only include ZDC controllers at target facilities
                if artcc_id != TARGET_ARTCC or facility_id not in TARGET_FACILITIES:
                    continue
                
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
            
            logger.info(f"Fetched {len(filtered)} ZDC controllers from vNAS")
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
    except:
        return None

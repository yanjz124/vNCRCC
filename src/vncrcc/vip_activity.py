"""
VIP Activity Detection for VATSIM.

Monitors for presidential and VP callsigns globally (no range restriction).
Based on TBL 2-3-8 and TBL 2-3-9 from official documentation.
"""

# VIP callsign patterns (all variations must be uppercase)
VIP_CALLSIGNS = {
    # Presidential callsigns (TBL 2-3-8)
    'AF1': {'title': 'Air Force One', 'type': 'President', 'service': 'Air Force'},
    'VM1': {'title': 'Marine One', 'type': 'President', 'service': 'Marine'},
    'VV1': {'title': 'Navy One', 'type': 'President', 'service': 'Navy'},
    'RR1': {'title': 'Army One', 'type': 'President', 'service': 'Army'},
    'C1': {'title': 'Coast Guard One', 'type': 'President', 'service': 'Coast Guard'},
    'G1': {'title': 'Guard One', 'type': 'President', 'service': 'Guard'},
    'EXEC1': {'title': 'Executive One', 'type': 'President', 'service': 'Commercial'},
    'EXEC1F': {'title': 'Executive One Foxtrot', 'type': 'President Family', 'service': 'Commercial'},
    
    # VP callsigns (TBL 2-3-9)
    'AF2': {'title': 'Air Force Two', 'type': 'Vice President', 'service': 'Air Force'},
    'VM2': {'title': 'Marine Two', 'type': 'Vice President', 'service': 'Marine'},
    'VV2': {'title': 'Navy Two', 'type': 'Vice President', 'service': 'Navy'},
    'RR2': {'title': 'Army Two', 'type': 'Vice President', 'service': 'Army'},
    'C2': {'title': 'Coast Guard Two', 'type': 'Vice President', 'service': 'Coast Guard'},
    'G2': {'title': 'Guard Two', 'type': 'Vice President', 'service': 'Guard'},
    'EXEC2': {'title': 'Executive Two', 'type': 'Vice President', 'service': 'Commercial'},
    'EXEC2F': {'title': 'Executive Two Foxtrot', 'type': 'VP Family', 'service': 'Commercial'},
}


def is_vip_callsign(callsign: str) -> bool:
    """Check if a callsign matches any VIP pattern."""
    if not callsign:
        return False
    cs_upper = callsign.strip().upper()
    return cs_upper in VIP_CALLSIGNS


def get_vip_info(callsign: str) -> dict:
    """Get VIP metadata for a callsign."""
    if not callsign:
        return {}
    cs_upper = callsign.strip().upper()
    return VIP_CALLSIGNS.get(cs_upper, {})


def detect_vip_aircraft(aircraft_list: list) -> list:
    """
    Scan entire aircraft list for VIP callsigns.
    
    Args:
        aircraft_list: List of pilot dicts from VATSIM JSON
        
    Returns:
        List of dicts with VIP aircraft info
    """
    vips = []
    
    for ac in aircraft_list:
        callsign = ac.get('callsign', '').strip().upper()
        
        if callsign in VIP_CALLSIGNS:
            vip_info = VIP_CALLSIGNS[callsign]
            
            # Build enriched VIP record
            vip_record = {
                'callsign': ac.get('callsign', ''),
                'cid': ac.get('cid'),
                'name': ac.get('name', ''),
                'latitude': ac.get('latitude'),
                'longitude': ac.get('longitude'),
                'altitude': ac.get('altitude'),
                'groundspeed': ac.get('groundspeed'),
                'heading': ac.get('heading'),
                'transponder': ac.get('transponder', ''),
                'flight_plan': ac.get('flight_plan'),
                'last_updated': ac.get('last_updated'),
                
                # VIP metadata
                'vip_title': vip_info['title'],
                'vip_type': vip_info['type'],
                'vip_service': vip_info['service'],
            }
            vips.append(vip_record)
    
    return vips

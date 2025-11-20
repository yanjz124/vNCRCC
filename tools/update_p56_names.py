#!/usr/bin/env python3
"""Update P56 history names to be consistent with current VATSIM data."""
import json
import sys
from pathlib import Path
from collections import defaultdict

def analyze_and_update(history_path: str, dry_run: bool = True):
    """Analyze name inconsistencies and optionally update them."""
    with open(history_path, 'r') as f:
        data = json.load(f)
    
    events = data.get('events', [])
    current_inside = data.get('current_inside', {})
    
    # Build a map of CID -> most recent name from current_inside
    current_names = {}
    for cid, state in current_inside.items():
        name = state.get('name')
        if name:
            current_names[cid] = name
    
    # Also get most recent names from recent events
    for event in reversed(events[-50:]):  # Check last 50 events
        cid = str(event.get('cid', ''))
        name = event.get('name')
        if cid and name and cid not in current_names:
            current_names[cid] = name
    
    print(f"Found {len(events)} events")
    print(f"Current names for {len(current_names)} CIDs")
    
    # Find inconsistencies
    updates_needed = []
    name_variations = defaultdict(lambda: defaultdict(int))
    
    for i, event in enumerate(events):
        cid = str(event.get('cid', ''))
        event_name = event.get('name', '')
        callsign = event.get('callsign', '')
        
        if cid:
            name_variations[cid][event_name] += 1
            
            if cid in current_names and event_name != current_names[cid]:
                updates_needed.append({
                    'index': i,
                    'cid': cid,
                    'callsign': callsign,
                    'old_name': event_name,
                    'new_name': current_names[cid]
                })
    
    # Show CIDs with multiple name variations
    print("\nCIDs with name variations:")
    for cid, names in sorted(name_variations.items()):
        if len(names) > 1:
            print(f"  CID {cid}:")
            for name, count in sorted(names.items(), key=lambda x: -x[1]):
                current_marker = " (CURRENT)" if name == current_names.get(cid) else ""
                print(f"    {name!r} ({count}x){current_marker}")
    
    print(f"\n{len(updates_needed)} events need name updates")
    
    if updates_needed:
        print("\nUpdates to apply:")
        for u in updates_needed[:10]:  # Show first 10
            print(f"  Event {u['index']}: CID {u['cid']} ({u['callsign']})")
            print(f"    {u['old_name']!r} -> {u['new_name']!r}")
        if len(updates_needed) > 10:
            print(f"  ... and {len(updates_needed) - 10} more")
    
    if not dry_run and updates_needed:
        print(f"\nApplying {len(updates_needed)} updates...")
        for u in updates_needed:
            events[u['index']]['name'] = u['new_name']
        
        # Write backup
        backup_path = Path(history_path).with_suffix('.json.bak')
        with open(backup_path, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        print(f"Backup written to {backup_path}")
        
        # Write updated file
        with open(history_path, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        print(f"Updated {history_path}")
    elif updates_needed:
        print("\nDry run - no changes made. Run with --apply to update.")
    else:
        print("\nNo updates needed - all names are consistent!")
    
    return len(updates_needed)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Update P56 history names for consistency')
    parser.add_argument('--history', default='/home/JY/vNCRCC/data/p56_history.json',
                        help='Path to p56_history.json')
    parser.add_argument('--apply', action='store_true',
                        help='Actually apply updates (default is dry-run)')
    args = parser.parse_args()
    
    count = analyze_and_update(args.history, dry_run=not args.apply)
    sys.exit(0 if count == 0 else 1)

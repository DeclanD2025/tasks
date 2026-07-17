#!/usr/bin/env python3
"""
Add time estimates to all weekend tasks.
Stores time as '{t:N}' prefix in the notes field, e.g. '{t:10} Check names and figures.'
The frontend will parse this out and display it as a badge.
"""
import json
import urllib.request
import urllib.parse

SUPABASE_URL = 'https://hpgalybhcztwzfqoluts.supabase.co'
SUPABASE_KEY = 'sb_publishable_RhQ-IyzBQ7k2ibW91-6aoQ_Mk_JY9Tm'
TABLE = 'tasks'

HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'return=representation'
}

def api_request(method, path, data=None, params=None):
    url = f'{SUPABASE_URL}/rest/v1/{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers=HEADERS, method=method)
    if data is not None:
        req.data = json.dumps(data).encode('utf-8')
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode('utf-8')
        return json.loads(body) if body else []

# Fetch all tasks
tasks = api_request('GET', TABLE, params={'select': 'id,title,notes,due_date,area', 'limit': 1000})
print(f'Fetched {len(tasks)} tasks')

# Define time estimates (in minutes) keyed by title substring or suffix
time_map = {
    # Priority 1 — Close the easy loops (20 min total)
    'Book Obsession cinema tickets': 5,
    'Add the cinema booking to the calendar': 3,
    'Add the World Cup watchalong': 3,
    'Send Martin the photo of Issue 4': 2,

    # Priority 2 — Clean the room (40 min total)
    'Remove rubbish': 8,
    'Put clothes away': 8,
    'Clear the desk': 5,
    'Clear the floor': 5,
    'Change bedding if needed': 5,
    'Put Faroes items together': 5,

    # Priority 3 — Elijah Just article (22 min)
    'Complete final proofread — Struan Elijah Just article': 10,
    'Add featured image and metadata — Elijah Just article': 5,
    'Publish Elijah Just article': 5,
    'Save live link for newsletter — Elijah Just article': 2,

    # Priority 4 — Callum Ward article (22 min)
    'Complete final proofread — Callum Ward article': 10,
    'Add featured image and metadata — Callum Ward article': 5,
    'Publish Callum Ward': 5,
    'Save live link for newsletter — Callum Ward article': 2,

    # Priority 5 — Newsletter structure (45 min)
    'Create newsletter structure with subject': 8,
    'Write short newsletter introduction': 8,
    'Add Elijah Just article section to newsletter': 6,
    'Add Callum Ward': 6,
    'Add Genk article placeholder to newsletter': 3,
    'Add Issue 4 or subscription promotion': 5,
    'Add closing section to newsletter': 5,

    # Priority 6 — Dispatch finances (90 min)
    'Enter all missing Dispatch transactions': 30,
    'Compare Dispatch records against bank': 20,
    'Identify any unexplained Dispatch': 15,
    'Calculate what Dispatch owes': 15,

    # Priority 7 — Personal budget (45 min)
    'Record expected income for next month': 5,
    'Add fixed bills and debt payments': 8,
    'Add expected Faroes and travel spending': 8,
    'Set food, transport and discretionary': 8,
    'Decide realistic saving amount': 5,
    'Identify expensive weeks': 5,

    # Priority 8 — Faroes preparation (65 min)
    'flights and check-in': 6,
    'accommodation': 6,
    'match arrangements': 6,
    'festival plans': 6,
    'airport and local transport': 6,
    'travel insurance and health': 6,
    'mobile data and payment': 6,
    'downloaded maps': 5,
    'packing and clothing': 6,
    'remaining bookings': 6,
    'Divide Faroes items': 6,

    # Priority 9 — Genk article (22 min)
    'Complete final proofread — Motherwell 3-4 Genk': 10,
    'Add featured image and metadata — Genk article': 5,
    'Publish Motherwell 3-4 Genk article': 5,
    'Save live link for newsletter — Genk article': 2,

    # Priority 10 — Schedule newsletter (45 min)
    'Add Genk article to newsletter': 8,
    'Tighten newsletter introduction': 8,
    'Check all links in newsletter': 5,
    'Check newsletter subject line': 5,
    'Preview newsletter on desktop': 8,
    'Schedule newsletter for Monday': 5,

    # Priority 11 — Orion V2 (180 min)
    'Write one-paragraph definition of Orion V2': 20,
    'List each Orion V2 feature': 20,
    'Test the Orion V2 HAE data flow': 30,
    'Attempt to restore reliable HAE syncing': 45,
    'Document HAE blocker': 15,
    'Produce one stable Orion V2 build': 30,
    'Move excluded Orion V2 features': 10,

    # Priority 12 — Weather/location (30 min)
    'Decide weather scope for Orion V2': 10,
    'Decide location scope for Orion V2': 10,
    'Record clear decisions on weather': 5,

    # Priority 13 — Frontier Signals (75 min)
    'Create one-page decision document for Frontier Signals': 15,
    'Identify the three most important Frontier Signals deliverables': 10,
    'Determine which Frontier Signals deliverable comes first': 8,
    'Define what Codex should do next for Frontier Signals': 10,
    'Identify what requires my own legal': 10,
    'Create one concrete Codex task for the first Frontier Signals': 10,

    # Priority 14 — Fitness plan (35 min)
    'Decide number of gym sessions': 5,
    'Decide number of runs per week': 5,
    'Decide whether to include one optional Zone 2': 5,
    'Decide adjustments for wrist': 5,
    'Decide how running will be adjusted': 5,
    'Set one measurable goal': 5,
    'Write down fitness sessions': 5,

    # Priority 15 — Plan next week (45 min)
    'Add fixed commitments for next week': 5,
    'Schedule fitness sessions for next week': 5,
    'Add remaining Faroes actions to next week': 5,
    'Schedule one job-search block': 5,
    'Schedule one Frontier Signals block': 5,
    'Schedule one Orion block': 5,
    'Schedule Dispatch work for next week': 5,
    'Schedule protected downtime': 3,
    'Review next week: visible': 3,
}

def match_title(title):
    """Find the matching time estimate for a given title."""
    for pattern, mins in time_map.items():
        if pattern.lower() in title.lower():
            return mins
    return None

updated = 0
no_match = []
for t in tasks:
    mins = match_title(t['title'])
    if mins is None:
        no_match.append(t['title'])
        continue
    
    old_notes = t.get('notes') or ''
    # Strip any existing {t:N} prefix
    import re
    old_notes = re.sub(r'^\{t:\d+\}\s*', '', old_notes)
    new_notes = f'{{t:{mins}}} {old_notes}' if old_notes else f'{{t:{mins}}}'
    
    # Update via PATCH
    api_request('PATCH', f'{TABLE}?id=eq.{t["id"]}', data={'notes': new_notes})
    updated += 1
    if updated % 10 == 0:
        print(f'  Updated {updated}/{len(tasks)}...')

print(f'\nDone! Updated {updated} tasks with time estimates.')
if no_match:
    print(f'No match for {len(no_match)} tasks:')
    for nt in no_match:
        print(f'  - "{nt}"')

#!/usr/bin/env python3
"""
Mark all Steelmen Dispatch todo tasks (including Issue 4 sub-areas) as complete.

Uses the Supabase REST API directly.
Note: Combining `status=eq.todo` with `area=ilike.*` filters doesn't work
in PostgREST, so we query all steelmen-area tasks and filter by status in Python.
"""
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

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
        return json.loads(resp.read().decode('utf-8'))

def find_steelmen_tasks():
    """Find all tasks in any area containing 'Steelmen', then filter for todo status."""
    # Query all tasks in steelmen areas (no status filter — PostgREST can't combine
    # ilike on one column with eq on another this way)
    all_steelmen = api_request('GET', TABLE, params={
        'select': 'id,title,area,status,category',
        'area': 'ilike.*steelmen*',
        'limit': 1000
    })
    # Filter for todo tasks in Python
    todo = [t for t in all_steelmen if t.get('status') == 'todo' or t.get('status') == 'open']
    return todo

def mark_complete(task_ids):
    """Update a list of task IDs to status=done."""
    if not task_ids:
        return []
    now = datetime.now(timezone.utc).isoformat()
    ids_filter = ','.join(task_ids)
    params = {
        'id': f'in.({ids_filter})'
    }
    body = {
        'status': 'done',
        'completed_at': now
    }
    return api_request('PATCH', TABLE, data=body, params=params)

def main():
    print('Querying for Steelmen Dispatch todo tasks (any sub-area)...')
    tasks = find_steelmen_tasks()

    # Group by area for a clean report
    by_area = {}
    for t in tasks:
        a = t.get('area', 'Unknown')
        by_area.setdefault(a, []).append(t)

    total = len(tasks)
    print(f'Found {total} matching todo task(s) across {len(by_area)} area(s):\n')
    for area in sorted(by_area.keys()):
        area_tasks = by_area[area]
        print(f'  [{area}] ({len(area_tasks)} tasks)')
        for t in area_tasks:
            cat = t.get('category', '')
            cat_str = f'  cat: {cat}' if cat else ''
            print(f"    - {t['title']}{cat_str}")

    if not tasks:
        print('\nNo Steelmen Dispatch tasks to update. All done! ✓')
        return

    task_ids = [t['id'] for t in tasks]
    print(f'\nMarking {len(task_ids)} task(s) as complete...')
    updated = mark_complete(task_ids)
    print(f'Successfully updated {len(updated)} task(s).')

    # Verify
    verify = find_steelmen_tasks()
    remaining = len(verify)
    print(f'Remaining todo tasks: {remaining}')
    if remaining == 0:
        print('All Steelmen Dispatch tasks are now complete! ✓')
    else:
        print(f'Warning: {remaining} task(s) still open.')

if __name__ == '__main__':
    main()

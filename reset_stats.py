#!/usr/bin/env python3
"""
Reset stats and clear all completed tasks from Supabase.

1. Deletes ALL rows from the 'events' table (activity log)
2. Deletes ALL rows from the 'tasks' table where status = 'done'
"""
import json
import urllib.request
import urllib.parse
import urllib.error

SUPABASE_URL = 'https://hpgalybhcztwzfqoluts.supabase.co'
SUPABASE_KEY = 'sb_publishable_RhQ-IyzBQ7k2ibW91-6aoQ_Mk_JY9Tm'
TABLE_TASKS = 'tasks'
TABLE_EVENTS = 'events'

HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'return=representation'
}

# A UUID that no real row will ever have — used for "not equal to" to match all rows
NEVER_UUID = '00000000-0000-0000-0000-000000000000'

def api_request(method, path, data=None, params=None):
    url = f'{SUPABASE_URL}/rest/v1/{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers=HEADERS, method=method)
    if data is not None:
        req.data = json.dumps(data).encode('utf-8')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else []
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        print(f'  HTTP Error {e.code}: {body}')
        raise

def fetch_all_ids(table, status_filter=None):
    """Fetch all matching IDs from a table (handles pagination)."""
    all_ids = []
    offset = 0
    limit = 1000
    while True:
        params = {'select': 'id'}
        if status_filter:
            params['status'] = f'eq.{status_filter}'
        params['limit'] = str(limit)
        params['offset'] = str(offset)
        rows = api_request('GET', table, params=params)
        if not rows:
            break
        all_ids.extend(r['id'] for r in rows)
        if len(rows) < limit:
            break
        offset += limit
    return all_ids

def delete_by_ids(table, ids):
    """Delete rows by a list of UUID IDs."""
    if not ids:
        return 0
    # Delete in batches to avoid URL length issues
    batch_size = 100
    deleted = 0
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        ids_param = 'in.(' + ','.join(batch) + ')'
        try:
            result = api_request('DELETE', table, params={'id': ids_param})
            deleted += len(result) if result else 0
            print(f'  Deleted batch of {len(batch)}')
        except Exception as e:
            print(f'  Failed batch: {e}')
    return deleted

def main():
    print('=== Stats Reset & Completed Tasks Clear ===\n')

    # 1. Count before
    print('Counting completed tasks...')
    done_ids = fetch_all_ids(TABLE_TASKS, 'done')
    print(f'  Found {len(done_ids)} completed tasks')

    print('Counting events...')
    event_ids = fetch_all_ids(TABLE_EVENTS)
    print(f'  Found {len(event_ids)} events')

    if len(done_ids) == 0 and len(event_ids) == 0:
        print('\nNothing to clear — already clean.')
        return

    # 2. Delete events (stats reset)
    print(f'\nDeleting {len(event_ids)} events...')
    del_events = 0
    if event_ids:
        del_events = delete_by_ids(TABLE_EVENTS, event_ids)
        print(f'  Deleted {del_events} events')

    # 3. Delete completed tasks
    print(f'\nDeleting {len(done_ids)} completed tasks...')
    del_tasks = 0
    if done_ids:
        del_tasks = delete_by_ids(TABLE_TASKS, done_ids)
        print(f'  Deleted {del_tasks} completed tasks')

    # 4. Verify
    print('\nVerifying...')
    remaining_tasks = fetch_all_ids(TABLE_TASKS, 'done')
    remaining_events = fetch_all_ids(TABLE_EVENTS)
    print(f'  Remaining completed tasks: {len(remaining_tasks)}')
    print(f'  Remaining events: {len(remaining_events)}')

    print(f'\nDone! Removed {del_tasks} completed tasks and {del_events} events.')

if __name__ == '__main__':
    main()

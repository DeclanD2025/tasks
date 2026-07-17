#!/usr/bin/env python3
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

def wait_for_reachability(timeout=300, interval=30):
    start = time.time()
    attempt = 1
    while time.time() - start < timeout:
        print(f'Attempt {attempt}: checking Supabase connectivity...')
        try:
            # Lightweight health check via the tasks table metadata
            api_request('HEAD', TABLE, params={'limit': 0})
            print('Supabase is reachable.')
            return True
        except Exception as e:
            print(f'  Not reachable yet: {e}')
            attempt += 1
            time.sleep(interval)
    raise TimeoutError('Supabase did not become reachable within the timeout period.')

def find_issue4_tasks():
    # Find todo tasks where title or category contains 'Issue 4' (case-insensitive)
    params = {
        'select': 'id,title,category,status',
        'status': 'eq.todo',
        'or': '(title.ilike.*Issue 4*,category.ilike.*Issue 4*)'
    }
    return api_request('GET', TABLE, params=params)

def mark_complete(task_ids):
    if not task_ids:
        return []
    now = datetime.now(timezone.utc).isoformat()
    # Supabase update with IN filter
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
    wait_for_reachability()
    print('Querying for Issue 4 tasks...')
    tasks = find_issue4_tasks()
    print(f'Found {len(tasks)} matching todo task(s):')
    for t in tasks:
        print(f"  - [{t['id']}] {t['title']} (category: {t.get('category')})")
    if not tasks:
        print('No tasks to update.')
        return
    task_ids = [t['id'] for t in tasks]
    print('Marking complete...')
    updated = mark_complete(task_ids)
    print(f'Successfully updated {len(updated)} task(s).')
    # Verify
    verify = find_issue4_tasks()
    print(f'Remaining matching todo tasks after update: {len(verify)}')

if __name__ == '__main__':
    main()

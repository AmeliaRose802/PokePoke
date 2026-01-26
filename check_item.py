#!/usr/bin/env python
"""Check the current state of the item."""
import json
import subprocess
import sys

item_id = sys.argv[1] if len(sys.argv) > 1 else "icm_queue_c#-r587"

result = subprocess.run(['bd', 'show', item_id, '--json'], capture_output=True, text=True, encoding='utf-8')
data = json.loads(result.stdout)
item = data[0] if isinstance(data, list) else data

print(f"Item: {item['id']}")
print(f"Owner: {item.get('owner', 'NONE')}")
print(f"Status: {item.get('status', 'NONE')}")
print(f"Title: {item.get('title', '')}")

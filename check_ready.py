#!/usr/bin/env python
"""Quick script to check bd ready output."""
import json
import subprocess

result = subprocess.run(['bd', 'ready', '--json'], capture_output=True, text=True, encoding='utf-8')
data = json.loads(result.stdout)
print(f"Total items from bd ready: {len(data)}")
print()
for item in data[:10]:
    print(f"{item['id']}: owner={item.get('owner', 'none')}, status={item.get('status', 'unknown')}")

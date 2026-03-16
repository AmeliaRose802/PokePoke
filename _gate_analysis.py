"""Temp script to analyze gate agent stats."""
import json

with open('.pokepoke/gate_rejection_stats.json') as f:
    data = json.load(f)

log = data.get('log', [])
summary = data.get('summary', {})

total = len(log)
passed = sum(1 for c in log if c.get('passed'))
failed = total - passed

print(f"Total gate checks: {total}")
print(f"Passed: {passed} ({passed/total*100:.1f}%)" if total else "")
print(f"Failed: {failed} ({failed/total*100:.1f}%)" if total else "")
print()

print("Summary by model:")
for model, stats in summary.items():
    print(f"  {model}: {json.dumps(stats)}")
print()

# Recent checks (last 20)
print("Last 20 checks:")
for c in log[-20:]:
    status = "PASS" if c.get('passed') else "FAIL"
    item = c.get('item_id', '?')
    model = c.get('gate_model', '?')
    ts = c.get('timestamp', '?')[:19]
    print(f"  {status} | {item:20s} | {model:25s} | {ts}")

# By item — how many times each item was gate-checked
from collections import Counter
item_counts = Counter()
item_passes = Counter()
for c in log:
    item_counts[c.get('item_id', '?')] += 1
    if c.get('passed'):
        item_passes[c.get('item_id', '?')] += 1

print()
print("Items with most gate checks (top 15):")
for item, count in item_counts.most_common(15):
    p = item_passes.get(item, 0)
    print(f"  {item:25s}: {count} checks, {p} passed, {count-p} failed")

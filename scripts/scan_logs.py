"""Scan log files for ANSI escape codes and encoding artifacts."""
import os
import re

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
BRACKET_ANSI_RE = re.compile(r'\[(?:0|1|2|3[0-9]|4[0-7]|9[0-7])m')
# Mojibake from UTF-8 decoded as Latin-1 or similar
MOJIBAKE_RE = re.compile(
    r'\xc3[\x80-\xbf]'  # UTF-8 double-byte sequences decoded wrong
    r'|\xe2\x80[\x90-\xbf]'  # em-dash, smart quotes etc read as raw bytes
    r'|\xc2[\xa0-\xbf]'  # non-breaking space etc
)
# Common visible mojibake text patterns
MOJIBAKE_TEXT_RE = re.compile(
    r'\u00e2\u0080[\u0090-\u00bf]'  # â€" â€™ etc
    r'|[\u00c3][\u00a0-\u00bf]'  # Ã followed by another char
    r'|[\u00c2][\u00a0-\u00bf]'  # Â followed by another char
)
# Control chars (excluding normal whitespace)
CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
# Unicode box drawing and similar that might be artifacts
BOX_DRAWING_RE = re.compile(r'[\u2500-\u257f\u2580-\u259f]')  # ─ │ ├ └ etc
# Emoji that might look garbled on some terminals
EMOJI_RE = re.compile(r'[\U0001f300-\U0001f9ff\u2600-\u26ff\u2700-\u27bf\u2b50\u274c\u2705\u270f\U0001f4ca\U0001f527\u26a0]')

log_dir = r'C:\Users\ameliapayne\PokePoke\logs'
results = {
    'ansi': [], 'bracket_ansi': [], 'mojibake': [],
    'mojibake_text': [], 'control': [], 'box_drawing': [], 'emoji': []
}
files_checked = 0

for root, dirs, files in os.walk(log_dir):
    for fn in files:
        if not fn.endswith('.log'):
            continue
        fpath = os.path.join(root, fn)
        files_checked += 1
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if ANSI_RE.search(line):
                        results['ansi'].append((fpath, i, line.rstrip()[:150]))
                    if BRACKET_ANSI_RE.search(line):
                        results['bracket_ansi'].append((fpath, i, line.rstrip()[:150]))
                    if CONTROL_RE.search(line):
                        results['control'].append((fpath, i, repr(line.rstrip()[:100])))
                    if BOX_DRAWING_RE.search(line):
                        results['box_drawing'].append((fpath, i, line.rstrip()[:150]))
                    if EMOJI_RE.search(line):
                        results['emoji'].append((fpath, i, line.rstrip()[:150]))
        except Exception as e:
            print(f"ERROR reading {fpath}: {e}")

print(f'Files checked: {files_checked}')
print()
for cat, label in [
    ('ansi', 'TRUE ANSI ESCAPE CODES (\\x1b[...)'), 
    ('bracket_ansi', 'BRACKET ANSI PATTERNS ([0m, [32m etc)'),
    ('control', 'CONTROL CHARACTERS'),
    ('box_drawing', 'BOX DRAWING CHARACTERS'),
    ('emoji', 'EMOJI CHARACTERS'),
]:
    count = len(results[cat])
    print(f'{label}: {count} hits')
    if results[cat]:
        unique_files = set(fp for fp, _, _ in results[cat])
        print(f'  In {len(unique_files)} unique files')
        print(f'  Examples (up to 5):')
        for fpath, line_num, text in results[cat][:5]:
            rel = fpath.replace(log_dir + os.sep, '')
            print(f'    {rel}:{line_num}: {text}')
    print()

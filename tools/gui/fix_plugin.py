#!/usr/bin/env python3
"""Fix broken PluginScene class in studio.py"""
with open('/Users/mikeni/lerobot-smolvla-lew/tools/gui/studio.py', 'r') as f:
    lines = f.readlines()

# Find "Z700插拔场景" docstring and comment out everything until next class
bad_start = None
for i, line in enumerate(lines):
    if 'Z700插拔场景' in line and '"""' in line:
        bad_start = i
        break

if bad_start:
    j = bad_start
    while j < len(lines):
        if j > bad_start and (lines[j].startswith('class ') or lines[j].startswith('# ---')):
            break
        lines[j] = '# ' + lines[j]
        j += 1
    print(f'Commented out lines {bad_start+1}-{j}')

with open('/Users/mikeni/lerobot-smolvla-lew/tools/gui/studio.py', 'w') as f:
    f.writelines(lines)
print('Done')

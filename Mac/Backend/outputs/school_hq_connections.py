"""Validated per-user integrations. No shipped accounts or course enrollments."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(root=ROOT):
    path = Path(root) / 'School HQ Study/connections.json'
    if not path.exists():
        return {'courses': [], 'codex_path': ''}
    value = json.loads(path.read_text())
    courses = value.get('courses')
    if not isinstance(courses, list) or len(courses) > 30:
        raise ValueError('Open Genesis Settings and configure your classes.')
    ids, canvas_ids = set(), set()
    for row in courses:
        if not isinstance(row, dict) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,39}', str(row.get('id', ''))) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(row.get('canvas_id', ''))) or not isinstance(row.get('label'), str) or not 1 <= len(row['label'].strip()) <= 80:
            raise ValueError('Invalid class configuration. Review Genesis Settings.')
        if row['id'] in ids or row['canvas_id'] in canvas_ids:
            raise ValueError('Each class and Canvas ID must be unique.')
        ids.add(row['id']); canvas_ids.add(row['canvas_id'])
    return value

def courses(root=ROOT):
    return {row['id']: str(row['canvas_id']) for row in read(root)['courses']}

def labels(root=ROOT):
    return {row['id']: row['label'] for row in read(root)['courses']}


# Plugins: the places Genesis gathers what it needs for the brief (assignments, documents,
# dates, announcements). The planner, the companion and iPhone notes are the core, not plugins. Nothing runs, collects or appears
# until the student picks it in Settings > Plugins (or on first launch).
PLUGINS = {
    'canvas':    'Canvas: reads your classes, assignments, announcements and grades (UCF Webcourses)',
    'calendar':  'Calendar: your Webcourses calendar feed, for due dates Canvas pages miss',
    'email':     'Email: makes course emails searchable in Library (read-only)',
    'professor_sites': 'Professor websites: public course pages some professors keep outside Canvas',
}

def plugins(root=ROOT):
    value = read(root)
    chosen = value.get('plugins') or {}
    on = {name: bool(chosen.get(name)) for name in PLUGINS}
    # The older single switch still counts for professor sites.
    if value.get('cop3330_professor_enabled'): on['professor_sites'] = True
    return on

def enabled(name, root=ROOT):
    return plugins(root).get(name, False)

if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['plugins']:
        print(json.dumps({'plugins': plugins(), 'catalog': PLUGINS}))

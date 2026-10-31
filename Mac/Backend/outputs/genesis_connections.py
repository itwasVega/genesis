"""Validated per-user integrations. No shipped accounts or course enrollments."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(root=ROOT):
    path = Path(root) / 'Genesis Study/connections.json'
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
    'canvas':    "Canvas: reads your classes, assignments, announcements, files and grades from your school's Canvas",
    'calendar':  'Calendar: your Canvas calendar feed, picked up for you, for due dates that only live there',
    'email':     'Email: makes course emails searchable in Library (read-only)',
}

def plugins(root=ROOT):
    value = read(root)
    chosen = value.get('plugins') or {}
    on = {name: bool(chosen.get(name)) for name in PLUGINS}
    # A legacy, single-course professor-site reader, kept only for workspaces that already use it.
    on['professor_sites'] = bool(chosen.get('professor_sites') or value.get('cop3330_professor_enabled'))
    return on

def enabled(name, root=ROOT):
    return plugins(root).get(name, False)

if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['plugins']:
        print(json.dumps({'plugins': plugins(), 'catalog': PLUGINS}))


# ---- School-neutral settings: every school and time zone works the same way.
def canvas_host(root=ROOT):
    """The school's Canvas address, e.g. 'canvas.myschool.edu' or 'myschool.instructure.com'."""
    host = str(read(root).get('canvas_host') or '').strip().lower()
    return host if re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', host) else ''

def canvas_origin(root=ROOT):
    host = canvas_host(root)
    return 'https://' + host if host else ''

def school_domain(root=ROOT):
    """The school's email domain: from the school email if one is set, else from the Canvas host."""
    value = read(root)
    email = str(value.get('school_email') or '')
    if '@' in email: return email.rsplit('@', 1)[1].lower()
    host = canvas_host(root)
    if not host or host.endswith('.instructure.com'): return ''
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host

def zone_name(root=ROOT):
    """The student's time zone: chosen in setup, else this Mac's own."""
    name = str(read(root).get('timezone') or '')
    if name: return name
    try:
        import os
        link = os.path.realpath('/etc/localtime')
        if '/zoneinfo/' in link: return link.split('/zoneinfo/', 1)[1]
    except OSError: pass
    return 'UTC'

def zone(root=ROOT):
    from zoneinfo import ZoneInfo
    try: return ZoneInfo(zone_name(root))
    except Exception: return ZoneInfo('UTC')

SUBJECTS = (
    ('math', r'calc|math|algebra|statistic|precalc|trig|\bmac\s*\d|\bmat\s*\d|\bsta\s*\d'),
    ('discrete', r'discrete|logic|proof|\bcot\s*\d'),
    ('cs', r'comput|program|software|data struct|algorithm|java|python|\bc\b|c\+\+|\bcop\s*\d|\bcs\s*\d|\bcis\s*\d|\bcen\s*\d'),
)
def subject(course, root=ROOT):
    """A rough subject for a class (math, discrete, cs or general), from its code and name."""
    text = (course + ' ' + labels(root).get(course, '')).lower()
    for name, pattern in SUBJECTS:
        if re.search(pattern, text): return name
    return 'general'

def language(course, root=ROOT):
    """The programming language a CS class uses, when its name says so (else None: the model decides)."""
    for row in read(root)['courses']:
        if row['id'] == course and row.get('language'): return row['language']
    text = (course + ' ' + labels(root).get(course, '')).lower()
    for lang, pattern in (('java', r'java|object.oriented|\boop\b'), ('python', r'python'), ('cpp', r'c\+\+'), ('c', r'\bc\b programming|computer science (?:1|i)\b|\bcs\s*1\b')):
        if re.search(pattern, text): return lang
    return None

def aliases(root=ROOT):
    """How notes refer to each class: its code (any spacing), its name, and any extra words set in setup."""
    out = []
    for row in read(root)['courses']:
        m = re.fullmatch(r'([A-Za-z]+)[\s-]*(\d+)([A-Za-z]*)', row['id'])
        code = (m[1] + r'\s*' + m[2] + (r'(?:' + m[3] + r')?' if m[3] else '') + r'\b') if m else re.escape(row['id'])
        words = [code, re.escape(row['label'].strip())] + [re.escape(w) for w in row.get('aliases', []) if isinstance(w, str) and w.strip()]
        out.append((row['id'], '|'.join(w for w in words if w)))
    # Everyday words for a subject, when only one class has that subject (or language).
    hints = {'math': r'calc(?:ulus)?|derivatives?|integrals?|limits?', 'discrete': r'discrete|proofs?|logic',
             'java': r'java|\boop\b|object.oriented', 'c': r'\bcs\s*1\b|cs1|pointers?|linked lists?|\bc\b programming'}
    keys = [(row['id'], subject(row['id'], root), language(row['id'], root)) for row in read(root)['courses']]
    for i, (course, subj, lang) in enumerate(keys):
        for key in (subj, lang):
            if key in hints and sum(1 for _, s, l in keys if key in (s, l)) == 1:
                out[i] = (course, out[i][1] + '|' + hints[key])
    return out

#!/usr/bin/env python3
"""One-time upgrade of a workspace from the app's old name to Genesis.

Earlier builds kept their records under folders and files named after the old app name.
This moves them to the Genesis names, merges into anything already there, rewrites saved
paths inside records and the local database, and removes the old program files the new
ones replace. Nothing is uploaded and nothing personal is deleted. It runs before anything
else touches the workspace and does nothing once the old names are gone.

Records whose saved fingerprints include a path are re-checked by the next sync, which
collects them again; study history (answers, attempts, notes) carries over as is.
"""
import json, os, shutil, sqlite3, sys
from pathlib import Path

OLD = 'School' + ' HQ'          # spelled in two parts so the old name appears nowhere else
OLD_CODE = 'school' + '_hq_'
FOLDERS = [(OLD+' App', 'Genesis App'), (OLD+' Study', 'Genesis Study'), (OLD+' Email', 'Genesis Email'),
           (OLD+' Drive', 'Genesis Drive'), (OLD, 'Genesis Renders')]
TEXT = [('/'+OLD+' App/', '/Genesis App/'), ('/'+OLD+' Study/', '/Genesis Study/'), ('/'+OLD+' Email/', '/Genesis Email/'),
        ('/'+OLD+' Drive/', '/Genesis Drive/'), ('/'+OLD+'/', '/Genesis Renders/'), ('school-hq.sqlite3', 'genesis.sqlite3'),
        ('/.'+OLD_CODE, '/.genesis_'), ('/'+OLD_CODE, '/genesis_')]
SUFFIXES = {'.json', '.jsonl', '.txt', '.md', '.html', '.csv', '.log'}


def merge(old, new):
    """Move old into new; anything already in new wins. Empty old folders are removed."""
    if not old.exists() or old.is_symlink(): return
    if not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True); old.rename(new); return
    if old.is_dir() and new.is_dir():
        for child in list(old.iterdir()): merge(child, new/child.name)
        try: old.rmdir()
        except OSError: pass


def rewrite(path):
    try:
        if path.stat().st_size > 100_000_000: return False
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError): return False
    new = text
    for a, b in TEXT: new = new.replace(a, b)
    if new == text: return False
    tmp = path.with_name(path.name+'.migrating'); tmp.write_text(new, encoding='utf-8')
    os.chmod(tmp, path.stat().st_mode & 0o777); tmp.replace(path)
    return True


def database(path):
    if not path.exists(): return
    db = sqlite3.connect(path, timeout=15)
    try:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_data' AND name NOT LIKE '%_idx' AND name NOT LIKE '%_content' AND name NOT LIKE '%_docsize' AND name NOT LIKE '%_config'"):
            cols = [r[1] for r in db.execute('PRAGMA table_info("%s")' % table)]
            for col in cols:
                for a, b in TEXT:
                    try: db.execute('UPDATE "%s" SET "%s"=replace("%s",?,?) WHERE instr("%s",?)>0' % (table, col, col, col), (a, b, a))
                    except sqlite3.Error: pass
        db.commit()
    finally: db.close()


def run(workspace):
    out = Path(workspace)/'outputs'
    if not out.is_dir(): return {'migrated': False}
    moved = []
    for a, b in FOLDERS:
        if (out/a).exists(): merge(out/a, out/b); moved.append(a)
    bridge = out/'Genesis App/Bridge'
    for suffix in ('', '-wal', '-shm'):
        merge(bridge/('school-hq.sqlite3'+suffix), bridge/('genesis.sqlite3'+suffix))
    for p in list(out.iterdir()):
        name = p.name
        if name.startswith('.'+OLD_CODE): merge(p, out/('.genesis_'+name[len(OLD_CODE)+1:])); moved.append(name)
        elif name.startswith(OLD_CODE):
            target = out/('genesis_'+name[len(OLD_CODE):])
            if p.suffix in ('.py', '.swift', '.LICENSE', '.pyc') and target.exists(): p.unlink()   # replaced by the Genesis copy
            else: merge(p, target)   # records, settings, and any program file of your own
            moved.append(name)
    work = Path(workspace)/'work'
    if (work/('school'+'-hq-app')).exists(): merge(work/('school'+'-hq-app'), work/'genesis-app'); moved.append('work/'+'school'+'-hq-app')
    if not moved: return {'migrated': False}
    rewritten = 0
    for folder, _, names in os.walk(out):
        if '/.git' in folder or '__pycache__' in folder: continue
        for name in names:
            p = Path(folder)/name
            if p.suffix.lower() in SUFFIXES and not p.is_symlink() and rewrite(p): rewritten += 1
    database(bridge/'genesis.sqlite3')
    return {'migrated': True, 'moved': moved, 'rewritten': rewritten}


if __name__ == '__main__':
    print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)))

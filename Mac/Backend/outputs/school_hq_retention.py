#!/usr/bin/env python3
"""Storage cleanup with an explicit dry run.

Keeps: everything referenced by any published plan, receipt of the current request,
assessment source, catalog entry or the library; the newest runs in full; all
academic originals (course PDFs/code are only ever removed when an identical copy
with the same hash is kept). Compacts the duplicate full-text index.
"""
import argparse,hashlib,json,os,re,shutil,sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BRIDGE=ROOT/'School HQ App/Bridge'
KEEP_RUNS=5

def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return {} if default is None else default

def referenced_paths():
 refs=set()
 def walk(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k in ('path','snapshot','location','receipt_file','text_path','solution_path') and isinstance(x,str) and x.startswith('/'):refs.add(str(Path(x).resolve()))
    else:walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for f in (BRIDGE/'Packets').glob('*/*.json'):walk(read(f,{}))
 for f in (BRIDGE/'Courses').glob('*/current.json'):walk(read(f,{}))
 walk(read(BRIDGE/'library.json',{}));walk(read(BRIDGE/'state.json',{}))
 walk(read(ROOT/'School HQ Study/assessments.json',{}));walk(read(ROOT/'School HQ Study/coaching-state.json',{}))
 for f in (ROOT/'School HQ Study/Catalog').glob('*.json'):walk(read(f,{}))
 for f in (BRIDGE/'Receipts').glob('*.json'):walk(read(f,{}))
 return refs

def plan(keep=KEEP_RUNS):
 runs=sorted([p for p in (BRIDGE/'Runs').iterdir() if p.is_dir()],key=lambda p:p.stat().st_mtime,reverse=True) if (BRIDGE/'Runs').exists() else []
 current=(read(BRIDGE/'state.json',{}).get('request') or {}).get('id')
 recent={p.name for p in runs[:keep]}|({current} if current else set())
 refs=referenced_paths();remove=[];kept_bytes=0
 for run in runs:
  if run.name in recent:continue
  for f in run.rglob('*'):
   if not f.is_file():continue
   if str(f.resolve()) in refs:kept_bytes+=f.stat().st_size;continue
   # Academic originals in material/ are kept unless the same bytes live elsewhere.
   if '/material/' in str(f) and not dup_kept(f,refs):continue
   remove.append(f)
 old_results=sorted((BRIDGE/'LocalCanvas').glob('*-result.json'),key=lambda p:p.stat().st_mtime,reverse=True)[keep:] if (BRIDGE/'LocalCanvas').exists() else []
 remove+=[f for f in old_results if str(f.resolve()) not in refs]
 return remove

_hash_cache={}
def digest(p):
 k=str(p)
 if k not in _hash_cache:_hash_cache[k]=hashlib.sha256(Path(p).read_bytes()).hexdigest()
 return _hash_cache[k]
_sizes=None
def dup_kept(f,refs):
 global _sizes
 if _sizes is None:
  _sizes={}
  for r in refs:
   if os.path.isfile(r):_sizes.setdefault(os.path.getsize(r),[]).append(r)
 d=None
 for r in _sizes.get(f.stat().st_size,[]):
  if r==str(f.resolve()):continue
  d=d or digest(f)
  if digest(r)==d:return True
 return False

def compact_db(apply):
 db_path=BRIDGE/'school-hq.sqlite3'
 if not db_path.exists():return {'fts_rows_removed':0}
 import school_hq_local_store as store
 db=store.connect(db_path)
 before=db_path.stat().st_size
 if not apply:
  n=db.execute('SELECT COUNT(*) FROM documents_fts').fetchone()[0];u=db.execute('SELECT COUNT(DISTINCT sha256) FROM documents').fetchone()[0]
  db.close();return {'fts_rows':n,'unique_documents':u,'db_mb':round(before/1e6,1)}
 removed=store.compact_index(db);db.execute('VACUUM');db.close()
 return {'fts_rows_removed':removed,'db_mb_before':round(before/1e6,1),'db_mb_after':round(db_path.stat().st_size/1e6,1)}

def main():
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--keep',type=int,default=KEEP_RUNS);a=p.parse_args()
 files=plan(a.keep);size=sum(f.stat().st_size for f in files)
 result={'files':len(files),'mb':round(size/1e6,1),'database':compact_db(a.apply),'applied':a.apply}
 if a.apply:
  for f in files:
   try:f.unlink()
   except OSError:pass
  for d in sorted((BRIDGE/'Runs').rglob('*'),key=lambda p:-len(p.parts)):
   if d.is_dir() and not any(d.iterdir()):d.rmdir()
 print(json.dumps(result,indent=1))
if __name__=='__main__':main()

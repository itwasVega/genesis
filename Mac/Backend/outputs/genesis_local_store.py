"""App-owned jobs, event log, verified grade history and local search."""
import json,sqlite3,hashlib,os
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
DB=ROOT/'Genesis App/Bridge/genesis.sqlite3'
def now():return datetime.now(timezone.utc).isoformat()
def connect(path=DB):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(path,timeout=15);os.chmod(path,0o600);db.row_factory=sqlite3.Row
 db.executescript('''PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
 CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,requested_at TEXT NOT NULL,state TEXT NOT NULL,pid INTEGER,updated_at TEXT NOT NULL,error TEXT);
 CREATE TABLE IF NOT EXISTS checks(request_id TEXT,source TEXT,started_at TEXT,finished_at TEXT,status TEXT,receipt TEXT,error TEXT,PRIMARY KEY(request_id,source));
 CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,request_id TEXT,at TEXT,stage TEXT,detail TEXT);
 CREATE TABLE IF NOT EXISTS grades(request_id TEXT,course TEXT,captured_at TEXT,basis TEXT,total REAL,payload TEXT,PRIMARY KEY(request_id,course));
 CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY,sha256 TEXT,course TEXT,kind TEXT,indexed_at TEXT);
 CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(path UNINDEXED,course,body);
 PRAGMA user_version=1;''');return db

def event(db,ident,stage,detail):
 db.execute('INSERT INTO events(request_id,at,stage,detail) VALUES(?,?,?,?)',(ident,now(),stage,detail[:2000]));db.commit()
 # Keep bounded diagnostics while retaining all job/check/grade receipts.
 db.execute('DELETE FROM events WHERE seq < (SELECT COALESCE(MAX(seq),0)-3000 FROM events)');db.commit()

def percent(value):
 import re
 m=re.fullmatch(r'\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*',str(value))
 return float(m[1]) if m else None

def grade_delta(previous,current):
 a=percent(previous.get('total_displayed')) if previous else None;b=percent(current.get('total_displayed'))
 basis=current.get('based_only_on_graded_assignments')
 if not previous:return {'previous':None,'current':b,'delta':None,'reason':'First verified local snapshot; no comparable earlier check.'}
 if basis is None or basis!=previous.get('based_only_on_graded_assignments') or a is None or b is None:
  return {'previous':a,'current':b,'delta':None,'reason':'Not comparable: grading basis or displayed total is unverified or changed.'}
 def rows(snapshot):
  result={}
  for x in snapshot.get('assignments',[]):
   key=x.get('source') or x.get('assignment_id') or (x.get('name','')+'|'+x.get('group',''))
   if key in result:return None
   result[key]=x
  return result
 old=rows(previous);new=rows(current);changed=[]
 if old is not None and new is not None:
  for key,x in new.items():
   before=old.get(key)
   if before is None or any(x.get(k)!=before.get(k) for k in ('score_displayed','dropped','status')):
    changed.append({'name':x['name'],'previous':before.get('score_displayed') if before else 'not previously visible','current':x.get('score_displayed'),'dropped':x.get('dropped',False)})
 delta=round(b-a,4)
 if not delta:reason='Posted total unchanged.'
 elif changed:reason='Visible score/status changes: '+', '.join(x['name'] for x in changed)+'. Their exact contribution is unconfirmed until weights, drop rules and point totals are verified.'
 else:reason='Reason unconfirmed: no comparable assignment score change explains this total. Grading rules or visibility may have changed.'
 return {'previous':a,'current':b,'delta':delta,'reason':reason,'changed_assignments':changed,'exact_attribution':False}

def save_grades(db,ident,book):
 result=[]
 for course,snapshot in book.items():
  existing=db.execute('SELECT payload FROM grades WHERE request_id=? AND course=?',(ident,course)).fetchone()
  if existing and json.loads(existing['payload'])!=snapshot:raise ValueError('This request already has a different immutable grade snapshot; start a new Sync')
  old=db.execute('SELECT payload FROM grades WHERE course=? AND request_id<>? ORDER BY captured_at DESC LIMIT 1',(course,ident)).fetchone()
  previous=json.loads(old['payload']) if old else None
  db.execute('INSERT OR IGNORE INTO grades VALUES(?,?,?,?,?,?)',(ident,course,snapshot['captured_utc'],str(snapshot.get('based_only_on_graded_assignments')),percent(snapshot.get('total_displayed')),json.dumps(snapshot)))
  result.append({'course':course,'displayed':snapshot.get('total_displayed','Unknown'),'captured_at':snapshot['captured_utc'],**grade_delta(previous,snapshot)})
 db.commit();return result

def index(db,path,course='',kind='text'):
 """Index text once per unique content. Each sync writes new per-run copies of the
 same Canvas pages; indexing by path stored identical bodies dozens of times."""
 p=Path(path);data=p.read_bytes();sha=hashlib.sha256(data).hexdigest()
 row=db.execute('SELECT sha256 FROM documents WHERE path=?',(str(p),)).fetchone()
 if row and row['sha256']==sha:return False
 body=data.decode('utf-8')
 if '\x00' in body:raise ValueError('Binary content cannot be indexed as text')
 duplicate=db.execute('SELECT 1 FROM documents WHERE sha256=? AND path<>? LIMIT 1',(sha,str(p))).fetchone()
 db.execute('DELETE FROM documents_fts WHERE path=?',(str(p),))
 if not duplicate:db.execute('INSERT INTO documents_fts(path,course,body) VALUES(?,?,?)',(str(p),course,body))
 db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)',(str(p),sha,course,kind,now()));db.commit();return True

def compact_index(db):
 """Remove duplicate full-text rows (same content under several run paths)."""
 keep={}
 for r in db.execute('SELECT path,sha256 FROM documents ORDER BY indexed_at DESC'):
  keep.setdefault(r['sha256'],r['path'])
 kept=set(keep.values());removed=0
 for (path,) in db.execute('SELECT path FROM documents_fts').fetchall():
  if path not in kept:db.execute('DELETE FROM documents_fts WHERE path=?',(path,));removed+=1
 db.commit();return removed

def search(db,query,limit=30):
 terms=[t for t in __import__('re').findall(r'[A-Za-z0-9]{2,}',query)][:8]
 if not terms:return []
 match=' '.join('"'+t+'"' for t in terms)
 rows=db.execute("SELECT path,course,snippet(documents_fts,2,'[',']',' … ',12) AS snip FROM documents_fts WHERE documents_fts MATCH ? ORDER BY rank LIMIT ?",(match,limit)).fetchall()
 return [{'path':r['path'],'course':r['course'],'snippet':r['snip']} for r in rows]

if __name__=='__main__':
 import sys
 if len(sys.argv)>=3 and sys.argv[1]=='search':
  db=connect();print(json.dumps(search(db,' '.join(sys.argv[2:]))));db.close()

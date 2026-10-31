#!/usr/bin/env python3
"""On-demand app-owned sync: Canvas, optional supplements (email, professor site, calendar), then the study engine.

No chat dispatcher, persistent loop, or tokens. Every stage is timed in the event
log (stage `timing:<name>`) so slow steps are visible instead of guessed.
"""
import argparse,fcntl,hashlib,json,os,subprocess,sys,time,tempfile,threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
import genesis_app_bridge as b
import genesis_local_store as store
from genesis_coaching import atomic
from genesis_source_policy import ACTIVE_POLICY_ID
ROOT=Path(__file__).resolve().parent
BRIDGE=ROOT/'Genesis App/Bridge'
POLICY=ROOT/'genesis_local_policy.json'

def stamp():return datetime.now(timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text())
def bridge(*args):
 p=subprocess.run([sys.executable,str(ROOT/'genesis_app_bridge.py'),*args],capture_output=True,text=True,timeout=30)
 if p.returncode:raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else 'Bridge command failed')
 return json.loads(p.stdout)
def active(ident):
 r=read(BRIDGE/'state.json').get('request',{})
 if r.get('id')!=ident or r.get('status')!='processing' or not b.request_fresh(r):raise RuntimeError('Manual request cancelled, replaced or expired')
 return r

def coaching_active(ident):
 state=read(BRIDGE/'state.json');r=state.get('request') or {}
 if r.get('id')==ident and r.get('status')=='complete' and (state.get('brief') or {}).get('id')==ident and b.request_fresh(r):return r
 return active(ident)

def command(ident,name,args=(),timeout=360):
 active(ident);env=dict(os.environ,GENESIS_MANUAL_REQUEST_ID=ident,PYTHONDONTWRITEBYTECODE='1')
 with tempfile.TemporaryFile(mode='w+') as stream:
  p=subprocess.Popen([sys.executable,str(ROOT/name),*args],stdout=stream,stderr=subprocess.STDOUT,text=True,env=env)
  start=time.monotonic()
  try:
   while p.poll() is None:
    active(ident)
    if time.monotonic()-start>timeout:raise RuntimeError(name+' timed out')
    time.sleep(.2)
  finally:
   if p.poll() is None:
    p.terminate()
    try:p.wait(timeout=3)
    except subprocess.TimeoutExpired:p.kill();p.wait()
  stream.seek(0,2);length=stream.tell();stream.seek(max(0,length-16000));output=stream.read()
 log=BRIDGE/'Runs'/ident/(name+'.log');log.parent.mkdir(parents=True,exist_ok=True);log.write_text(output[-16000:]);os.chmod(log,0o600)
 if p.returncode:raise RuntimeError(name+': '+(output.strip().splitlines()[-1] if output.strip() else 'check failed'))
 return output

def snapshot(path,role):return {'path':str(Path(path).resolve()),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'role':role}

def frozen(path,role):
 source=Path(path);data=source.read_bytes();sha=hashlib.sha256(data).hexdigest();target=BRIDGE/'Objects'/(sha+source.suffix)
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():
  if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise RuntimeError('Immutable source object is corrupt')
 else:
  temp=target.with_suffix('.tmp');temp.write_bytes(data);os.chmod(temp,0o600);os.replace(temp,target)
 return snapshot(target,role)

def receipt(ident,source,started,files,coverage,objects,result='checked'):
 r=active(ident);policy=read(POLICY)
 value={'schema':2,'producer':'genesis_local_worker','policy_id':policy['id'],'request_id':ident,'source':source,'result':result,'started_at':started,'checked_at':stamp(),'coverage_limits':coverage,'source_objects':objects,'snapshots':files,'expected_artifacts':[f['path'] for f in files],'partial':False,'error':None,
 'publication':{'required':False,'policy_id':policy['id'],'reason':policy['explanation'],'status':'not_required_local_consumer'}}
 if source=='remarkable' and any(f['role']=='render-validation' for f in files):value['render_validation_version']=2
 p=BRIDGE/'Receipts'/(ident+'-'+source+'.json');atomic(p,value)
 bridge('complete','--request-id',ident,'--source',source,'--detail',coverage,'--evidence','App-owned adapter output and hashes verified; local-first policy; no remote publication claimed.','--receipt',str(p))
 return value

def canvas(ident,started,db):
 job=BRIDGE/'LocalCanvas'/(ident+'-request.json');response=job.with_name(ident+'-result.json')
 replay=None
 prior_receipt=BRIDGE/'Receipts'/(ident+'-canvas.json')
 if response.exists() and prior_receipt.exists():
  prior=read(prior_receipt);native=next((f for f in prior.get('snapshots',[]) if f.get('role')=='canvas-native-response'),None)
  if prior.get('request_id')==ident and native and native.get('sha256')==hashlib.sha256(response.read_bytes()).hexdigest():
   candidate=read(response)
   if candidate.get('request_id')==ident and not candidate.get('error'):
    replay=candidate;started=prior['started_at']
    archived=BRIDGE/'Runs'/ident/('canvas-failed-receipt-'+str(time.time_ns())+'.json');atomic(archived,prior)
    store.event(db,ident,'revalidated:canvas-native','Same-request native bytes rehashed; original capture/start times retained, no new network observation claimed')
 if replay is None:
  if response.exists():
   archive=BRIDGE/'Runs'/ident/('canvas-prior-response-'+str(time.time_ns())+'.json');archive.parent.mkdir(parents=True,exist_ok=True);response.rename(archive)
  atomic(job,{'request_id':ident,'requested_at':started,'courses':__import__('genesis_canvas_capture').COURSES})
  deadline=time.monotonic()+1800
  while not response.exists():
   active(ident)
   if time.monotonic()>deadline:raise RuntimeError('App-owned Canvas browser did not finish within 30 minutes. Connect Canvas in the app; no browser session is inherited from ChatGPT.')
   time.sleep(.3)
  data=read(response)
 else:data=replay
 if data.get('request_id')!=ident or data.get('error'):raise RuntimeError(data.get('error') or 'Wrong Canvas response ID')
 courses=__import__('genesis_canvas_capture').COURSES
 captures=data.get('captures',[]);now=datetime.now(timezone.utc)
 book={};files=[];limits=[]
 for course,cid in courses.items():
  rows=[x for x in captures if x.get('course')==course]
  for kind in ('grades','assignments','files','announcements'):
   row=next((x for x in rows if x.get('kind')==kind),None)
   if not row:raise RuntimeError(course+' '+kind+' was not captured')
   from genesis_verification import timestamp
   start=timestamp(active(ident)['requested_at']);captured=timestamp(row['captured_utc'])
   if not start<=captured<=now:raise RuntimeError('Canvas capture is stale or future dated')
   from urllib.parse import urlparse
   url=urlparse(row['url'])
   if url.hostname!=__import__('genesis_connections').canvas_host() or not url.path.startswith('/courses/'+cid+'/'):raise RuntimeError('Canvas capture course/origin mismatch')
   if not row.get('body','').strip() or row.get('authenticated') is not True:raise RuntimeError('Canvas page is not authenticated/loaded')
   if kind=='grades':
    grades=row.get('grades',{})
    if not grades.get('assignments') or not grades.get('total_displayed'):raise RuntimeError(course+' grade table is incomplete')
    if grades.get('based_only_on_graded_assignments') is None:limits.append(course+': grade calculation basis unverified')
    book[course]={**grades,'source':row['url'],'captured_utc':row['captured_utc']}
   path=BRIDGE/'Runs'/ident/'canvas'/(course+'-'+kind+'.json');atomic(path,row);files.append(snapshot(path,course+':'+kind))
  for i,row in enumerate(x for x in rows if x.get('kind') in ('detail','announcement-detail','page-detail','modules')):
   path=BRIDGE/'Runs'/ident/'canvas'/(course+'-detail-'+str(i)+'.json');atomic(path,row);files.append(snapshot(path,course+':detail'))
   store.index(db,path,course,'canvas-detail')
  limits.extend(data.get('coverage_limits',[]))
 # Keep supplementary lab/module captures as distinct evidence, never substitute main-course totals.
 for i,row in enumerate(x for x in captures if x.get('course') not in courses):
  path=BRIDGE/'Runs'/ident/'canvas'/('supplement-'+str(i)+'.json');atomic(path,row);files.append(snapshot(path,row.get('course','LAB')+':'+row.get('kind','detail')));store.index(db,path,row.get('course','LAB'),'canvas-lab')
 for material in data.get('materials',[]):
  path=Path(material['path']).resolve()
  if BRIDGE.resolve() not in path.parents or not path.is_file() or path.is_symlink():raise RuntimeError('Native material was not safely downloaded')
  raw=path.read_bytes()
  if path.suffix.lower()=='.pdf' and raw[:5]!=b'%PDF-':raise RuntimeError('Native PDF signature invalid')
  if not raw:raise RuntimeError('Downloaded material is empty')
  if material.get('sha256')!=hashlib.sha256(raw).hexdigest():raise RuntimeError('Native downloaded material hash changed')
  files.append(snapshot(path,'practice-pdf' if path.suffix.lower()=='.pdf' else 'course-material'))
  if path.suffix.lower() in ('.zip','.gz'):
   import zipfile
   archive={'sha256':hashlib.sha256(raw).hexdigest(),'policy':'Original only. No extraction or execution. Member listings are untrusted reference metadata.'}
   if path.suffix.lower()=='.zip':
    with zipfile.ZipFile(path) as z:
     info=z.infolist()
     if len(info)>5000:raise RuntimeError('Archive member count exceeds safe listing bound')
     archive['members']=[{'name':x.filename,'bytes':x.file_size,'compressed_bytes':x.compress_size} for x in info]
   else:
    if raw[:2]!=b'\x1f\x8b':raise RuntimeError('GZip signature invalid')
    archive['coverage']='Compressed original retained; binary packet captures are not parsed as lessons.'
   archive_path=BRIDGE/'Objects'/(archive['sha256']+'-archive-v2.json');atomic(archive_path,archive);files.append(snapshot(archive_path,'archive-index'))

 from genesis_canvas_links import collect as collect_public_links
 public_links=collect_public_links(data,BRIDGE/'PublicReferences')
 public_report=BRIDGE/'Runs'/ident/'canvas-public-links.json';atomic(public_report,public_links);files.append(snapshot(public_report,'canvas-public-links'))
 for row in public_links:
  if row.get('path'):files.append(snapshot(row['path'],'public-module-text'));store.index(db,row['path'],row['course'],'public-module-reference')
  else:limits.append(str(row.get('url'))+': '+str(row.get('error')))
 files.append(snapshot(response,'canvas-native-response'))
 path=BRIDGE/'Runs'/ident/'gradebooks.json';atomic(path,book);files.append(snapshot(path,'gradebooks'))
 for f in files:
  if Path(f['path']).suffix.lower() in ('.json','.txt','.java','.c','.h','.md','.in','.out','.html'):
   try:store.index(db,f['path'],f['role'].split(':')[0],'canvas')
   except (UnicodeError,ValueError):
    if f['role']!='course-material':raise
    limits.append(Path(f['path']).name+': original bytes retained; not safely indexable as UTF-8 text.')
 coverage='Five course grade pages plus paginated read-only assignment/file/folder/announcement/module records checked in the app-owned browser. '+ '; '.join(dict.fromkeys(limits))
 if not limits:coverage+='Accessible document downloads verified; individual exclusions/failures remain listed in the native response.'
 verified=receipt(ident,'canvas',started,files,coverage,[{'course':c,'canvas_id':cid} for c,cid in courses.items()])
 job.rename(BRIDGE/'Runs'/ident/'canvas-request.json')
 grade_rows=store.save_grades(db,ident,book);atomic(BRIDGE/'grades.json',{'request_id':ident,'verified_at':stamp(),'courses':grade_rows})
 return verified

@contextmanager
def timed(db,ident,name):
 start=time.monotonic()
 try:yield
 finally:
  try:store.event(db,ident,'timing:'+name,json.dumps({'seconds':round(time.monotonic()-start,2)}))
  except Exception:pass

def progress(ident,step,fraction,label):
 try:bridge('stage','--request-id',ident,'--detail',label,'--progress',json.dumps({'step':step,'fraction':fraction}))
 except Exception:pass

def source_adapters():
 return [('canvas',canvas)]

def main():
 p=argparse.ArgumentParser();p.add_argument('--request-id',required=True);p.add_argument('--skip-coach',action='store_true');args=p.parse_args();ident=args.request_id
 BRIDGE.mkdir(parents=True,exist_ok=True)
 with (BRIDGE/'.local-worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  db=store.connect();r=bridge('status').get('request',{})
  if r.get('id')!=ident or r.get('manual') is not True or not b.request_fresh(r) or r.get('status') not in ('queued','processing'):return
  if r.get('policy_id')!=ACTIVE_POLICY_ID:raise RuntimeError('Start a new Sync; older source policies cannot run.')
  starts=db.execute("SELECT COUNT(*) FROM events WHERE request_id=? AND stage='started'",(ident,)).fetchone()[0]
  if starts>=3:
   bridge('runner-fail','--request-id',ident,'--detail','The local worker stopped repeatedly. Your previous brief and work are preserved. Start a new Sync after checking the worker log.')
   db.execute('UPDATE jobs SET state=?,updated_at=?,error=? WHERE id=?',('failed',stamp(),'Automatic recovery limit reached',ident));db.commit();db.close();return
  if r['status']=='queued':bridge('claim','--request-id',ident)
  atomic(BRIDGE/'worker.json',{'request_id':ident,'pid':os.getpid(),'started_at':stamp(),'state':'running'})
  db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?)',(ident,r['requested_at'],'starting',os.getpid(),stamp(),None));db.commit();store.event(db,ident,'started','On-demand worker acknowledged request')
  failures=[];lock_failures=threading.Lock()
  labels={'canvas':'Canvas'}
  def run_source(source,fn):
   sdb=store.connect()
   try:
    current=read(BRIDGE/'state.json');row=current['sources'].get(source,{})
    if row.get('status')=='ready' and row.get('request_id')==ident:
     from genesis_verification import load_receipt
     if load_receipt(row['verification']['receipt_file'],current['request'],source,ROOT)==row['verification']:
      store.event(sdb,ident,'reused:'+source,'Same-request verified artifacts revalidated; no duplicate source collection');return
    active(ident);started=stamp();bridge('start','--request-id',ident,'--source',source,'--detail','Checking '+labels[source]+'…')
    store.event(sdb,ident,'collecting:'+source,'Adapter started');sdb.execute('INSERT OR REPLACE INTO checks VALUES(?,?,?,?,?,?,?)',(ident,source,started,None,'collecting',None,None));sdb.commit()
    with timed(sdb,ident,source):result=fn(ident,started,sdb)
    sdb.execute('UPDATE checks SET finished_at=?,status=?,receipt=? WHERE request_id=? AND source=?',(stamp(),'verified',json.dumps(result),ident,source));sdb.commit();store.event(sdb,ident,'verified:'+source,result['coverage_limits'])
   except Exception as exc:
    detail=str(exc)[-1600:]
    with lock_failures:failures.append(labels[source]+': '+detail)
    try:bridge('fail','--request-id',ident,'--source',source,'--keep-going','--detail',detail)
    except Exception:pass
    sdb.execute('UPDATE checks SET finished_at=?,status=?,error=? WHERE request_id=? AND source=?',(stamp(),'failed',detail,ident,source));sdb.commit();store.event(sdb,ident,'failed:'+source,detail)
   finally:sdb.close()
  progress(ident,'sources',0.04,'Reading Canvas…')
  with timed(db,ident,'sources'):
   threads=[threading.Thread(target=run_source,args=(source,fn),daemon=True) for source,fn in source_adapters()]
   for t in threads:t.start()
   for t in threads:t.join()
  try:
   if failures:raise RuntimeError(' | '.join(failures))
   active(ident)
   progress(ident,'supplements',0.36,'Reading email and calendar, and looking for past exams…')
   def professor():
    # An optional, workspace-local reader for one professor's public site. It ships with no
    # school's code; it runs only if that workspace has its own module and switch.
    from genesis_connections import enabled
    import importlib.util
    if not enabled("professor_sites") or importlib.util.find_spec("genesis_cop3330") is None: return
    module=importlib.import_module("genesis_cop3330");course=getattr(module,"COURSE",None) or "professor-site"
    pdb=store.connect()
    try:
     store.event(pdb,ident,'collecting:professor-site','Checking public professor materials; Canvas collection retained')
     with timed(pdb,ident,'professor-site'):
      result=module.collect(BRIDGE,ident,BRIDGE/'Receipts'/(ident+'-canvas.json') if (BRIDGE/'Receipts'/(ident+'-canvas.json')).exists() else None,guard=lambda:active(ident))
     store.event(pdb,ident,'checked:professor-site',result['professor_site']['status']+'; '+str(result['professor_site']['verified_materials'])+' verified materials')
     for material in result['professor_site']['materials']:
      if material.get('text_path'):
       try:store.index(pdb,material['text_path'],course,'professor-instruction')
       except (UnicodeError,ValueError):pass
    except Exception as exc:
     atomic(BRIDGE/'Runs'/ident/(course+'-course-record.json'),{'course':course,'request_id':ident,'professor_site':{'status':'failed','detail':str(exc)[:500]},'coverage_limits':['Website failure does not replace or pass Canvas. Previous instructional objects preserved.']})
     store.event(pdb,ident,'failed:professor-site','Supplemental website check failed; Canvas readiness is independent')
    finally:pdb.close()
   def calendar():
    from genesis_connections import enabled
    if not enabled('calendar'):return
    cdb=store.connect()
    try:
     from genesis_optional_sources import collect as collect_optional
     with timed(cdb,ident,'calendar'):collect_optional(BRIDGE,ident)
    except Exception:
     store.event(cdb,ident,'optional-sources:failed','Calendar supplement could not finish; no freshness claimed.')
    finally:cdb.close()
   def mail():
    from genesis_connections import enabled
    if not enabled('email'):return
    mdb=store.connect()
    try:
     import genesis_mail
     with timed(mdb,ident,'mail'):result=genesis_mail.collect()
     for path in result.get('paths',[]):
      try:store.index(mdb,path,'Email','mail')
      except (UnicodeError,ValueError):pass
     store.event(mdb,ident,'optional-mail:'+result.get('status','unknown'),str(result.get('new',0))+' new course messages')
    except Exception as exc:
     store.event(mdb,ident,'optional-mail:failed','Email supplement could not finish ('+type(exc).__name__+'); Canvas readiness is independent.')
    finally:mdb.close()
   def scout():
    # Past exams, practice exams, syllabi and the professor's pages, found on the school's own
    # site. Always on: it only runs for a class when something new could be found.
    sdb=store.connect()
    try:
     import genesis_scout
     with timed(sdb,ident,'scout'):result=genesis_scout.run(ident,guard=lambda:active(ident))
     for record in result.get('records',[]):
      for m in record['materials']:
       if m.get('text_path'):
        try:store.index(sdb,m['text_path'],record['course'],'found-online')
        except (UnicodeError,ValueError):pass
     store.event(sdb,ident,'scout:'+result['status'],json.dumps(result['classes'])[:400])
    except Exception as exc:
     store.event(sdb,ident,'scout:failed','Looking for past exams could not finish ('+type(exc).__name__+'); nothing else depends on it.')
    finally:sdb.close()
   threads=[threading.Thread(target=f,daemon=True) for f in (professor,calendar,mail,scout)]
   for t in threads:t.start()
   for t in threads:t.join()
   active(ident)
   if not bridge('gate').get('ready'):raise RuntimeError('Same-request local receipt gate did not pass')
   from genesis_library import main as refresh_library
   with timed(db,ident,'library'):refresh_library()
   bridge('sync-complete','--request-id',ident)
   if not args.skip_coach:
    import genesis_engine as engine
    with timed(db,ident,'engine'):engine.run(ident,db=db,progress=lambda step,fraction,label:progress(ident,step,fraction,label),guard=lambda:coaching_active(ident))
   store.event(db,ident,'complete','Verified source run complete'+(' without coaching (explicit diagnostic)' if args.skip_coach else ' and Daily Brief published'))
   db.execute('UPDATE jobs SET state=?,updated_at=? WHERE id=?',('sources_verified' if args.skip_coach else 'complete',stamp(),ident));db.commit()
  except Exception as exc:
   detail=str(exc)[-2000:]
   state=read(BRIDGE/'state.json')
   published=(state.get('request') or {}).get('id')==ident and (state.get('request') or {}).get('status')=='complete' and (state.get('brief') or {}).get('id')==ident
   terminal='superseded' if (state.get('request') or {}).get('id')!=ident else (state.get('request') or {}).get('status')
   if terminal in ('cancelled','superseded'):
    store.event(db,ident,terminal,'Worker stopped after request cancellation/replacement; saved brief preserved')
    db.execute('UPDATE jobs SET state=?,updated_at=?,error=? WHERE id=?',(terminal,stamp(),None,ident));db.commit()
    return
   if published:
    store.event(db,ident,'post-publication-warning',detail)
    db.execute('UPDATE jobs SET state=?,updated_at=?,error=? WHERE id=?',('complete',stamp(),None,ident));db.commit()
    return
   try:bridge('runner-fail','--request-id',ident,'--detail',detail)
   except Exception:pass
   db.execute('UPDATE jobs SET state=?,updated_at=?,error=? WHERE id=?',('failed',stamp(),detail,ident));db.commit();store.event(db,ident,'failed',detail)
  finally:
   atomic(BRIDGE/'worker.json',{'request_id':ident,'pid':os.getpid(),'finished_at':stamp(),'state':'stopped'})
   db.close()
if __name__=='__main__':
 try:main()
 except Exception as exc:
  try:
   ident=sys.argv[sys.argv.index('--request-id')+1]
   bridge('runner-fail','--request-id',ident,'--detail','Local worker stopped: '+str(exc)[-1200:])
  except Exception:pass
  print('Local worker stopped: '+str(exc),file=sys.stderr);sys.exit(1)


#!/usr/bin/env python3
"""Local UI bridge. No cache, credentials, network or collector access."""
import argparse, json, os, fcntl, uuid, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent
STORE=ROOT/'Genesis App'/'Bridge'
from genesis_source_policy import ACTIVE_SOURCES,ACTIVE_POLICY_ID,required_sources
SOURCES=list(ACTIVE_SOURCES)
def now():return datetime.now(timezone.utc).isoformat()
def base():return {'schema':1,'request':None,'sources':{s:{'status':'waiting','detail':'Waiting for your next source check','checked_at':None} for s in SOURCES},'events':[],'brief':None}
def write(p,d):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(d,indent=2)+'\n');os.replace(t,p)
def event(d,title,body):
 d['events'].append({'id':str(uuid.uuid4()),'title':title,'body':body,'at':now()});d['events']=d['events'][-80:]
def eligible_date(r):
 t=datetime.fromisoformat(r['requested_at']).astimezone(__import__('genesis_connections').zone())
 return r.get('eligible_date') or (t.date()+timedelta(days=1 if t.hour>=22 else 0)).isoformat()
def parse_stamp(value):
 try:
  stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else None
  if stamp is None:return None
  return stamp if stamp.tzinfo is not None else None
 except (ValueError,TypeError):return None
def request_fresh(r):
 stamp=parse_stamp(r.get('requested_at'))
 if stamp is None or r.get('manual') is not True:return False
 age=(datetime.now(timezone.utc)-stamp).total_seconds()
 return 0<=age<=7200
def ready(d):
 r=d.get('request')
 if not r or r.get('status') not in ('processing','complete') or not request_fresh(r):return False
 started=parse_stamp(r.get('requested_at'));current=datetime.now(timezone.utc)
 for key in required_sources(r):
  row=d.get('sources',{}).get(key,{})
  checked=parse_stamp(row.get('checked_at'))
  if (row.get('request_id')!=r.get('id') or row.get('status')!='ready' or not checked
      or not started<=checked<=current or not str(row.get('evidence') or '').strip()):return False
  try:
   from genesis_verification import load_receipt
   v=row.get('verification',{})
   actual=load_receipt(v.get('receipt_file',''),r,key,ROOT)
   if actual!=v:return False
  except (OSError,ValueError,KeyError,TypeError):return False
 return True
def active_request(d,ident):
 r=d.get('request')
 if not r or ident!=r.get('id') or r.get('status')!='processing' or not request_fresh(r):
  raise ValueError('Requires the current fresh processing manual request')
 return r
def record_history(d):
 r=d.get('request')
 if not r:return
 item={**r,'sources':json.loads(json.dumps(d['sources']))}
 if item.get('started_at') and item.get('finished_at'):
  item['duration_seconds']=max(0,(datetime.fromisoformat(item['finished_at'])-datetime.fromisoformat(item['started_at'])).total_seconds())
 h=d.setdefault('history',[]);h[:]=[x for x in h if x['id']!=r['id']];h.append(item)
 # History is preserved; UI displays the most recent runs.
def apply(d,a):
 if a.action=='test-event':
  raise ValueError('reMarkable notifications and collection have been removed')
 if a.action=='request':
  if d.get('request') and d['request']['status'] in ('queued','processing') and request_fresh(d['request']):return {'status':'already queued','request':d['request']}
  if d.get('request'):record_history(d)
  ident=str(uuid.uuid4());d['request']={'id':ident,'requested_at':now(),'status':'queued','confirmed_device_sync':False,'manual':True}
  policy=getattr(a,'policy',None) or ACTIVE_POLICY_ID
  if policy:
   if policy!=ACTIVE_POLICY_ID:raise ValueError('New requests require the active Canvas policy')
   configured=json.loads((ROOT/'genesis_local_policy.json').read_text())
   if configured['id']!=policy or configured['required_sources']!=SOURCES:raise ValueError('Local policy must require Canvas')
   d['request']['policy_id']=policy
   d['request']['policy_sha256']=__import__('hashlib').sha256((ROOT/'genesis_local_policy.json').read_bytes()).hexdigest()
  d['request']['eligible_date']=datetime.now(__import__('genesis_connections').zone()).date().isoformat()
  if getattr(a,'context_file',None):
   from genesis_brief_context import attach
   attach(ROOT,d['request'],a.context_file)
  d['sources']={s:{'status':'queued','detail':'Waiting for the on-demand worker','request_id':ident,'checked_at':None} for s in SOURCES}
  event(d,'Source checks queued','Starting the app-owned local worker.' if policy else 'Your manual request is queued. Collection starts when the background chat receives it.');return d['request']
 if a.action=='cancel':
  if a.request_id and (not d.get('request') or a.request_id!=d['request']['id']):raise ValueError('Request changed; cancellation refused')
  if d.get('request') and d['request']['status'] in ('queued','processing'):
   d['request'].update(status='cancelled',finished_at=now(),detail=a.detail or 'Cancelled');record_history(d)
  return {'status':'cancelled'}
 if a.action=='stage':
  active_request(d,a.request_id)
  d['request'].setdefault('started_at',now());d['request']['stage']=a.detail
  if getattr(a,'progress',None):
   value=json.loads(a.progress)
   if not isinstance(value,dict) or not isinstance(value.get('step'),str) or not 0<=float(value.get('fraction',0))<=1:raise ValueError('Invalid progress')
   d['request']['progress']={'step':value['step'],'fraction':round(float(value['fraction']),3),'label':a.detail,'at':now()}
  return d['request']
 if a.action=='sync-complete':
  if not ready(d) or a.request_id!=d['request']['id']:raise ValueError('Sources not ready for this request')
  d['request']['sync_completed_at']=now();d['last_successful_sync']=d['request']['sync_completed_at']
  d['request']['counts']=json.loads(a.counts) if a.counts else {}
  record_history(d);event(d,'Sources checked','Canvas checked. Generating your plan.');return d['request']
 if a.action=='runner-fail':
  if not d.get('request') or a.request_id!=d['request']['id']:raise ValueError('Request changed')
  if d['request'].get('status') not in ('queued','processing'):
   return {'status':'ignored','reason':'Request already terminal; late worker failure cannot overwrite it'}
  d['request']['status']='blocked';d['request']['stage']='Sync needs attention';d['request']['detail']=a.detail;d['request']['finished_at']=now()
  for key,row in d['sources'].items():
   if row['status']=='collecting':row.update(status='interrupted',detail='Check stopped before verification; the manual sync needs attention.')
  record_history(d)
  event(d,'Genesis needs attention',a.detail);return d['request']
 if a.action=='remind':
  day=datetime.now().astimezone(__import__('zoneinfo').__import__('genesis_connections').zone()).date().isoformat()
  if d.get('last_reminder')!=day and not ready(d):
   d['last_reminder']=day;event(d,'Your plan is waiting for a sync','Open Genesis and Sync to check Canvas.')
  return {'status':'waiting for manual sync' if not ready(d) else 'ready'}
 if a.action=='status':return d
 if a.action=='resume':
  r=d.get('request')
  if r and r.get('policy_id')!=ACTIVE_POLICY_ID:raise ValueError('Source requirements changed. Start a new Sync.')
  if not r or a.request_id!=r['id'] or not r.get('manual') or r.get('status')!='blocked' or not request_fresh(r) or not a.detail:raise ValueError('Resume requires the current fresh blocked manual request and a repair reason')
  if len(r.get('retry_history',[]))>=2:raise ValueError('Retry limit reached; a new manual request is required')
  r.setdefault('retry_history',[]).append({'at':now(),'previous_failure':r.get('detail'),'repair':a.detail})
  r['status']='processing';r.pop('finished_at',None);r['detail']=a.detail;r['stage']='Retrying source checks…'
  event(d,'Resuming your sync',a.detail);return r
 if a.action=='claim':
  if getattr(a,'request_id',None) and a.request_id!=(d.get('request') or {}).get('id'):raise ValueError('Request changed; claim refused')
  if not d.get('request') or d['request']['status']!='queued' or not request_fresh(d['request']):return {'status':'nothing fresh queued'}
  d['request']['status']='processing';d['request'].setdefault('started_at',now());return d['request']
 if a.action in ('start','complete','fail'):
  if a.source not in SOURCES:raise ValueError('Unknown source')
  active_request(d,a.request_id)
  if a.action=='complete' and (not str(a.evidence or '').strip() or d['sources'][a.source].get('status')!='collecting'):
   raise ValueError('Completion needs a started check and verified evidence')
  verification=None
  if a.action=='complete':
   from genesis_verification import load_receipt
   if not getattr(a,'receipt',None):raise ValueError('Structured collection and cloud-readback receipt required')
   verification=load_receipt(a.receipt,d['request'],a.source,ROOT)
  row=d['sources'][a.source]
  row.update({'status':{'start':'collecting','complete':'ready','fail':'blocked'}[a.action],'detail':a.detail or a.action,'updated_at':now()})
  if a.request_id:row['request_id']=a.request_id
  elif d.get('request') and d['request']['status'] in ('queued','processing'):row['request_id']=d['request']['id']
  if a.action=='complete':
   if not a.evidence:raise ValueError('Completion requires evidence')
   row.update({'checked_at':now(),'evidence':a.evidence,'verification':verification})
  if a.action=='start':
   row.pop('checked_at',None);row.pop('evidence',None);row.pop('verification',None)
   event(d,a.source.title()+' collection started',row['detail'])
  if a.action=='fail':
   event(d,a.source.title()+' needs attention',row['detail'])
   if d.get('request') and not getattr(a,'keep_going',False):
    d['request'].update(status='blocked',finished_at=now(),detail=row['detail'])
    for key,other in d['sources'].items():
     if other['status']=='collecting':other.update(status='interrupted',detail='Check stopped before verification after another source failed.')
    record_history(d)
   elif d.get('request'):record_history(d)
  return row
 if a.action=='gate':return {'ready':ready(d),'request':d.get('request'),'sources':d['sources']}
 if a.action=='publish':
  if not ready(d):raise ValueError('Brief held: every required source must pass for this request')
  if d['request'].get('policy_id') in ('local-first-v1',ACTIVE_POLICY_ID):
   from genesis_publication import publish
   return publish(d,a,ROOT,STORE)
  from genesis_coaching import validate_packet,load,record_packet,persist,atomic
  supplied=getattr(a,'packet',None)
  if not supplied:raise ValueError('Structured coaching packet required; see Coaching packet workflow.md')
  p=Path(supplied).resolve();allowed=ROOT/'Genesis Study'
  if allowed.resolve() not in p.parents or p.suffix!='.json':raise ValueError('Packet must be inside Genesis Study')
  packet=json.loads(p.read_text());date=packet.get('date')
  if date!=datetime.now(__import__('genesis_connections').zone()).date().isoformat():raise ValueError('New brief needs the current Eastern date')
  with (allowed/'.coaching.lock').open('a') as coaching_lock:
   fcntl.flock(coaching_lock,fcntl.LOCK_EX)
   learning=load(ROOT);tasks,rubrics=validate_packet(packet,ROOT,learning)
   # Solutions are excluded from the UI brief and full public checklist.
   rubric_file=allowed/(date+' - private rubrics.json');atomic(rubric_file,rubrics)
   registry=allowed/'exercise-rubrics.json';stored=json.loads(registry.read_text()) if registry.exists() else {};stored.update(rubrics);atomic(registry,stored)
   lines=['# '+date+' — '+packet['title'],'',packet['source_limits'],'']
   for t in tasks:
    lines.extend(['- [ ] **'+str(t['number'])+'. '+t['title']+'**',t['body'],'','Why: '+t['reason'],''])
    for src in t['sources']:
     if src.get('location'):lines.append('Source: ['+src['label']+'](<'+src['location']+'>) — '+src['section'])
   checklist=allowed/(date+' - exact checklist.md');checklist.write_text('\n'.join(lines))
   record_packet(packet,tasks,learning);persist(learning,ROOT)
  brief={'id':d['request']['id'],'date':date,'generated_at':now(),'title':packet['title'],'subtitle':packet['subtitle'],'tasks':tasks,'source_check':d['sources'].copy(),'file':str(checklist),'schema':2,'source_limits':packet['source_limits']}
  write(STORE/(date+'-brief.json'),brief);d['brief']=brief;d['request'].update(status='complete',finished_at=now(),stage='All caught up');record_history(d)
  event(d,'Your Daily Brief is ready',str(len(tasks))+' ordered tasks, grounded in the completed source checks.');return {'status':'published','tasks':len(tasks)}
 raise ValueError('Unknown action')
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['request','status','claim','resume','start','complete','fail','gate','publish','remind','runner-fail','cancel','stage','sync-complete','test-event']);p.add_argument('--source');p.add_argument('--detail');p.add_argument('--evidence');p.add_argument('--receipt');p.add_argument('--policy');p.add_argument('--context-file');p.add_argument('--request-id');p.add_argument('--checklist');p.add_argument('--packet');p.add_argument('--counts');p.add_argument('--keep-going',action='store_true');p.add_argument('--progress');a=p.parse_args()
 STORE.mkdir(parents=True,exist_ok=True)
 with (STORE/'.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);path=STORE/'state.json';d=json.loads(path.read_text()) if path.exists() else base()
  recovered=False
  if (STORE/'current-publication.json').exists():
   from genesis_publication import recover
   recovered=recover(d,ROOT,STORE)
  expired=False
  if d.get('request') and d['request']['status'] in ('queued','processing') and not request_fresh(d['request']):
   d['request'].update(status='blocked',finished_at=now(),detail='This unfinished manual request expired. Start a new sync.');record_history(d);expired=True;event(d,'A fresh sync is needed','This unfinished request expired. Start a new Sync.')
  result=apply(d,a)
  if recovered or expired or a.action not in ['status','gate']:write(path,d)
  print(json.dumps(result))
if __name__=='__main__':main()

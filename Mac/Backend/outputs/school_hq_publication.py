"""Immutable local coaching packets with one atomic current pointer and recovery."""
import copy,fcntl,hashlib,json,os,shutil,tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import school_hq_coaching as c

def hash_file(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def durable_json(path,value):
 c.atomic(path,value)
 with Path(path).open('rb') as f:os.fsync(f.fileno())

def package_valid(folder):
 manifest=read(folder/'manifest.json')
 if manifest.get('schema')!=1 or not manifest.get('files'):raise ValueError('Incomplete publication manifest')
 for name,sha in manifest['files'].items():
  if Path(name).name!=name or (folder/name).is_symlink() or hash_file(folder/name)!=sha:raise ValueError('Publication artifact missing or corrupt')
 return manifest

def project(folder,d,root,store):
 manifest=package_valid(folder);ident=manifest['request_id'];brief=read(folder/'brief.json')
 if (d.get('request') or {}).get('id')!=ident:raise ValueError('Committed publication belongs to another request')
 study=root/'School HQ Study'
 with (study/'.coaching.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  state=c.load(root);packet=read(folder/'packet.json');tasks=brief['tasks'];rubrics=read(folder/'rubrics.json')
  # Idempotently add assignments to the latest state. Never restore an old
  # coaching-state snapshot over newer actual student attempts.
  c.record_packet(packet,tasks,state)
  registry=study/'exercise-rubrics.json';old=read(registry) if registry.exists() else {};old.update(rubrics);durable_json(registry,old)
  c.persist(state,root)
 # Refresh the disposable projection from the latest authentic learning state.
 from school_hq_preparation import build as prepare
 durable_json(store/'preparation.json',prepare(root,brief_override=brief))
 d['brief']=brief;d['request'].update(status='complete',finished_at=brief['generated_at'],stage='Daily Brief ready')
 from school_hq_app_bridge import record_history,event
 record_history(d)
 if not any(e.get('publication_id')==ident for e in d.get('events',[])):
  event(d,'Your Daily Brief is ready',str(len(tasks))+' ordered tasks from the verified local request.');d['events'][-1]['publication_id']=ident
 durable_json(folder/'projected.json',{'request_id':ident,'projected_at':c.stamp()})
 return d

def recover(d,root,store):
 pointer=store/'current-publication.json'
 if not pointer.exists():return False
 p=read(pointer);folder=store/'Packets'/p['request_id']
 if folder.parent!=store/'Packets' or hash_file(folder/'manifest.json')!=p['manifest_sha256']:raise ValueError('Current publication pointer invalid')
 if (d.get('request') or {}).get('id')!=p['request_id']:return False
 if d['request'].get('status') not in ('processing','complete'):return False
 if (d.get('brief') or {}).get('id')==p['request_id'] and (folder/'projected.json').exists():return False
 project(folder,d,root,store);return True

def publish(d,args,root,store,interrupt=None):
 supplied=getattr(args,'packet',None)
 if not supplied:raise ValueError('Structured coaching packet required')
 path=c.contained(supplied,root/'School HQ Study');packet=read(path)
 if packet.get('date')!=datetime.now(__import__('school_hq_connections').zone()).date().isoformat():raise ValueError('New brief needs current Eastern date')
 ident=d['request']['id'];destination=store/'Packets'/ident
 if destination.exists():
  manifest=package_valid(destination)
  if manifest['packet_sha256']!=hash_file(path):raise ValueError('This request already has a different committed packet; start a new request')
  durable_json(store/'current-publication.json',{'request_id':ident,'manifest_sha256':hash_file(destination/'manifest.json')})
  project(destination,d,root,store);return {'status':'recovered','tasks':len(d['brief']['tasks'])}
 from school_hq_source_use import validate as validate_source_use
 source_use_summary=validate_source_use(packet,root,ident)
 from school_hq_brief_context import validate as validate_context
 source_use_summary+=validate_context(packet,root,d['request'])
 source_limits=packet['source_limits']+('\n\n'+'\n'.join(source_use_summary) if source_use_summary else '')
 if d['request'].get('policy_id')=='local-first-v2':source_limits+='\n\nreMarkable collection is disabled. Saved notes are dated references only and were not refreshed or checked for this request.'
 study=root/'School HQ Study'
 with (study/'.coaching.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);state=c.load(root);tasks,rubrics=c.validate_packet(packet,root,state)
  from school_hq_preparation import build as prepare
  projected=copy.deepcopy(state);c.record_packet(packet,tasks,projected)
  preparation=prepare(root,brief_override={'id':ident,'date':packet['date'],'tasks':tasks},state_override=projected)
  order={key:i for i,key in enumerate(preparation['task_order'])}
  if not packet.get('engine_order'):tasks.sort(key=lambda task:(task.get('context_addition',False),order.get(task['id'],len(order))))
  else:tasks.sort(key=lambda task:task.get('context_addition',False))
  for i,task in enumerate(tasks):task['number']=i+1
  parent=store/'Packets';parent.mkdir(parents=True,exist_ok=True);folder=Path(tempfile.mkdtemp(prefix='.staging-',dir=parent))
  try:
   lines=['# '+packet['date']+' — '+packet['title'],'',source_limits,'']
   for t in tasks:lines.extend(['- [ ] **'+str(t['number'])+'. '+t['title']+'**',t['body'],'','Why: '+t['reason'],''])
   checklist=folder/'checklist.md';checklist.write_text('\n'.join(lines))
   brief={'id':ident,'date':packet['date'],'generated_at':c.stamp(),'title':packet['title'],'subtitle':packet['subtitle'],'tasks':tasks,'source_check':copy.deepcopy(d['sources']),'file':str(destination/'checklist.md'),'schema':2,'source_limits':source_limits,'publication_policy':d['request'].get('policy_id'),'preparation_version':preparation['version']}
   for name,value in [('packet.json',packet),('rubrics.json',rubrics),('brief.json',brief),('source-receipts.json',copy.deepcopy(d['sources'])),('preparation.json',preparation)]:durable_json(folder/name,value)
   manifest={'schema':1,'request_id':ident,'packet_sha256':hash_file(path),'files':{p.name:hash_file(p) for p in folder.iterdir() if p.is_file()}}
   durable_json(folder/'manifest.json',manifest);package_valid(folder)
   if interrupt:interrupt('staged')
   os.replace(folder,destination)
   # This pointer is the only publication commit. Projection is recoverable.
   durable_json(store/'current-publication.json',{'request_id':ident,'manifest_sha256':hash_file(destination/'manifest.json')})
   if interrupt:interrupt('committed')
  finally:
   if folder.exists():shutil.rmtree(folder)
 project(destination,d,root,store)
 return {'status':'published','tasks':len(tasks),'transaction':ident}

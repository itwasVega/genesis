"""Auditable practice-source consideration; not proof of reading or mastery.

Only future versioned coaching manifests opt in. A successful download never
counts as use. The original same-request collection gate is unchanged.
"""
import hashlib,json,re
from pathlib import Path

def read(path,default):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError):return default

def candidates(root,preparation):
 root=Path(root);library=read(root/'Genesis App/Bridge/library.json',{})
 active={e['course'] for e in preparation.get('assessments',[]) if e.get('active') and e.get('source_verified') and not e.get('stale')}
 result=[];seen=set()
 for a in library.get('assets',[]):
  if a.get('course') not in active:continue
  if a.get('verification_state')!='verified_bytes_not_learning_coverage':continue
  title=a.get('title','');category=a.get('category','')
  if category!='sample_questions' and not (re.search(r'\b(sample|mock)\b',title,re.I) and not re.search(r'solution|answer|key',title,re.I)):continue
  p=Path(a['path'])
  try:p.resolve().relative_to(root.resolve())
  except ValueError:continue
  if not p.is_file() or p.is_symlink():continue
  digest=hashlib.sha256(p.read_bytes()).hexdigest();key=(a['course'],digest)
  if key in seen:continue
  if a.get('sha256') and digest!=a['sha256']:raise ValueError('Practice-source hash changed: '+title)
  seen.add(key);result.append({'id':a['course']+':'+digest[:24],'course':a['course'],'title':title,'path':str(p.resolve()),'sha256':digest,'page_count':a.get('page_count'),'category':category or 'sample_candidate','source_url':a.get('source_url'),'selection_limit':'Course/category match only; inspect current assessment scope. Not automatically read, assigned or mastered.'})
 return {'schema':1,'required_decisions':result,'limit':'Coach-declared use with hash/citation checks, not a guarantee that all relevant material was discovered or understood.'}

def validate(packet,root,request_id):
 root=Path(root);manifest=read(root/'Genesis App/Bridge/Runs'/request_id/'source-manifest.json',{})
 contract=manifest.get('source_use_contract')
 if not contract:return []
 if contract.get('schema')!=1 or manifest.get('request_id')!=request_id:raise ValueError('Invalid practice-source consideration contract')
 required=contract.get('required_decisions',[])
 if not required:return []
 entries=packet.get('source_use',[])
 if not isinstance(entries,list) or any(not isinstance(x,dict) for x in entries):raise ValueError('source_use must be a list of practice-source decisions')
 ids=[x.get('id') for x in entries]
 if any(not isinstance(ident,str) or not ident for ident in ids):raise ValueError('Practice-source decisions need string IDs')
 if len(ids)!=len(set(ids)):raise ValueError('Duplicate practice-source decision')
 indexed={x.get('id'):x for x in entries};summaries=[]
 for item in required:
  entry=indexed.get(item['id'])
  if not entry:raise ValueError('Missing practice-source decision: '+item['title'])
  p=Path(item['path']);p.resolve().relative_to(root.resolve())
  if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256'] or entry.get('sha256')!=item['sha256']:raise ValueError('Practice-source verification changed: '+item['title'])
  decision=entry.get('decision');reason=entry.get('reason','');pages=entry.get('pages_read',[])
  if decision not in ('used','deferred','not_read') or not isinstance(reason,str) or not reason.strip() or len(reason)>1200:raise ValueError('Practice source needs a specific use/defer/not-read reason')
  if not isinstance(pages,list) or any(type(n)!=int or n<1 or (item.get('page_count') and n>item['page_count']) for n in pages):raise ValueError('Invalid inspected practice-source pages')
  if decision=='used':
   problems=entry.get('problems',[])
   if p.suffix.lower()=='.pdf' and not pages:raise ValueError('Used PDF needs inspected pages')
   if not isinstance(problems,list) or not problems or any(not isinstance(v,str) or not v.strip() for v in problems):raise ValueError('Identify the problems considered or adapted')
   matching=[s for t in packet.get('tasks',[])+packet.get('catch_up_tasks',[]) for s in t.get('sources',[]) if s.get('sha256')==item['sha256']]
   if not matching:raise ValueError('Used practice source must be cited by an actual task')
   if p.suffix.lower()=='.pdf' and not any(set(s.get('pages',[])) & set(pages) for s in matching):raise ValueError('Task citation must include inspected practice pages')
   summaries.append('Practice source used: '+item['title']+'; '+', '.join(problems)+'. This does not imply completed practice or mastery.')
  else:summaries.append('Practice source '+decision.replace('_',' ')+': '+item['title']+' — '+reason.strip())
 return summaries

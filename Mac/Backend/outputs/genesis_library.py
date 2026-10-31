#!/usr/bin/env python3
"""Readable-file presentation index, grounded in verified receipts; no collection/AI."""
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
STORE=ROOT/'Genesis App/Bridge'
def read(p,default):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return default
def professor_materials(root,store):
 """Index independently verified public bytes, never imply they were taught/read.

 Current pointers must match their retained run record. Dates and authority stay
 attached to each item; this projection never changes source readiness.
 """
 for current in (store/'Courses').glob('*/current.json'):
  if current.is_symlink():continue
  record=read(current,{});ident=record.get('request_id','');course=record.get('course')
  if course!=current.parent.name or not ident or ident in ('.','..') or Path(ident).name!=ident:continue
  archived=store/'Runs'/ident/(course+'-course-record.json')
  try:archived.resolve().relative_to(store.resolve())
  except ValueError:continue
  if not archived.is_file() or archived.is_symlink() or archived.read_bytes()!=current.read_bytes():continue
  for item in record.get('professor_site',{}).get('materials',[]):
   if item.get('status')!='verified' or not item.get('sha256'):continue
   path=Path(item.get('path',''))
   try:path.resolve().relative_to(root.resolve())
   except ValueError:continue
   if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:continue
   yield course,item,record.get('checked_at')
def found_materials(root,store):
 """What the scout found online: verified bytes on the school's own site, matched to their run record."""
 for current in (store/'Courses').glob('*/scout-current.json'):
  if current.is_symlink():continue
  record=read(current,{});ident=record.get('request_id','');course=record.get('course')
  if course!=current.parent.name or not ident or Path(ident).name!=ident:continue
  archived=store/'Runs'/ident/(course+'-scout-record.json')
  if not archived.is_file() or archived.is_symlink() or archived.read_bytes()!=current.read_bytes():continue
  for item in record.get('materials',[]):
   if item.get('status')!='verified' or not item.get('sha256'):continue
   path=Path(item.get('path',''))
   try:path.resolve().relative_to(root.resolve())
   except ValueError:continue
   if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:continue
   yield course,item,record.get('checked_at')
def main():
 assets=[];courses={};seen={};current_notes=set();verified=[]
 def add(p,kind,course,title=None,expected=None,**provenance):
  p=Path(p)
  if not p.is_file() or p.is_symlink() or p.suffix.lower() not in ('.pdf','.txt','.md','.png','.jpg','.jpeg','.java','.c','.h','.zip','.py','.cpp','.gz','.sh','.in','.out','.html','.doc','.docx','.ppt','.pptx'):return
  digest=hashlib.sha256(p.read_bytes()).hexdigest()
  if expected and expected!=digest:return
  key=(course,digest)
  if key in seen:
   item=seen[key]
   if provenance:
    item.setdefault('additional_sources',[]).append(provenance)
    for name,value in provenance.items():item.setdefault(name,value)
    if provenance.get('category') in ('sample_questions','review_notes','syllabus') and title:
     item.setdefault('alternate_titles',[]).append(item['title']);item['title']=title
   return
  item={'id':course+':'+str(p.resolve()),'path':str(p.resolve()),'title':title or p.name,'kind':kind,'course':course,'sha256':digest,**provenance}
  seen[key]=item;assets.append(item)
 saved_library=read(STORE/'library.json',{})
 state=read(STORE/'state.json',{});request=state.get('request') or {}
 from genesis_verification import load_receipt
 from genesis_source_policy import ACTIVE_SOURCES
 for source,row in state.get('sources',{}).items():
  if source not in ACTIVE_SOURCES:continue
  if row.get('status')!='ready' or row.get('request_id')!=request.get('id'):continue
  try:
   p=Path(row['verification']['receipt_file'])
   if load_receipt(p,request,source,ROOT)!=row['verification']:continue
   verified.append(read(p,{}))
  except (KeyError,OSError,ValueError):continue
 for receipt in verified:
  files=receipt['snapshots'];by_role={f['role']:f for f in files}
  if receipt['source']=='canvas':
   book=read(by_role['gradebooks']['path'],{})
   for course,g in book.items():courses[course]={'id':course,'grade':g.get('total_displayed','Not available'),'captured':g.get('captured_utc','Unknown'),'assignments':len(g.get('assignments',[]))}
   native=read(by_role['canvas-native-response']['path'],{})
   hashes={f['path']:f['sha256'] for f in files}
   for m in native.get('materials',[]):
    if m['path'] in hashes:add(m['path'],'Course material',m['course'],m['name'],hashes[m['path']],source_url=m.get('source'),verification_state='verified_bytes_not_learning_coverage')
 # The website was collected separately but previously omitted from the entire
 # searchable library. Reuse its content-addressed originals without new copies.
 for course,m,captured in professor_materials(ROOT,STORE):
  category=m.get('category','reference')
  add(m['path'],'Professor · '+category.replace('_',' '),course,m['title'],m['sha256'],source_url=m.get('url'),category=category,page_count=m.get('page_count'),captured_at=captured,verification_state='verified_bytes_not_learning_coverage')
 for course,m,captured in found_materials(ROOT,STORE):
  category=m.get('category','reference')
  when=' · '.join(x for x in (m.get('term'),m.get('instructor')) if x)
  add(m['path'],'Found online · '+m.get('label',category.replace('_',' ')),course,(m['title']+(' ('+when+')' if when else ''))[:200],m['sha256'],
      source_url=m.get('url'),category=category,page_count=m.get('page_count'),captured_at=captured,found_online=True,
      term=m.get('term'),instructor=m.get('instructor'),same_instructor=bool(m.get('same_instructor')),exam=m.get('exam'),
      verification_state='verified_bytes_not_learning_coverage')
 # Preserve legacy readable references/history on disk. Show only the verified current
 # derivative for a notebook already represented above, and deduplicate identical bytes.
 grades=read(ROOT/'Canvas School Source/gradebooks.json',{})
 for course,g in grades.items():
  if course not in courses:courses[course]={'id':course,'grade':g.get('total_displayed','Not available'),'captured':g.get('captured_utc','Unknown'),'assignments':len(g.get('assignments',[]))}
  add(ROOT/'Canvas School Source'/(course+' - grades.txt'),'Grades',course)
 for item in read(ROOT/'genesis_canvas_source_state.json',{}).get('files',[]):
  p=Path(item['source']);p=p if p.is_absolute() else ROOT/'Canvas School Source'/p
  course=next((c for c in grades if c in str(p)),'School');add(p,'Course material · saved',course)
 # Retain the saved note index without inspecting the reMarkable cache,
 # rehashing note bytes, rerendering, or declaring a fresh source check.
 for old in saved_library.get('assets',[]):
  if not old.get('kind','').startswith('Lecture notes'):continue
  path=Path(old.get('path',''))
  if not path.is_file() or path.is_symlink():continue
  item={**old,'kind':'Lecture notes · saved','verification_state':'dated_saved_reference_not_refreshed'}
  key=(item.get('course'),item.get('sha256',item.get('id')))
  if key not in seen:seen[key]=item;assets.append(item)
 for name in read(ROOT/'genesis_shared_source_state.json',{}).get('email_bundles',[]):add(ROOT/'Shared School Email'/name,'School email · saved',name.split(' - ')[0])
 STORE.mkdir(parents=True,exist_ok=True);p=STORE/'library.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps({'courses':list(courses.values()),'assets':assets,'receipt_request_id':request.get('id'),'verified_sources':[r['source'] for r in verified]},indent=2)+'\n');os.replace(tmp,p)
 print(json.dumps({'courses':len(courses),'readable_files':len(assets),'verified_sources':[r['source'] for r in verified]}))
if __name__=='__main__':main()

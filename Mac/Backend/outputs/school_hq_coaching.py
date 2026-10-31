#!/usr/bin/env python3
"""Local learning evidence and packet validation. No model/network or source collection."""
import sys
import argparse, copy, fcntl, hashlib, json, os, re, subprocess, tempfile, uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from school_hq_planning import priorities, duration, generic_filler, verified_grades, listed_deadlines
from school_hq_exercises import blocks
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parent
def allowed_courses(root,state):
 from school_hq_planning import configured_courses
 roster=Path(root)/'School HQ App/Bridge/library.json'
 try:extra=[x['id'] for x in json.loads(roster.read_text()).get('courses',[])]
 except (OSError,ValueError,KeyError):extra=[]
 return set(configured_courses({**state,'_courses':extra}))|{'School'}
from school_hq_connections import labels
LABELS={**labels(), 'School':'School'}
SID=re.compile(r'[A-Za-z0-9][A-Za-z0-9:._-]{2,160}')
def stamp():return datetime.now(timezone.utc).isoformat()
def slug(value):return re.sub(r'[^a-z0-9]+','-',value.lower()).strip('-')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.write-',dir=path.parent)
 try:
  with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n')
  os.chmod(tmp,0o600);os.replace(tmp,path)
 finally:
  if Path(tmp).exists():Path(tmp).unlink()
def text(obj,key):
 value=obj.get(key)
 if not isinstance(value,str) or not value.strip():raise ValueError('Missing '+key)
 return value.strip()
def contained(path,root):
 p=Path(path).resolve();root=Path(root).resolve()
 if root not in p.parents or not p.is_file():raise ValueError('Source must be an existing workspace output file')
 return p
def pdf_count(path,root):
 from school_hq_pdf import document
 return document(path)['page_count']

def source_check(s,root,day,count_pages=pdf_count):
 if s.get('origin') not in ('official','notes','original'):raise ValueError('Unknown source authority')
 text(s,'label');text(s,'section')
 if s['origin']=='original':return
 location=text(s,'location');snapshot=s.get('snapshot') or location
 if location.startswith('https://'):
  u=urlparse(location)
  if u.hostname not in ({__import__('school_hq_connections').canvas_host()}|set(__import__('school_hq_connections').read().get('public_resource_hosts',[])))-{''} or u.username or u.password:raise ValueError('Source URL outside approved school reference hosts')
 if location.startswith('https://') and not s.get('snapshot'):raise ValueError('Web reference needs a verified local capture')
 if '://' in snapshot:raise ValueError('Snapshot must be local')
 p=contained(snapshot,root)
 if any(x in p.name.lower() for x in ('private rubric','exercise-rubrics','coaching-state','study-progress','packet.json')) or 'Evidence' in p.parts:raise ValueError('Private coaching/evidence files cannot be public sources')
 if sha(p)!=text(s,'sha256'):raise ValueError('Source hash changed')
 captured=date.fromisoformat(text(s,'captured_at')[:10])
 if captured>day:raise ValueError('Future source capture date')
 if p.suffix.lower()=='.pdf':
  pages=s.get('pages')
  if not isinstance(pages,list) or not pages or any(type(n)!=int or n<1 for n in pages):raise ValueError('PDF source needs exact one-based pages')
  if max(pages)>count_pages(p,root):raise ValueError('PDF page outside document')
 return p

def initial(root):
 def legacy(name):
  try:return json.loads((root/'School HQ Study'/name).read_text())
  except FileNotFoundError:return {}
 old=legacy('study-progress.json')
 profile=legacy('study-profile.json')
 skills=[]
 for item in old.get('coverage',[]):
  skills.append({'id':item['course']+':'+slug(item['skill']),'course':item['course'],'name':item['skill'],'status':'untested','evidence':[],'successes':0})
 events=[]
 for item in profile.get('confirmed_assessments',[]):
  events.append({'id':item['course']+':'+slug(item['name']),'course':item['course'],'name':item['name'],'date':item['date'],'time':item.get('time'),'certainty':'confirmed','scope':item.get('scope'),'skill_ids':[],'scope_verified':False,'source_note':item['source'],'captured_at':'2026-10-08','legacy_snapshot':True})
 return {'schema':2,'skills':skills,'events':events,'attempts':[],'review_queue':[],'exercises':{},'assigned_packets':[],'unconfirmed_events':profile.get('unconfirmed_assessments',[]),'migration_note':'Legacy coverage retained as untested; checkmarks/assignments do not establish correctness. Original files preserved.'}
def load(root=ROOT):
 p=root/'School HQ Study/coaching-state.json'
 return json.loads(p.read_text()) if p.exists() else initial(root)
def validate_packet(packet,root=ROOT,state=None,count_pages=pdf_count):
 state=load(root) if state is None else state
 courses=allowed_courses(root,state)
 day=date.fromisoformat(text(packet,'date'))
 if packet.get('schema')!=2:raise ValueError('Packet schema 2 required')
 text(packet,'title');text(packet,'subtitle');text(packet,'source_limits')
 skills={x['id']:x for x in state['skills']}
 for s in packet.get('new_skills',[]):
  if not SID.fullmatch(text(s,'id')) or s.get('course') not in courses or s['id'] in skills:raise ValueError('Invalid new skill')
  text(s,'name');skills[s['id']]=s
 base_tasks=packet.get('tasks');extra=packet.get('catch_up_tasks',[])
 if not isinstance(base_tasks,list) or not 1<=len(base_tasks)<=16 or not isinstance(extra,list) or len(extra)>8:raise ValueError('Use 1–16 normal tasks and at most 8 additive catch-up tasks')
 tasks=base_tasks+extra;out=[];rubrics={};seen=set();events={e['id']:e for e in state.get('events',[])}
 for n,t in enumerate(tasks,1):
  if generic_filler(t):raise ValueError('Generic break/reset tasks are not part of a study plan')
  key=text(t,'exercise_id')
  if not SID.fullmatch(key) or key in seen:raise ValueError('Invalid/duplicate exercise ID')
  seen.add(key);course=t.get('course');kind=t.get('kind')
  if course not in courses or kind not in ('learning','instruction','deadline','exam','event','break'):raise ValueError('Explicit course/kind required')
  title=text(t,'title');question=text(t,'question');why=text(t,'reason');aids=text(t,'aids');done=text(t,'done_when')
  steps=t.get('steps')
  if not isinstance(steps,list) or not steps or any(not isinstance(x,str) or not x.strip() for x in steps):raise ValueError('Task needs explicit steps')
  public=' '.join([title,question,why,aids,done,*steps])
  if t.get('prompt_blocks') is not None:
   block_list=t['prompt_blocks']
   if not isinstance(block_list,list) or not block_list or len(block_list)>80:raise ValueError('Invalid prompt blocks')
   for block in block_list:
    if not isinstance(block,dict) or set(block)-{'kind','text','language'} or block.get('kind') not in ('paragraph','code','displayMath') or not isinstance(block.get('text'),str):raise ValueError('Invalid public content block')
    if len(block['text'])>20000:raise ValueError('Content block too large')
    public+=' '+block['text']

  if re.search(r'\b(today|tomorrow|yesterday)\b',public,re.I):raise ValueError('Use absolute dates in saved tasks')
  if re.fullmatch(r'(review|practice|study)\s+(this |the )?(topic|material|more).*',title,re.I):raise ValueError('Generic topic task')
  if re.search(r'\b(mastered|exam.ready|fully prepared)\b',public,re.I):raise ValueError('Unsupported readiness claim')
  sources=t.get('sources',[])
  if kind!='break' and not sources:raise ValueError('Task needs exact source or labeled original practice')
  for src in sources:source_check(src,root,day,count_pages)
  if kind in ('learning','instruction'):
   if not t.get('skill_ids') or any(k not in skills or skills[k]['course']!=course for k in t['skill_ids']):raise ValueError('Known matching skill IDs required')
   if t.get('restricted_graded',False):raise ValueError('Restricted graded material cannot be assessed')
   if len(question)<20:raise ValueError('Incomplete practice question')
   private=t.get('private_solution')
   if not isinstance(private,dict):raise ValueError('Hidden answer/rubric required')
   solution=text(private,'solution');text(private,'rubric');verification=private.get('verification',{})
   if verification.get('method') not in ('official_solution','independent_calculation','controlled_practice_tests'):raise ValueError('Independent answer verification required')
   text(verification,'evidence')
   if kind=='learning' and len(solution)>=16 and solution.lower() in public.lower():raise ValueError('Target answer leaked into public task')
   rubrics[key]=private
  else:
   if kind in ('exam','event','deadline'):
    e=events.get(t.get('event_id'))
    if not e or e.get('certainty')!='confirmed':raise ValueError('Unconfirmed event cannot be assigned as confirmed')
    if e.get('legacy_snapshot') or not e.get('source'):raise ValueError('Event needs reverified structured official evidence')
    source_check(e['source'],root,day,count_pages)
    if date.fromisoformat(e['date'])<day:raise ValueError('Past event cannot be newly assigned')
    if e['date'] not in public:raise ValueError('Event needs an absolute date')
  fingerprint=hashlib.sha256(json.dumps({'course':course,'question':question,'skill_ids':t.get('skill_ids',[])},sort_keys=True).encode()).hexdigest()
  prior=state.get('exercises',{}).get(key)
  if prior and prior['fingerprint']!=fingerprint:raise ValueError('Existing exercise ID reused for a different problem')
  source_public=[{k:v for k,v in s.items() if k in ('label','location','pages','section','origin','captured_at','snapshot','role','search')} for s in sources]
  body=question+'\n\n'+'\n'.join(f'{i}. {x}' for i,x in enumerate(steps,1))+'\n\nAids: '+aids+'\n\nDone when: '+done
  if t.get('cue'):body+='\n\nMemory cue: '+t['cue']
  minutes,basis=duration(t)
  extra={}
  for k in ('answer_type','answer_format','origin','format_match','problem_label','mode','language','teaching_blocks','example_blocks','hint_blocks','emphasis_version'):
   if t.get(k) is not None:extra[k]=t[k]
  if extra.get('answer_type') not in (None,'code','code_trace','memory_trace','derivation','numeric','short_answer','proof','multiple_choice','table','explanation','mixed'):raise ValueError('Unknown answer type')
  for k in ('teaching_blocks','example_blocks','hint_blocks'):
   v=extra.get(k)
   if v is not None and (not isinstance(v,list) or len(v)>40 or any(not isinstance(b,dict) or b.get('kind') not in ('paragraph','code','displayMath') or not isinstance(b.get('text'),str) or len(b['text'])>12000 for b in v)):raise ValueError('Invalid '+k)
   if v and kind=='learning' and isinstance(t.get('private_solution'),dict):
    sol=str(t['private_solution'].get('solution',''))
    if len(sol)>=16 and sol.lower() in ' '.join(b['text'] for b in v).lower():raise ValueError('Target answer leaked into teaching content')
  out.append({'context_addition':n>len(base_tasks),'prompt_blocks':t.get('prompt_blocks') or blocks(body,course),'estimated_minutes':minutes,'estimate_basis':basis,'id':key,'exercise_id':key,'number':n,'title':title,'body':body,'course':LABELS.get(course,course),'course_id':course,'kind':kind,'skill_ids':t.get('skill_ids',[]),'reason':why,'sources':source_public,'fingerprint':fingerprint,
   'question':question,'steps':steps,'aids':aids,'done_when':done,'cue':t.get('cue'),**extra})
 return out,rubrics

def record_packet(packet,tasks,state):
 for item in packet.get('new_skills',[]):
  if not any(s['id']==item['id'] for s in state['skills']):state['skills'].append({**item,'status':'untested','evidence':[],'successes':0})
 for t in tasks:state['exercises'].setdefault(t['id'],{'fingerprint':t['fingerprint'],'course':t['course_id'],'skill_ids':t['skill_ids'],'rubric_verified':t['kind'] in ('learning','instruction')})
 record={'date':packet['date'],'exercise_ids':[t['id'] for t in tasks],'status':'assigned, not attempted'}
 state['assigned_packets']=[x for x in state['assigned_packets'] if x['date']!=packet['date']]+[record]

def update_event(state,new,root=ROOT):
 if new.get('course') not in allowed_courses(root,state) or new.get('certainty') not in ('confirmed','tentative','conflict'):raise ValueError('Event course/certainty invalid')
 if not SID.fullmatch(text(new,'id')):raise ValueError('Event ID invalid')
 date.fromisoformat(text(new,'date'));text(new,'name');captured=date.fromisoformat(text(new,'captured_at')[:10])
 src=new.get('source')
 if not isinstance(src,dict) or src.get('origin')!='official':raise ValueError('Official captured event evidence required')
 source_file=source_check(src,root,date.today())
 if new.get('scope_verified') is True and not new.get('skill_ids'):raise ValueError('Verified exam scope needs explicit skill mapping')
 if new['captured_at'][:10]!=src['captured_at'][:10]:raise ValueError('Event and source capture dates differ')
 quoted=text(new,'date_text')
 parsed=None
 for fmt in ('%Y-%m-%d','%B %d, %Y','%b %d, %Y','%m/%d/%Y'):
  try:parsed=datetime.strptime(quoted,fmt).date();break
  except ValueError:continue
 if parsed is None or parsed.isoformat()!=new['date']:raise ValueError('Event date must match its exact source text')
 if source_file.suffix.lower()=='.pdf':
  from school_hq_pdf import document
  pages=document(source_file)['pages']
  body='\n'.join(pages[p-1] for p in src['pages'])
 else:body=source_file.read_text()
 if quoted not in body:raise ValueError('Event date text absent from captured source')
 if new.get('time'):
  time_text=text(new,'time_text');parsed_time=None
  for fmt in ('%H:%M','%I:%M %p','%I %p'):
   try:parsed_time=datetime.strptime(time_text.upper(),fmt).strftime('%H:%M');break
   except ValueError:continue
  if parsed_time!=new['time'] or time_text not in body:raise ValueError('Event time must match its actual official source text')
 known={x['id'] for x in state['skills']}
 if any(k not in known for k in new.get('skill_ids',[])):raise ValueError('Unknown exam skill')
 prior=next((e for e in state['events'] if e['id']==new['id']),None)
 if prior:
  previous=date.fromisoformat(prior['captured_at'][:10])
  if captured<previous:raise ValueError('Older event cannot overwrite newer evidence')
  if captured==previous and prior['date']!=new['date']:
   prior['certainty']='conflict';prior['conflicting_evidence']=new;return
  if new==prior:return
 state['events']=[e for e in state['events'] if e['id']!=new['id']]+[new]

def assess(state,review,evidence,day):
 # This records a reviewed attempt; it never autonomously grades a photograph.
 if day>datetime.now(__import__('school_hq_connections').zone()).date():raise ValueError('Future attempts cannot be recorded')
 ident=text(review,'submission_id')
 if evidence.get('id')!=ident or not (evidence.get('answer','').strip() or evidence.get('attachment')):raise ValueError('Actual answer evidence required')
 if evidence.get('assessment_allowed') is not True:raise ValueError('Practice-only consent/scope required')
 if any(a['submission_id']==ident for a in state['attempts']):raise ValueError('Submission already reviewed')
 exercise=text(evidence,'exercise_id');entry=state['exercises'].get(exercise)
 if not entry or not entry.get('rubric_verified'):raise ValueError('Known exercise with a verified rubric required; register legacy practice first')
 outcome=review.get('outcome')
 if outcome not in ('correct','incorrect','ambiguous'):raise ValueError('Invalid outcome')
 text(review,'feedback');text(review,'verification_evidence')
 if outcome=='incorrect':text(review,'specific_error')
 aids=evidence.get('aids')
 if aids not in ('closed_book','allowed_exam_aids','notes','hint'):raise ValueError('Aid level missing')
 independent=outcome=='correct' and aids in ('closed_book','allowed_exam_aids')
 partial=outcome=='incorrect' and isinstance(review.get('partial_score'),(int,float)) and 0.6<=review['partial_score']<1
 attempt={**review,'exercise_id':exercise,'aids':aids,'independent':independent,'reviewed_at':stamp(),'attempt_date':day.isoformat()}
 state['attempts'].append(attempt)
 # What each kind of evidence does (precedence top to bottom):
 #   ambiguous            nothing changes except a clarification flag
 #   correct, same day as a miss on this skill  'repaired': the error is cleared, but an
 #                        immediate retry after feedback is not spaced success; review tomorrow
 #   correct, independent spaced success: next review 1, 3, 7, 14, then 30 days out
 #   correct with a hint  supported: no success credit and no reset; review tomorrow
 #   partial (0.6-0.99)   one slip: retry tomorrow, one earlier success removed, not all
 #   incorrect            the error is recorded, successes reset, retry tomorrow
 for sid in entry['skill_ids']:
  skill=next(x for x in state['skills'] if x['id']==sid)
  prior=[a for a in state['attempts'][:-1] if a.get('independent') and sid in state['exercises'][a['exercise_id']]['skill_ids']]
  skill['evidence'].append(ident);skill['last_attempt']=day.isoformat()
  missed_today=any(a.get('attempt_date')==day.isoformat() and a.get('outcome')=='incorrect' and sid in state['exercises'].get(a['exercise_id'],{}).get('skill_ids',[]) for a in state['attempts'][:-1])
  if outcome=='ambiguous':
   skill['needs_clarification']=True;continue
  if independent and missed_today:
   skill.pop('last_error',None);skill.pop('needs_clarification',None)
   if skill['status'] in ('untested','learning'):skill['status']='learning'
   attempt['evidence_kind']='repaired_same_day';offset=1;mode='retrieval'
  elif independent:
   skill['successes']=skill.get('successes',0)+1
   skill.pop('last_error',None);skill.pop('needs_clarification',None)
   transferred=review.get('transfer_variant') is True and any(a['exercise_id']!=exercise and state['exercises'][a['exercise_id']]['fingerprint']!=entry['fingerprint'] for a in prior)
   skill['status']='transfer-checked' if transferred else 'demonstrated'
   attempt['evidence_kind']='independent'
   offset=[1,3,7,14,30][min(skill['successes']-1,4)];mode='retrieval'   # 30 days keeps early-term skills alive for the final
  elif outcome=='correct':
   if skill['status']=='untested':skill['status']='learning'
   attempt['evidence_kind']='supported';offset=1;mode='retrieval'
  elif partial:
   skill['successes']=max(0,skill.get('successes',0)-1);skill['status']='learning'
   skill['last_error']=review.get('specific_error') or 'One slip in otherwise correct work'
   attempt['evidence_kind']='partial';offset=1;mode='independent_retry'
  else:
   skill['status']='learning';skill['successes']=0;offset=1
   recent=[a for a in state['attempts'] if sid in state['exercises'][a['exercise_id']]['skill_ids']][-3:]
   recent=[a for a in recent if a['outcome']=='incorrect']
   mode='prerequisite' if len(recent)>=2 else 'independent_retry'
   skill['last_error']=review.get('specific_error') or 'Incorrect answer'
   attempt['evidence_kind']='incorrect'
  due=(day+timedelta(days=offset)).isoformat();skill['next_review']=due
  state['review_queue']=[q for q in state['review_queue'] if q['skill_id']!=sid]+[{'skill_id':sid,'due':due,'mode':mode,'based_on':ident}]
 return attempt

def candidates(state,day):
 ranked=[];course_scores={r['course']:r for r in priorities(state,day)}
 due={q['skill_id']:q for q in state['review_queue'] if q['due']<=day.isoformat()}
 for skill in state['skills']:
  base=course_scores.get(skill['course'])
  if not base:continue
  adjustment=30 if skill.get('last_error') else 20 if skill['status'] in ('learning','untested') else 0
  if skill['id'] in due:adjustment+=55
  ranked.append({'skill_id':skill['id'],'course':skill['course'],'status':skill['status'],'priority':round(base['priority']+adjustment,2),'reason':base['reason']+('; repair '+skill['last_error'] if skill.get('last_error') else '')})
 ordered=sorted(ranked,key=lambda x:(-x['priority'],x['skill_id']))
 # Reserve one evidence-based diagnostic per course, regardless of bank coverage.
 selected=[]
 for row in course_scores.values():
  item=next((x for x in ordered if x['course']==row['course']),None)
  if item:selected.append(item)
 for item in ordered:
  if item not in selected and sum(x['course']==item['course'] for x in selected)<6 and len(selected)<18:selected.append(item)   # room for due reviews behind several repairs
 return sorted(selected,key=lambda x:(-x['priority'],x['skill_id']))

def dashboard(state,day,root=ROOT):
 from school_hq_preparation import planning_state
 state=planning_state(root,copy.deepcopy(state));state['_verified_grades']=verified_grades(root);state['_listed_deadlines']=listed_deadlines(root)
 upcoming=[e for e in state['events'] if date.fromisoformat(e['date'])>=day]
 upcoming.sort(key=lambda e:e['date'])
 counts={k:sum(s['status']==k for s in state['skills']) for k in ('untested','learning','demonstrated','transfer-checked')}
 return {'course_priorities':priorities(state,day),'schema':2,'as_of':stamp(),'reviewed_submission_ids':[a['submission_id'] for a in state['attempts']],'unconfirmed_events':state.get('unconfirmed_events',[]),'events':upcoming,'coverage':counts,'candidates':candidates(state,day),'due_reviews':[q for q in state['review_queue'] if q['due']<=day.isoformat()],'feedback':[{'submission_id':a['submission_id'],'feedback':a['feedback'],'outcome':a['outcome'],'exercise_id':a.get('exercise_id'),'attempt_date':a.get('attempt_date'),'course':state['exercises'].get(a.get('exercise_id'),{}).get('course')} for a in state['attempts'][-12:]]}

def persist(state,root=ROOT):
 atomic(root/'School HQ Study/coaching-state.json',state)
 atomic(root/'School HQ App/Bridge/learning.json',dashboard(state,datetime.now(__import__('school_hq_connections').zone()).date(),root))
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['initialize','context','validate','review','event','register']);p.add_argument('--file');args=p.parse_args()
 root=ROOT;lock=root/'School HQ Study/.coaching.lock';lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('a') as held:
  fcntl.flock(held,fcntl.LOCK_EX);state=load(root)
  if args.action=='initialize':persist(state);print('Learning state initialized; legacy progress preserved')
  elif args.action=='context':print(json.dumps(dashboard(state,datetime.now(__import__('school_hq_connections').zone()).date()),indent=2))
  elif args.action=='validate':
   packet=json.loads(contained(args.file,root/'School HQ Study').read_text());tasks,rubrics=validate_packet(packet,root,state);print(json.dumps({'valid':True,'tasks':len(tasks),'hidden_rubrics':len(rubrics)}))
  elif args.action=='register':
   packet=json.loads(contained(args.file,root/'School HQ Study').read_text());tasks,rubrics=validate_packet(packet,root,state)
   if any(t['kind']!='learning' for t in tasks):raise ValueError('Legacy review registration accepts ungraded learning exercises only')
   for skill in packet.get('new_skills',[]):
    if not any(x['id']==skill['id'] for x in state['skills']):state['skills'].append({**skill,'status':'untested','evidence':[],'successes':0})
   for t in tasks:state['exercises'].setdefault(t['id'],{'fingerprint':t['fingerprint'],'course':t['course_id'],'skill_ids':t['skill_ids'],'rubric_verified':True})
   registry=root/'School HQ Study/exercise-rubrics.json';stored=json.loads(registry.read_text()) if registry.exists() else {};stored.update(rubrics);atomic(registry,stored);persist(state)
   print(json.dumps({'registered_for_review':[t['id'] for t in tasks],'assigned':False,'graded':False}))
  elif args.action=='event':update_event(state,json.loads(contained(args.file,root/'School HQ Study').read_text()),root);persist(state)
  elif args.action=='review':
   review=json.loads(contained(args.file,root/'School HQ Study').read_text())
   submission=contained(root/'School HQ App/Bridge/Evidence'/(text(review,'submission_id')+'.json'),root/'School HQ App/Bridge/Evidence')
   evidence=json.loads(submission.read_text())
   if evidence.get('attachment'):
    attachment=contained(evidence['attachment'],root/'School HQ App/Bridge/Evidence')
    if sha(attachment)!=evidence.get('attachment_sha256'):raise ValueError('Evidence attachment changed')
   package=root/'School HQ App/Bridge/Packets'/str(evidence.get('brief_id',''))/'rubrics.json'
   if package.is_file():
    from school_hq_publication import package_valid
    package_valid(package.parent)
   registry=package if package.is_file() else root/'School HQ Study/exercise-rubrics.json'
   if not registry.exists() or evidence.get('exercise_id') not in json.loads(registry.read_text()):raise ValueError('Verified rubric for this exact brief absent; keep evidence pending')
   assess(state,review,evidence,date.fromisoformat(review['attempt_date']));persist(state)
if __name__=='__main__':main()

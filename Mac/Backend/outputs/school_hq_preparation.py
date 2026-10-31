#!/usr/bin/env python3
"""Course-neutral preparation projection. No collection, model, or source-status writes.

Authoritative source artifacts and original attempt journal remain separate. This
projection is disposable; its version binds the UI order and guided selection.
"""
import argparse,hashlib,json,re,sys
from pathlib import Path
from datetime import datetime,date,timezone,timedelta
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parent

def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return {} if default is None else default

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def now():return datetime.now(timezone.utc)
def source_valid(s,root):
 try:
  p=Path(s['snapshot']).resolve();p.relative_to(Path(root).resolve())
  captured=datetime.fromisoformat(s['captured_at'].replace('Z','+00:00'))
  return p.is_file() and not p.is_symlink() and sha(p)==s['sha256'] and captured.tzinfo is not None and captured<=now()
 except (KeyError,OSError,ValueError,TypeError,AttributeError):return False

def assessments(root):
 result=[]
 for row in read(Path(root)/'School HQ Study/assessments.json',{}).get('assessments',[]):
  v=dict(row);v['source_verified']=bool(v.get('sources')) and all(source_valid(s,root) for s in v['sources'])
  v['source_warning']=None if v['source_verified'] else 'Assessment source is missing or changed. Scope needs verification.'
  result.append(v)
 return result

def validate(payload,root):
 if payload.get('schema')!=1 or not isinstance(payload.get('assessments'),list):raise ValueError('Assessment schema 1 required')
 ids=set()
 for a in payload['assessments']:
  if not re.fullmatch(r'[A-Za-z0-9:._-]{3,180}',a.get('id','')) or a['id'] in ids:raise ValueError('Invalid/duplicate assessment ID')
  ids.add(a['id'])
  if not a.get('course') or not a.get('name') or a.get('certainty') not in ('confirmed','listed','inferred','conflicting','unknown'):raise ValueError('Course/title/certainty required')
  if a.get('date'):date.fromisoformat(a['date'])
  if not a.get('sources') or not all(source_valid(s,root) for s in a['sources']):raise ValueError('Hash-verified local source required for assessment')
  objective_ids=set()
  for o in a.get('objectives',[]):
   if not o.get('id') or not o.get('title') or o['id'] in objective_ids:raise ValueError('Unique objective ID/title required')
   objective_ids.add(o['id'])
   if o.get('points') is not None and (type(o['points']) not in (int,float) or o['points']<0):raise ValueError('Invalid objective point weight')
   if not o.get('formats'):raise ValueError('Objective formats required')
  if a.get('duration_minutes') is not None and (type(a['duration_minutes'])!=int or a['duration_minutes']<1):raise ValueError('Invalid assessment duration')
 return payload

def assessment_active(a,when):
 if a.get('status','scheduled') in ('cancelled','completed') or not a.get('date'):return False
 try:
  zone=ZoneInfo(a.get('timezone') or __import__('school_hq_connections').zone_name());local=when.astimezone(zone);day=date.fromisoformat(a['date'])
  if day!=local.date():return day>local.date()
  if a.get('time') and a.get('duration_minutes'):
   end=datetime.fromisoformat(a['date']+'T'+a['time']).replace(tzinfo=zone)+timedelta(minutes=a['duration_minutes'])
   return local<=end
  return True
 except (ValueError,TypeError):return False

def planning_state(root,state,when=None):
 when=when or now()
 s=dict(state);s['_assessments']=assessments(root)
 from school_hq_planning import low_exams
 s['_low_exams']=low_exams(root)
 policies=read(Path(root)/'School HQ Study/grading-policies.json',{}).get('policies',[])
 s['_grade_policies']={v['course']:v for v in policies if v.get('course') and type(v.get('passing_percent')) in (int,float) and 0<=v['passing_percent']<=100 and v.get('sources') and all(source_valid(x,root) for x in v['sources'])}
 roster=read(Path(root)/'School HQ App/Bridge/library.json',{}).get('courses',[])
 s['_courses']=sorted({c['id'] for c in roster if c.get('id')}|{a['course'] for a in s['_assessments']}|{x['course'] for x in state.get('skills',[]) if x.get('course')})
 for a in s['_assessments']:
  s['events']=[x for x in s.get('events',[]) if x.get('id')!=a['id']]
  if not assessment_active(a,when) or not a['source_verified'] or a.get('certainty') not in ('confirmed','listed') or not a.get('date'):continue
  event={'id':a['id'],'course':a['course'],'name':a['name'],'kind':'exam','date':a['date'],'certainty':a['certainty'],'scope_verified':bool(a.get('objectives')) and all(o.get('title') and o.get('formats') for o in a.get('objectives',[]))}
  s['events']=[x for x in s.get('events',[]) if x.get('id')!=a['id']]+[event]
 return s

def build(root=ROOT,when=None,brief_override=None,state_override=None):
 import school_hq_coaching as c
 from school_hq_planning import priorities,listed_deadlines,verified_grades
 root=Path(root);when=when or now();day=when.astimezone(__import__('school_hq_connections').zone()).date();bridge=root/'School HQ App/Bridge'
 state=planning_state(root,c.load(root) if state_override is None else state_override,when);state['_verified_grades']=verified_grades(root);state['_listed_deadlines']=listed_deadlines(root)
 ranked=priorities(state,day);scores={x['course']:x['priority'] for x in ranked}
 pipeline=read(bridge/'state.json',{});brief=(pipeline.get('brief') or {}) if brief_override is None else brief_override;journal=read(root/'School HQ Study/learning-journal.json',{'attempts':[]});bank=read(root/'School HQ Study/lesson-bank.json',{'lessons':[]})
 bank['lessons']+=read(root/'School HQ Study/practice-extension.json',{'lessons':[]}).get('lessons',[])
 exams=[];focus={};lesson_scores={};coverage=[]
 for a in state['_assessments']:
  e=dict(a);days=(date.fromisoformat(a['date'])-day).days if a.get('date') else None;e['days_until']=days;e['active']=assessment_active(a,when)
  source_dates=[s.get('captured_at','') for s in a.get('sources',[])];e['captured_at']=max(source_dates,default='');e['stale']=False
  try:e['stale']=(when-datetime.fromisoformat(e['captured_at'].replace('Z','+00:00'))).total_seconds()>172800
  except ValueError:e['stale']=True
  rows=[]
  for o in a.get('objectives',[]):
   lessons=[l for l in bank['lessons'] if l['course']==a['course'] and l['id'] in o.get('lesson_ids',[])]
   attempts=[v for v in journal['attempts'] if v['lesson_id'] in {l['id'] for l in lessons}]
   independent=[v for v in attempts if v.get('outcome')=='correct' and v.get('aids')=='closed_book']
   reviewed=[v for v in attempts if v.get('outcome') in ('correct','incorrect')];pending=[v for v in attempts if v.get('outcome')=='pending_review']
   demonstrated_formats=sorted({q.get('format','targeted answer') for l in lessons for q in l['questions'] if any(v['question_id']==q['id'] and v['lesson_id']==l['id'] for v in independent)})
   missing=[f for f in o['formats'] if f not in demonstrated_formats]
   status='Latest reviewed sample incorrect — repair needed' if reviewed and reviewed[-1]['outcome']=='incorrect' else 'Independent sample demonstrated' if independent else 'Supported sample correct — unaided check needed' if reviewed else 'Awaiting review' if pending else 'Not assessed'
   row={**o,'status':status,'reviewed_attempts':len(reviewed),'independent_attempts':len(independent),'pending_attempts':len(pending),'demonstrated_formats':demonstrated_formats,'missing_formats':missing,'practice_available':bool(lessons),'available_formats':sorted({q.get('format','targeted answer') for l in lessons for q in l['questions']}),'lesson_closed_for_attempt_count':sum(l['id'] in journal.get('lessons_seen',[]) for l in lessons),'attempt_count':len(attempts),'retention_correct_count':sum(v.get('phase')=='retention' for v in independent),'limits':'Narrow checks do not certify complete implementation or exam readiness.'}
   rows.append(row)
   if e['active'] and a['source_verified'] and not e['stale'] and a.get('certainty') in ('confirmed','listed'):
    points=o.get('points');weight=float(points) if points is not None else 1.
    need=3 if reviewed and reviewed[-1]['outcome']=='incorrect' else 2 if not independent else 1
    for l in lessons:lesson_scores[l['id']]=max(lesson_scores.get(l['id'],0),weight*need);focus.setdefault(a['course'],set()).add(l['id'])
  e['objectives']=rows;exams.append(e)
 exams.sort(key=lambda e:(not e['active'],-scores.get(e['course'],0) if e['active'] else 0,e.get('date') or '9999'))
 tasks=[dict(t) for t in brief.get('tasks',[]) if t.get('kind')!='break']
 for t in tasks:
  code=t.get('course_id') or t.get('course');t['plan_course']=code;t['plan_priority']=scores.get(code,0)
  # Never promote old tasks into a current deadline. Their own brief date is kept.
  urgent=t.get('kind') in ('deadline','instruction') and any((x['course']==code or code=='School') and x['date']<=day.isoformat() and (t.get('kind')=='deadline' or x['name'].casefold() in (t.get('title','')+' '+t.get('body','')).casefold()) for x in state['_listed_deadlines'])
  t['urgent_deadline']=urgent
 addition_ids={t['id'] for t in brief.get('tasks',[]) if t.get('context_addition')}
 tasks.sort(key=lambda t:(t['id'] in addition_ids,not t['urgent_deadline'] if t['id'] not in addition_ids else False,-t['plan_priority'] if t['id'] not in addition_ids else 0,t.get('number',0)))
 public_tasks=[{'id':t['id'],'priority':t['plan_priority'],'urgent_deadline':t['urgent_deadline']} for t in tasks]
 view={'schema':1,'as_of':when.isoformat(),'day':day.isoformat(),'brief_id':brief.get('id'),'brief_date':brief.get('date'),'course_priorities':ranked,'task_order':[t['id'] for t in tasks],'task_priorities':public_tasks,'assessments':exams,'lesson_scores':lesson_scores,'focus_lessons':{k:sorted(v) for k,v in focus.items()},'limits':'Source-backed coverage and reviewed samples; no exam-readiness percentage. Saved plans do not make source checks current.'}
 # Version reflects only meaningful inputs, never the refresh clock.
 view['version']=digest({k:view[k] for k in ('day','brief_id','task_order','assessments','course_priorities','lesson_scores')})
 return view

def write(root=ROOT,when=None):
 import school_hq_coaching as c
 value=build(root,when);c.atomic(Path(root)/'School HQ App/Bridge/preparation.json',value);return value

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['refresh','import','import-practice']);p.add_argument('--file',type=Path);a=p.parse_args()
 if a.action=='import-practice':
  import school_hq_learning as learning
  import school_hq_coaching as c
  if not a.file:raise ValueError('Practice import file required')
  incoming=read(a.file);current=read(ROOT/'School HQ Study/practice-extension.json',{'schema':1,'lessons':[]})
  if incoming.get('schema')!=1 or not isinstance(incoming.get('lessons'),list):raise ValueError('Practice schema 1 required')
  merged={x['id']:x for x in current['lessons']}
  attempts=read(ROOT/'School HQ Study/learning-journal.json',{}).get('attempts',[])
  for lesson in incoming['lessons']:
   old=merged.get(lesson['id'])
   if old and old!=lesson and any(x['lesson_id']==lesson['id'] for x in attempts):raise ValueError('Attempted practice is immutable; import a new revision ID')
   merged[lesson['id']]=lesson
  base=read(ROOT/'School HQ Study/lesson-bank.json');base['lessons']+=list(merged.values())
  temp=ROOT/'School HQ Study/.practice-validation.json'
  try:
   c.atomic(temp,base);learning.bank(temp)
  finally:
   if temp.exists():temp.unlink()
  c.atomic(ROOT/'School HQ Study/practice-extension.json',{'schema':1,'lessons':list(merged.values())})
 if a.action=='import':
  import school_hq_coaching as c
  if not a.file:raise ValueError('Import file required')
  incoming=validate(read(a.file),ROOT);old=ROOT/'School HQ Study/assessments.json'
  merged={x['id']:x for x in read(old,{'assessments':[]}).get('assessments',[])}
  merged.update({x['id']:x for x in incoming['assessments']});value={'schema':1,'assessments':list(merged.values())}
  if old.exists():
   prior=read(old);c.atomic(ROOT/'School HQ Study/AssessmentHistory'/(digest(prior)+'.json'),prior)
  c.atomic(old,value)
 print(json.dumps(write()))
if __name__=='__main__':main()

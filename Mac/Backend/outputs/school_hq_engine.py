#!/usr/bin/env python3
"""School HQ study engine: plan in code, write each task with a model, verify it
with a different model (plus real test runs for code), then publish.

What decides WHAT you study is deterministic and explainable (deadlines, exams,
grades, recent errors, spaced reviews, your notes). Models only write and check
the individual tasks. Citations are attached by code from the problem catalog, so
a task can only point at pages and problems that exist.
"""
import argparse,copy,hashlib,json,os,re,shutil,subprocess,sys,tempfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
BRIDGE=ROOT/'School HQ App/Bridge'
STUDY=ROOT/'School HQ Study'
CACHE=STUDY/'task-cache'
from school_hq_connections import labels
SHORT=labels()
LABELS={k:v+' ('+k+')' for k,v in SHORT.items()}
LANG={'COP3330':'java','COP3502C':'c'}
MAX_NORMAL=14   # safety bound on optional work, not a target; work due within three days is never cut by it
MAX_TASKS=16    # what a published plan may hold (packet validation)
MODE_MINUTES={'learn':22,'repair':18,'retrieval':10,'mock':45,'prep':22,'catch_up':15,'diagnose':10}   # used only when you set a daily limit

def now():return datetime.now(timezone.utc).isoformat()
def today():return datetime.now(ZoneInfo('America/New_York')).date()
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def sha(p):return sha_bytes(Path(p).read_bytes())
def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return {} if default is None else default
def atomic(p,v):
 from school_hq_coaching import atomic as write;write(p,v)
def slug(v):return re.sub(r'[^a-z0-9]+','-',str(v).lower()).strip('-')[:60] or 'x'
def norm(t):return re.sub(r'\s+',' ',re.sub(r'[^0-9a-z]+',' ',(t or '').lower())).strip()
def words(t):return {w for w in norm(t).split() if len(w)>2 and w not in STOP}
STOP={'and','the','with','for','from','into','using','this','that','targeted','answer','check','checks','final','problem','question','write','code','given','each','what','your','rule','rules','basics','basic','review','practice','theory','notes','part','intro','introduction','function','functions','find','use'}

def bridge(*args):
 p=subprocess.run([sys.executable,str(ROOT/'school_hq_app_bridge.py'),*args],capture_output=True,text=True,timeout=120)
 if p.returncode:raise RuntimeError((p.stderr.strip().splitlines() or ['Bridge command failed'])[-1])
 return json.loads(p.stdout)

# ======================================================================
# Planning (deterministic)
# ======================================================================
def iso_mtime(p):
 return datetime.fromtimestamp(Path(p).stat().st_mtime,timezone.utc).isoformat()

def source_for(doc_path,title,pages,section,url=None,captured=None):
 p=Path(doc_path).resolve()
 location=url if (url and url.startswith('https://') and re.match(r'https://(webcourses\.ucf\.edu|www\.cs\.ucf\.edu|cs\.ucf\.edu)/',url)) else str(p)
 cap=captured or iso_mtime(p)
 try:
  when=datetime.fromisoformat(cap.replace('Z','+00:00'))
  if when.tzinfo is None or when>datetime.now(timezone.utc):when=datetime.fromisoformat(iso_mtime(p))
 except ValueError:when=datetime.fromisoformat(iso_mtime(p))
 # Eastern local time: the validator compares the calendar date with the plan date.
 cap=when.astimezone(ZoneInfo('America/New_York')).isoformat()
 src={'origin':'official','label':title,'section':section[:300],'location':location,'snapshot':str(p),'sha256':sha(p),'captured_at':cap}
 if p.suffix.lower()=='.pdf':src['pages']=sorted(set(int(x) for x in pages))
 return src

def course_events(state,course,day):
 out=[]
 for e in state.get('events',[])+state.get('_listed_deadlines',[]):
  if e.get('course')!=course or not e.get('date') or e.get('superseded'):continue
  try:d=(date.fromisoformat(e['date'])-day).days
  except ValueError:continue
  exam=e.get('kind')=='exam' or bool(re.search(r'^(?:exam|test|midterm|quiz|final)\b|\bexam\b|\bmidterm\b',e.get('name',''),re.I))
  out.append({'name':e.get('name','')[:120],'date':e['date'],'days':d,'exam':exam,'certainty':e.get('certainty'),'overdue':bool(e.get('overdue')),'assignment_id':e.get('assignment_id')})
 return sorted(out,key=lambda x:x['days'])

def grade_facts(course):
 g=read(BRIDGE/'grades.json',{}).get('courses',[])
 row=next((x for x in g if x.get('course')==course),None)
 return row.get('displayed') if row else None

def recent_exam_scores(course):
 """Low graded exams from the latest gradebook (e.g. 'E2 14/100')."""
 out=[]
 try:
  ident=read(BRIDGE/'grades.json',{}).get('request_id')
  book=read(BRIDGE/'Runs'/ident/'gradebooks.json',{}).get(course,{})
  for a in book.get('assignments',[]):
   name=a.get('name','');score=a.get('score_displayed','')
   if re.search(r'placeholder|replacement|review|practice|survey|attendance',name,re.I):continue
   if re.search(r'exam|midterm|mid term|test|\bE\d\b|quiz',name,re.I):
    m=re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',score)
    if m and float(m[2])>0 and float(m[1])/float(m[2])<0.7:
     short=re.split(r'\s+[-–(]\s*',name)[0].strip()[:28]
     out.append(short+' '+('%g'%float(m[1]))+'/'+('%g'%float(m[2])))
 except Exception:pass
 return out[:3]

def assignment_text(assignment_id):
 if not assignment_id:return None
 runs=sorted((BRIDGE/'Runs').glob('*/canvas'),key=lambda p:p.stat().st_mtime,reverse=True)[:2]
 for folder in runs:
  for f in folder.glob('*-detail-*.json'):
   v=read(f,{});a=v.get('assignment') or {}
   if str(a.get('id'))==str(assignment_id):
    # The source pane shows a readable copy of the instructions, not Canvas's raw JSON.
    from html import unescape
    desc=a.get('description') or ''
    desc=re.sub(r'(?i)<br\s*/?>|</p>|</li>|</h\d>','\n',desc);desc=re.sub(r'(?i)<li[^>]*>','\n• ',desc)
    desc=re.sub(r'\n{3,}','\n\n',re.sub(r'[ \t]+',' ',unescape(re.sub(r'<[^>]+>','',desc)))).strip()
    readable=STUDY/'assignment-text'/(slug(a.get('name') or str(assignment_id))+'-'+str(assignment_id)+'.txt')
    body=(a.get('name') or 'Assignment')+'\n'+('Due '+str(a.get('due_at'))+'\n' if a.get('due_at') else '')+'\n'+(desc or (v.get('body') or ''))+'\n'
    try:
     readable.parent.mkdir(parents=True,exist_ok=True)
     if not readable.exists() or readable.read_text()!=body:readable.write_text(body)
     path=str(readable)
    except OSError:path=str(f)
    return {'name':a.get('name'),'text':(v.get('body') or desc)[:3500],'path':path,'url':a.get('html_url') or v.get('url'),'captured_at':v.get('captured_utc')}
 return None

def match_problems(skill_text,course,catalog,usage,day,exam_soon,limit=3):
 want=words(skill_text);rows=[]
 for doc in catalog:
  if doc['course']!=course:continue
  exam_doc=bool(re.search(r'exam|midterm|sample|ex\d+pr|quiz|revision',doc['title'],re.I))
  for p in doc['problems']:
   if p.get('needs_figure'):continue
   last=usage.get(p['id'],{}).get('last_assigned')
   if last and 0<(day-date.fromisoformat(last)).days<6:continue   # today's picks stay stable across re-syncs
   have=words(' '.join(p.get('skills',[]))+' '+p.get('structure','')+' '+p['label'])
   body=words(p['prompt_text'][:800])
   if not want&have:continue   # the problem itself must be about the topic
   score=3*len(want&have)+len(want&body)
   if score<3:continue
   if p.get('has_official_solution'):score+=2
   if exam_soon and exam_doc:score+=3
   if usage.get(p['id'],{}).get('last_outcome')=='incorrect':score+=2
   if last==day.isoformat():score+=50
   rows.append((score,doc,p))
 rows.sort(key=lambda r:-r[0])
 return rows[:limit]

def official_solution_text(doc,problem):
 if not doc.get('solution_path') or not problem.get('solution_pages'):return None
 from school_hq_catalog import page_text
 pages=page_text([doc['solution_path']]).get(doc['solution_path'],[])
 return '\n\n'.join(pages[i-1][:4000] for i in problem['solution_pages'] if 0<i<=len(pages)) or None

JUNK=re.compile(r"(?i)\b(ip-?\s*restricted|mall|assignment|week\s*\d+|quiz\s*\d*|lab\s*\d*|attendance|reflection|responsibility|homework|hw\s*\d*|requires|respondus|lockdown|browser|canvas|closing|date|only|fix|this|for|early|exit|pm|am|\d{1,2}(?::\d\d)?)\b")
LOGISTICS=re.compile(r"(?i)\b(available|until|attempts?|before|after|due|opens?|closes?|closing|submit\w*|deadline|graded|grades?|posted|mostly|scheduled|session|room|online|in-?class|row|unresolved|applicability|acknowledged|lockdown|respondus|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*|mon\w*|tue\w*|wed\w*|thu\w*|fri\w*|sat\w*|sun\w*)\b")
def topic_from_title(name):
 # Only the part before a dash/semicolon names the topic; the rest is logistics.
 name=re.split(r'\s+[—–]\s+|;|\s-\s',name or '')[0]
 m=re.match(r'(?i)\s*(?:program|assignment|project|lab|hw|homework|pa)\s*\d*\s*:\s*(.+)',name)
 if m:name=m[1]   # "Program 3: Linked List Deletion" names its topic after the colon
 if LOGISTICS.search(name):name=LOGISTICS.sub(' ',name)
 t=re.sub(r'^\s*\d+(?:\.\d+)*\s*','',name or '');t=re.sub(r'\([^)]*\)','',t);t=re.sub(r'[—–-]+',' ',t)
 t=JUNK.sub(' ',t);t=re.sub(r'\s+',' ',t).strip(" :,'")
 return t if (len(t.split())>=2 or len(t)>=6) and len(t)<=70 else None

def clean_doc_title(title):
 t=re.sub(r'\.pdf$','',title,flags=re.I);t=re.sub(r'^[A-Z]{3}\d{4}C?_?','',t)
 t=re.sub(r'([a-z])([A-Z])',r'\1 \2',t);t=re.sub(r'([A-Za-z])(\d)',r'\1 \2',t);t=re.sub(r'[_()]+',' ',t)
 t=re.sub(r'\b(notes?|lecture|lec|slides?|part|week|unit|ch(?:apter)?|v)\b\s*\d*','',t,flags=re.I);t=re.sub(r'\b\d+\b','',t)
 t=re.sub(r'\bnum\b','number',t,flags=re.I);t=re.sub(r'\s+',' ',t).strip(' -')
 return (t[0].upper()+t[1:].lower()) if t else title

def slide_title(text):
 """First meaningful heading line of a lecture page (e.g. 'Modular Exponentiation')."""
 for line in (text or '').splitlines()[:12]:
  l=line.strip()
  if 4<=len(l)<=60 and re.search(r'[A-Za-z]{3}',l) and not re.search(r'cop|cot|mac|cis|ucf|fall|spring|professor|dr\.|page|\d{4}|http|@',l,re.I):
   return l.strip(' :-–')
 return None

def reported_scope(course,event,notes):
 """Topics you said an exam covers ("test 3 will include related rates and optimization")."""
 key=assess_key(event['name']);out=[]
 for n in notes or []:
  for ch in n.get('chips',[]):
   if ch.get('kind')=='scope_hint' and ch.get('course')==course and ch.get('topics') and (not ch.get('assessment') or assess_key(ch['assessment'])==key):
    out+=[t for t in ch['topics'] if t.lower() not in {x.lower() for x in out}]
 return out[:8]

def obligation_topics(course,event,assessments,day,is_test=False,notes=None):
 """Topics an upcoming obligation needs: published scope > the assignment's own
 title > what the most recent lectures cover (a test without published scope
 covers the unit, so it takes the last six lectures, not two)."""
 from school_hq_catalog import recent_teaching
 name=event['name'];words_e=words(name)
 for a in assessments:
  if a.get('course')!=course or a.get('status') in ('completed','cancelled') or not a.get('objectives'):continue
  same=(a.get('date')==event['date']) or len(words(a.get('name',''))&words_e)>=1 or (re.search(r'\blab\b',name,re.I) and re.search(r'\blab\b',a.get('name',''),re.I))
  if same:return [{'title':o['title'],'query':o['title']+' '+' '.join(o.get('formats',[])),'formats':o.get('formats',[])} for o in a['objectives']][:6],'published scope: '+a['name']
 said=reported_scope(course,event,notes) if is_test else []
 if said:return [{'title':x[:120],'query':x,'formats':[]} for x in said],'scope from your notes (unverified)'
 t=topic_from_title(name)
 if t:return [{'title':t,'query':t,'formats':[]}],'topic named in the assignment'
 out=[]
 for r in recent_teaching(course,ROOT,limit=6 if is_test and EXAM_NAME.search(name) else 2):
  title=slide_title(r['excerpt']) or clean_doc_title(r['doc']['title']);out.append({'title':title,'query':title+' '+r['excerpt'][:400],'formats':[],'teaching':r})
 if len({o['title'] for o in out})<len(out):
  for o in out:
   tt=re.sub(r'[A-Z]{3}\s?\d{4}C?|\d{2}(?:fall|spring|summer)','',o['teaching']['doc']['title'],flags=re.I)
   n=re.search(r'(?:notes?|lecture|lec|slides?)\s*(\d+)',tt,re.I) or re.search(r'(\d+)',tt)
   if n:o['title']+=' · notes '+str(int(n.group(1)))
 return out,('the lectures since the last exam (no published scope yet)' if is_test and EXAM_NAME.search(name) else 'what the latest lectures cover')

EXAM_NAME=re.compile(r'(?i)\b(?:exam|midterm|mid term|test|final)\b|exam\d')

def title_tokens(t):
 return {w for w in norm(re.sub(r'\s*—.*','',t or '')).split() if (len(w)>2 or w.isdigit()) and w not in STOP}

def best_skill(course,query,state,title=None):
 """The tracked skill a topic belongs to. With a topic title, the match must be
 close (same name, or most words shared, numbers included) so 'notes 10' never
 lands on another lecture's skill and inherits its status or mistakes."""
 if title:
  want=title_tokens(title);best=None;top=0.
  if not want:return None
  nums={w for w in want if w.isdigit()}
  for s in state['skills']:
   if s.get('course')!=course:continue
   have=title_tokens(s.get('name',''))
   if not have:continue
   if have==want:return s
   # Numbered titles are different documents/lectures when their numbers differ
   # ("lecture 10" vs "lecture 11"), however many other words they share.
   if nums and {w for w in have if w.isdigit()} and nums!={w for w in have if w.isdigit()}:continue
   j=len(want&have)/len(want|have)
   if j>top:best,top=s,j
  return best if top>=0.6 else None
 want=words(query);best=None;score=0
 for s in state['skills']:
  if s.get('course')!=course:continue
  n=len(want&words(s.get('name','')+' '+s['id'].split(':')[1].replace('-',' ')))
  if n>score:best,score=s,n
 return best if score>=1 else None

def teaching_ref(t):
 return {'title':t['doc']['title'],'path':t['doc']['path'],'page':t['page'],'excerpt':t['excerpt'][:1800],'url':t['doc'].get('source_url'),'captured_at':t['doc'].get('captured_at')}

# ---------- evidence, pacing and honest coverage ----------
# What a topic's evidence says, from the tracked skill (never a readiness %):
#   new         nothing attempted yet
#   practiced   attempted, but no independent correct answer yet (hinted, same-day retry)
#   error       the latest reviewed answer was wrong
#   independent one independent correct answer
#   retained    independent again after spacing, or transfer-checked
def topic_state(sk):
 if not sk or sk.get('status') in (None,'untested'):return 'new'
 if sk.get('last_error'):return 'error'
 if sk.get('status')=='transfer-checked' or sk.get('successes',0)>=2:return 'retained'
 if sk.get('status')=='demonstrated':return 'independent'
 return 'practiced'

def review_due(state,skill_id,day):
 return any(q['skill_id']==skill_id and q['due']<=day.isoformat() for q in state.get('review_queue',[]))

def paced_quota(outstanding,days,major):
 """How many outstanding topics of one obligation to plan today: everything in the
 last two days, otherwise spread over the days left (a midterm/final keeps its last
 two days for mixed review and the timed set)."""
 if outstanding<=0:return 0
 if days<=2:return outstanding
 spread=max(1,days-2 if major else days-1)
 return -(-outstanding//spread)

def assess_key(name):
 """'Exam2- Requires Respondus' -> 'exam2'; 'Test 3' -> 'test3'; 'FinalExam' -> 'final'."""
 m=re.search(r'(midterm|mid term|final|exam|test|quiz)\s*#?\s*(\d{1,2})?',norm(name))
 return (m[1].replace(' ','')+(m[2] or '')) if m else None

def reported_dates(notes):
 out=[]
 for n in notes:
  for ch in n.get('chips',[]):
   if ch.get('kind')=='date_report' and ch.get('course') in LABELS and ch.get('date'):
    out.append({'course':ch['course'],'name':ch.get('name') or 'Test','date':ch['date'],'note_id':n['id'],'text':n['text'][:200]})
 return out

def apply_reported_dates(state,notes,day):
 """A date you report in a note ('Calc test 3 is Nov 12') enters planning as an
 unverified 'reported' event. If Canvas lists the same assessment on a different
 date, the earlier date is planned for and the conflict is shown."""
 reports=[];lists=state.get('events',[]),state.get('_listed_deadlines',[])
 for r in reported_dates(notes):
  key=assess_key(r['name']);official=[e for L in lists for e in L if e.get('course')==r['course'] and e.get('date') and assess_key(e.get('name',''))==key and not e.get('reported')]
  row={**r,'status':'used','official_date':None}
  if official:
   o=min(official,key=lambda e:e['date']);row['official_date']=o['date']
   if o['date']==r['date']:row['status']='matches Canvas';reports.append(row);continue
   if o['date']<r['date']:row['status']='conflict: planning for the earlier Canvas date';reports.append(row);continue
   for e in official:e['superseded']=True
   row['status']='conflict: planning for your earlier date'
  if date.fromisoformat(r['date'])<day:continue
  label=LABELS[r['course']].split(' (')[0]+' '+r['name']
  state.setdefault('events',[]).append({'id':'note:'+r['note_id'],'course':r['course'],'name':r['name']+' (date you reported)','kind':'exam','date':r['date'],'certainty':'reported','reported':True})
  reports.append(row)
 return reports

UNDATED_SKIP=re.compile(r'(?i)placeholder|replacement|review|practice|survey|attendance|reflection|preparedness|syllabus|ungraded|first ?week|intro')
def undated_assessments(state,assessments,day,reports):
 """Known assessments with no date anywhere we can read: kept visible so they are
 never silently dropped (tell Genesis the date in a note to plan for it)."""
 dated={(e['course'],assess_key(e.get('name',''))) for L in (state.get('events',[]),state.get('_listed_deadlines',[])) for e in L if e.get('date')}
 dated|={(r['course'],assess_key(r['name'])) for r in reports}
 out={}
 try:
  book=read(BRIDGE/'Runs'/(read(BRIDGE/'grades.json',{}).get('request_id') or 'x')/'gradebooks.json',{})
 except Exception:book={}
 # Already scored in the gradebook means it happened, whatever the exam list says.
 dated|={(c,assess_key(x.get('name',''))) for c,entry in book.items() for x in entry.get('assignments',[]) if not UNDATED_SKIP.search(x.get('name','')) and re.search(r'\d\s*/\s*\d',str(x.get('score_displayed','')))}
 for a in assessments:
  if a.get('course') in LABELS and not a.get('date') and a.get('status','scheduled')=='scheduled':
   k=(a['course'],assess_key(a.get('name','')) or slug(a.get('name','')))
   if k not in dated:out.setdefault(k,{'course':a['course'],'name':re.split(r'\s+[—–]\s+|;',a['name'])[0][:80],'source':'exam list from announcements','scope':[o['title'] for o in a.get('objectives',[])][:6]})
 for course,entry in book.items():
  if course not in LABELS:continue
  for x in entry.get('assignments',[]):
   name=x.get('name','')
   if UNDATED_SKIP.search(name) or not re.search(r'(?i)\b(exam|midterm|test|final)\b|exam\d|finalexam',name):continue
   if (x.get('due') or '').strip() or re.search(r'\d\s*/\s*\d',str(x.get('score_displayed',''))):continue   # dated, or already scored
   k=(course,assess_key(name))
   if k in dated or k in out:continue
   out[k]={'course':course,'name':re.split(r'\s+[-–(]\s*',name)[0].strip()[:80],'source':'Canvas gradebook row with no date','scope':[]}
 return list(out.values())

def finished_today(day):
 """True when the plan already published for this day has every task checked
 correct (then a re-sync pulls the next paced topics forward)."""
 brief=(read(BRIDGE/'state.json',{}).get('brief') or {})
 if brief.get('date')!=day.isoformat() or not brief.get('tasks'):return False
 attempts=read(STUDY/'coaching-state.json',{}).get('attempts',[])
 good={a['exercise_id'].split(':retry')[0] for a in attempts if a.get('outcome')=='correct'}
 return all(t.get('exercise_id') in good for t in brief['tasks'] if not t.get('context_addition'))

def scope_confidence(basis):
 return 'published' if basis.startswith('published scope') else 'reported' if 'your notes' in basis else 'named' if 'named' in basis else 'inferred'

def make_plan(ident,day=None):
 import school_hq_coaching as c,school_hq_preparation as prep,school_hq_planning as pl,school_hq_context as ctx
 from school_hq_catalog import load_catalog,teaching_pages,recent_teaching
 day=day or today()
 base=c.load(ROOT);state=prep.planning_state(ROOT,copy.deepcopy(base))
 state['_verified_grades']=pl.verified_grades(ROOT);state['_listed_deadlines']=pl.listed_deadlines(ROOT)
 notes=ctx.active(day)
 reports=apply_reported_dates(state,notes,day)
 ranked=pl.priorities(state,day);course_rank={r['course']:r for r in ranked}
 candidates=c.candidates(state,day)
 catalog=load_catalog(ROOT);usage=read(STUDY/'catalog-usage.json',{})
 assessments=read(STUDY/'assessments.json',{'assessments':[]})['assessments']
 skills={s['id']:s for s in state['skills']}
 struggles=' '.join(n['text'] for n in notes if any(ch['kind']=='struggling' for ch in n['chips']))
 # Your notes about a course go to the writer of that course's tasks (labelled as your report).
 course_notes={course:' | '.join(n['text'][:160] for n in notes if any(ch.get('course')==course and ch['kind'] in ('note','struggling','scope_hint') for ch in n['chips']))[:400] or None for course in LABELS}
 ahead=finished_today(day)   # today's set is all done: pull the next paced topics forward
 slots=[];obligations=[];new_skills={};used_skills=set();deferred=[];uid=[0]

 def tag(slot):
  uid[0]+=1;slot['uid']=uid[0];return slot

 def make_slot(course,skill,topic_title,query,mode,priority,facts,exam_soon,teaching=None,group=None):
  name=topic_title or re.sub(r'\s*—.*','',skill.get('name') or skill['id'].split(':')[-1].replace('-',' '))
  if course_notes.get(course) and not facts.get('you_said'):facts['your_note_unverified']=course_notes[course]
  matches=match_problems(query+' '+name,course,catalog,usage,day,exam_soon)
  slot={'course':course,'skill_id':skill['id'],'skill_name':name,'mode':mode,'priority':priority,'facts':facts,'exam_soon':exam_soon,
        'problem':None,'reference':[],'teaching':teaching or [],'context_addition':False,'group':group}
  if matches:
   _,doc,p=matches[0]
   slot['problem']={'doc':{k:doc.get(k) for k in ('path','title','sha256','source_url','course','solution_path','format_profile')},'item':p}
   slot['reference']=[{'title':d['title'],'label':q['label'],'text':q['prompt_text'][:1200]} for _,d,q in matches[1:3]]
  else:
   docs=sorted([d for d in catalog if d['course']==course and d['problems']],key=lambda d:-len(words(' '.join(' '.join(q.get('skills',[])) for q in d['problems']))&words(query+' '+name)))
   if docs:
    slot['format_profile']=docs[0].get('format_profile',{})
    slot['reference']=[{'title':docs[0]['title'],'label':q['label'],'text':q['prompt_text'][:1200]} for q in docs[0]['problems'][:2]]
  if not slot['teaching'] and mode in ('learn','repair'):
   slot['teaching']=[teaching_ref(t) for t in teaching_pages(course,query+' '+name,ROOT,limit=2)]
  return tag(slot)

 def skill_for(course,title,query):
  sk=best_skill(course,query,state,title=title)
  if sk is None:
   sid=course+':'+slug(title);sk=skills.get(sid) or new_skills.get(sid) or {'id':sid,'course':course,'name':title,'status':'untested'}
  return sk

 def register(sk):
  if sk['id'] not in skills and sk['id'] not in new_skills:new_skills[sk['id']]={'id':sk['id'],'course':sk['course'],'name':sk['name'][:120]}

 # 1) Obligations: tests within two weeks (quizzes ten days) and graded work within five.
 #    Every topic of an obligation is listed with its evidence; today's share of the
 #    outstanding ones is paced over the days left, and nothing is dropped silently.
 mocked=set()   # one timed set per course per day; a midterm's set covers a quiz two days before it
 slotted={}   # (course, topic) -> slot already planned, so a quiz and an exam on the same lectures share it
 for course in LABELS:
  seen_listings=set()
  evs=course_events(state,course,day)
  major_days=[x['days'] for x in evs if x['exam'] and EXAM_NAME.search(x['name']) and 0<=x['days']<=6]
  for e in evs:
   if re.search(r'attendance|reflection|survey|syllabus',e['name'],re.I):continue
   is_test=e['exam'] or bool(re.search(r'\bquiz|\btest\b|\bexam',e['name'],re.I))
   major=is_test and bool(EXAM_NAME.search(e['name']))
   if e['days']<0 or e['days']>(14 if major else 10 if is_test else 5):continue
   listing=('major',e['date']) if major else (norm(re.sub(r'(?i)requires.*$','',e['name']))[:40],e['date'])
   if listing in seen_listings:continue   # the same item listed twice (gradebook + assignments)
   seen_listings.add(listing)
   topics,basis=obligation_topics(course,e,assessments,day,is_test,notes=notes)
   if e.get('certainty')=='reported':basis+=' · date from your note (unverified)'
   ob={'id':course+':'+slug(e['name'])+':'+e['date'],'course':course,'name':e['name'],'date':e['date'],'days':e['days'],'kind':'test' if is_test else 'assignment','basis':basis,'scope':scope_confidence(basis),'certainty':e.get('certainty'),'topics':[]}
   urgency=1000-e['days']*90+(160 if major else 40 if is_test else 0)+0.3*course_rank.get(course,{}).get('priority',0)
   assignment=None if is_test else assignment_text(e.get('assignment_id'))
   if not is_test and re.search(r'\bmall\b|reflection|lab\s*\d|survey|ip-?\s*restricted',e['name'],re.I):continue
   if not is_test and not topic_from_title(e['name']) and assignment and len(assignment['text'])>=200:
    # A programming assignment: teach its prerequisite, never solve it.
    sk=best_skill(course,assignment['text'][:600],state) or next((s for s in state['skills'] if s['course']==course),None)
    if sk:
     slot=tag({'course':course,'skill_id':sk['id'],'skill_name':sk.get('name',''),'mode':'prep','priority':urgency,'exam_soon':False,'group':ob['id'],'days':e['days'],
           'facts':{'course':LABELS[course],'assignment':e['name']+' · due '+e['date'],'days_until':e['days']},'assignment':assignment,'problem':None,'reference':[],
           'teaching':[teaching_ref(t) for t in teaching_pages(course,assignment['name']+' '+assignment['text'][:400],ROOT,limit=2)],'context_addition':False})
     slots.append(slot);used_skills.add(sk['id']);ob['topics'].append({'title':'Prerequisite for '+re.split(r'\s+[—–]\s+|;',e['name'])[0],'uid':slot['uid'],'state':topic_state(sk),'plan':'today'})
    obligations.append(ob);continue
   # Evidence for every topic, then today's paced share of what is still outstanding.
   rows=[]
   for t in topics:
    tkey=(course,t['title'].lower());sk=slotted[tkey]['_skill'] if tkey in slotted else skill_for(course,t['title'],t['query'])
    st=topic_state(sk);due=review_due(state,sk['id'],day)
    rows.append((t,tkey,sk,st,due or st in ('new','practiced','error')))
   outstanding=[r for r in rows if r[4]]
   quota=paced_quota(len(outstanding),e['days'],major)*(2 if ahead else 1)
   # Known mistakes first, then what was never studied, then due reviews, in the listed order.
   order=sorted(outstanding,key=lambda r:{'error':0,'new':1,'practiced':2}.get(r[3],3))
   today_keys={r[1] for r in order[:quota]}
   for i,(t,tkey,sk,st,need) in enumerate(rows):
    entry={'title':t['title'],'state':st,'uid':None}
    if not need:entry['plan']='covered';ob['topics'].append(entry);continue
    if tkey not in today_keys:
     entry['plan']='later';entry['reason']='paced: %d of %d outstanding topics are planned today, the rest on the days before %s'%(len(today_keys),len(outstanding),human(e['date']))
     ob['topics'].append(entry);continue
    if tkey in slotted:
     # Already planned for an earlier obligation: raise that slot to this one's urgency instead of duplicating it.
     prior=slotted[tkey];prior['priority']=max(prior['priority'],urgency-i)
     prior['facts']['also_on']=e['name']+' · '+e['date']+(' (formats: '+', '.join(t['formats'])+')' if t.get('formats') else '')
     prior['days']=min(prior.get('days',99),e['days'])
     entry.update(plan='shared',uid=prior['uid']);ob['topics'].append(entry);continue
    register(sk)
    mode='repair' if sk.get('last_error') else 'retrieval' if st in ('independent','retained') else 'learn'
    facts={'course':LABELS[course],'preparing_for':e['name']+' · '+e['date']+(' (in %d days)'%e['days'] if e['days'] else ' (today)'),'topic':t['title'],
           'scope_basis':basis,'expected_formats':', '.join(t.get('formats',[])) or None,'skill_status':sk.get('status'),'last_error':sk.get('last_error'),
           'course_grade':grade_facts(course),'low_exam_scores':recent_exam_scores(course)}
    teach=[teaching_ref(t['teaching'])] if t.get('teaching') else None
    slot=make_slot(course,sk,t['title'],t['query'],mode,urgency-i,facts,is_test,teach,ob['id']);slot['days']=e['days'];slot['_skill']=sk
    slots.append(slot);used_skills.add(sk['id']);slotted[tkey]=slot
    entry.update(plan='today',uid=slot['uid']);ob['topics'].append(entry)
   # Timed mixed set in exam conditions: three days out for any test, and a first
   # diagnostic one up to six days before a midterm/final, while there is time to fix gaps.
   if is_test and (e['days']<=3 or (major and e['days']<=6)) and topics and course not in mocked and (major or (e['days']<=3 and (state['_verified_grades'].get(course) or 100)<70 and not any(0<=m-e['days']<=2 for m in major_days))):
    pool=[(d,p) for d in catalog if d['course']==course and re.search(r'exam|midterm|sample|ex\d+pr|revision|quiz|lab',d['title'],re.I) for p in d['problems'] if not p.get('needs_figure')]
    pool=[(d,p) for d,p in pool if len(words(' '.join(p.get('skills',[]))+' '+p['structure'])&words(' '.join(t['query'] for t in topics)))>=1]
    picks=[];seen_struct=set()
    for d,p in sorted(pool,key=lambda x:(-x[1]['difficulty'],x[1]['id'])):
     if p['structure'] in seen_struct:continue
     seen_struct.add(p['structure']);picks.append((d,p))
     if len(picks)==3:break
    sk=best_skill(course,' '.join(t['query'] for t in topics),state) or next((s for s in state['skills'] if s['course']==course),None)
    if sk:
     slot=tag({'course':course,'skill_id':sk['id'],'skill_name':'timed set: '+e['name'],'mode':'mock','priority':urgency-20,'exam_soon':True,'group':ob['id'],'days':e['days'],
      'facts':{'course':LABELS[course],'exam':e['name']+' · '+e['date'],'topics':[t['title'] for t in topics],'scope_basis':basis,'course_grade':grade_facts(course)},
      'problem':None,'mock':[{'doc':{k:d.get(k) for k in ('path','title','sha256','source_url','solution_path')},'item':p} for d,p in picks] if len(picks)>=3 else [],
      'reference':[],'teaching':[],'context_addition':False})
     slots.append(slot);ob['topics'].append({'title':'Timed mixed set','uid':slot['uid'],'state':None,'plan':'today'});mocked.add(course)
   obligations.append(ob)

 # A topic paced for later in one obligation but planned today for another is shared.
 for ob in obligations:
  for t in ob['topics']:
   k=(ob['course'],t['title'].lower())
   if t.get('plan')=='later' and k in slotted:t.update(plan='shared',uid=slotted[k]['uid']);t.pop('reason',None)
 # 2) Fix recent mistakes and due spaced reviews not already covered.
 extra=[];planned_names={norm(s['skill_name']) for s in slots}
 for cand in candidates:
  sk=skills.get(cand['skill_id']);course=cand['course']
  if not sk or course not in LABELS or sk['id'] in used_skills:continue
  if norm(re.sub(r'\s*—.*','',sk.get('name',''))) in planned_names:continue   # same topic already planned under a sibling skill
  due=review_due(state,sk['id'],day)
  mode='repair' if sk.get('last_error') else 'retrieval' if due else 'learn'
  boost=(40 if mode=='repair' else 0)+(60 if struggles and words(sk.get('name',''))&words(struggles) else 0)   # an unrepaired misconception compounds
  if due:
   # Overdue reviews get more urgent every day they wait (forgetting is steepest early).
   when=min(q['due'] for q in state.get('review_queue',[]) if q['skill_id']==sk['id'])
   boost+=min(50,5*max(0,(day-date.fromisoformat(when)).days))
  if mode=='learn' and not boost:continue   # new material comes from obligations, not filler
  name=re.sub(r'\s*—.*','',sk.get('name') or sk['id'])
  facts={'course':LABELS[course],'skill':name,'skill_status':sk['status'],'mode':mode,'last_error':sk.get('last_error'),'review_due':due,
         'course_grade':grade_facts(course),'low_exam_scores':recent_exam_scores(course),'you_said':struggles[:200] if boost else None}
  extra.append(make_slot(course,sk,None,name,mode,cand['priority']+boost,facts,False))
  used_skills.add(sk['id'])
 # At most two repairs and three (short) reviews per course, so one bad week
 # doesn't crowd out everything else but due reviews are never starved by repairs.
 per={};kept=[]
 for sl in sorted(extra,key=lambda s:-s['priority']):
  k=(sl['course'],sl['mode']=='retrieval')
  if per.get(k,0)>=(3 if k[1] else 2):
   deferred.append(sl|{'_why':'at most %s per course per day; it stays in the queue'%('three reviews' if k[1] else 'two repairs')});continue
  per[k]=per.get(k,0)+1;kept.append(sl)
 # 2b) Exam recovery. A low exam starts diagnosis and repair of what it tested; it is
 # not a permanent label. Untested topics get a short check first (they are unknown,
 # not weak). Strong recent independent work in the course reduces the load, and a
 # course with a planned midterm/final keeps one recovery task only while failing.
 planned_major={o['course'] for o in obligations if o['kind']=='test' and EXAM_NAME.search(o['name'])}
 results=pl.exam_results(ROOT);strong={c for c in LABELS if pl.recently_strong(state,c,day)}
 for course in LABELS:
  rows=results.get(course,[]);lows=[r for r in rows if r['fraction']<0.7]
  grade=state['_verified_grades'].get(course);failing=isinstance(grade,(int,float)) and grade<70
  if not lows:continue
  want=2 if failing else 1
  if course in strong:want-=1
  if course in planned_major:want=min(want,1 if failing else 0)
  if any(x['course']==course and x['mode']=='repair' for x in kept):want-=1   # repairing known mistakes is recovery work too
  if want<=0:continue
  gap=sum(0.7-r['fraction'] for r in lows)/len(lows)
  pool=[]
  for a in assessments:   # what the low exams actually tested, when the scope was published
   if a.get('course')==course and a.get('status')=='completed':
    pool+=[(o['title'],o['title']+' '+' '.join(o.get('formats',[]))) for o in a.get('objectives',[])]
  pool+=[(re.sub(r'\s*—.*','',x.get('name') or x['id']),x.get('name') or x['id']) for x in state['skills'] if x['course']==course and x['status'] in ('untested','learning') and not x['id'].endswith('targeted-answer-check')]
  seen=set();pool=[p for p in pool if not (p[0].lower() in seen or seen.add(p[0].lower())) and (course,p[0].lower()) not in slotted]
  if not pool:continue
  start=day.toordinal()%len(pool);added=0
  for title,query in pool[start:]+pool[:start]:
   if added>=want:break
   sk=skill_for(course,title,query)
   if sk['id'] in used_skills:continue
   due=review_due(state,sk['id'],day);st=topic_state(sk)
   if st in ('independent','retained') and not due:continue
   register(sk)
   mode='repair' if sk.get('last_error') else 'retrieval' if due else 'diagnose' if st=='new' else 'learn'
   book=read(BRIDGE/'Runs'/(read(BRIDGE/'grades.json',{}).get('request_id') or 'x')/'gradebooks.json',{}).get(course,{})
   final_note='the gradebook has a "Final Exam Replacement" entry, so a strong final can replace a low test' if any(re.search(r'final exam replacement',x.get('name',''),re.I) for x in book.get('assignments',[])) else None
   facts={'course':LABELS[course],'recovering_from':', '.join(r['name']+' '+str(round(r['fraction']*100))+'%' for r in lows[:3]),'topic':title,
          'why':'checking and rebuilding what the low exams tested before the next exam and the final' if mode=='diagnose' else 'rebuilding what the low exams tested before the next exam and the final','skill_status':sk.get('status'),'last_error':sk.get('last_error'),
          'course_grade':grade_facts(course),'final_exam_note':final_note}
   slot=make_slot(course,sk,title,query,mode,round(280+120*gap-added,2),facts,False)
   slot['recovery']=True;kept.append(slot);used_skills.add(sk['id']);added+=1
 # 3) Missed classes: additive catch-up from the most relevant recent notes.
 catch=[]
 for n in notes:
  for chip in n['chips']:
   if chip['kind']!='missed_class' or not chip.get('course'):continue
   course=chip['course'];sk=next((s for s in state['skills'] if s['course']==course),None)
   pages=teaching_pages(course,n['text'],ROOT,limit=2) or recent_teaching(course,ROOT)
   if not sk or not pages:continue
   catch.append(tag({'course':course,'skill_id':sk['id'],'skill_name':'catch-up','mode':'catch_up','priority':0,'exam_soon':False,'group':None,
    'facts':{'course':LABELS[course],'your_note':n['text'][:300]},'problem':None,'reference':[],'teaching':[teaching_ref(t) for t in pages],'context_addition':True}))
 # One ranking for everything: an exam two weeks out should not outrank today's
 # recovery work just because it is an obligation.
 normal=sorted(slots+kept,key=lambda s:-s['priority'])
 # The size of today's sequence comes from need (pacing above), not from an invented
 # time budget. A daily limit applies only when you set one (study-profile daily_minutes).
 # Fill order: work due within three days; then, for each failing course (worst grade
 # first), its top repair of a known mistake and one recovery task; then the rest.
 profile=read(STUDY/'study-profile.json',{});limit=profile.get('daily_minutes')
 limit=limit if isinstance(limit,(int,float)) and not isinstance(limit,bool) and limit>0 else None
 grade_of=lambda c:state['_verified_grades'].get(c,100)
 reserved={}
 for sl in sorted([x for x in normal if x.get('recovery') or x['mode']=='repair'],key=lambda x:(grade_of(x['course']),-x['priority'])):
  if grade_of(sl['course'])<70 or sl.get('recovery'):reserved.setdefault((sl['course'],sl['mode']=='repair'),sl)
 order=[x for x in normal if x.get('days',99)<=3]+sorted(reserved.values(),key=lambda x:(grade_of(x['course']),x['mode']!='repair'))
 order+=[x for x in normal if not any(x is y for y in order)]
 spent=0;chosen=[]
 for sl in order:
  cost=MODE_MINUTES.get(sl['mode'],20);must=sl.get('days',99)<=3
  if len(chosen)>=MAX_TASKS:deferred.append(sl|{'_why':'today\'s sequence is full (%d tasks); it comes next'%MAX_TASKS});continue
  if not must and len(chosen)>=MAX_NORMAL:deferred.append(sl|{'_why':'today\'s sequence is full (%d tasks); it comes next'%MAX_NORMAL});continue
  if limit and not must and spent+cost>limit:deferred.append(sl|{'_why':'over the %d-minute daily limit you set'%limit});continue
  spent+=cost;chosen.append(sl)
 normal=[x for x in normal if any(x is y for y in chosen)]   # keep priority order for display
 # Planning again later the same day never brings back a task already checked correct today.
 done_keys={a['exercise_id'].split(':')[-2] for a in state.get('attempts',[]) if a.get('attempt_date')==day.isoformat() and a.get('outcome')=='correct' and a.get('exercise_id','').count(':')>=3}
 used=set();final=[];finished=set()
 for s in normal+catch[:4]:
  pid=(s.get('problem') or {}).get('item',{}).get('id')
  if pid and pid in used:s['problem']=None;pid=None
  s['key']=slot_key(s,pid,day)
  if s['key'] in done_keys:finished.add(s['uid']);continue
  if pid:used.add(pid)
  final.append(s)
 by_uid={s['uid']:s for s in final}
 for ob in obligations:
  ob['slots']=[s['key'] for s in final if s.get('group')==ob['id']]
  for t in ob['topics']:
   u=t.pop('uid',None)
   if u is None:continue
   if u in finished:t['plan']='covered';t['state']='independent'
   elif u in by_uid:t['key']=by_uid[u]['key'];t['mode']=by_uid[u]['mode']
   else:t['plan']='deferred';t['reason']=next((d['_why'] for d in deferred if d.get('uid')==u),'not planned today')
 later=[{'course':d['course'],'title':d['skill_name'],'mode':d['mode'],'reason':d['_why'],'for':next((o['name'] for o in obligations if o['id']==d.get('group')),None)} for d in deferred]
 for s in final:
  s.pop('_skill',None);s.pop('uid',None)
 plan={'schema':2,'request_id':ident,'day':day.isoformat(),'built_at':now(),'course_priorities':ranked,'slots':final,'obligations':obligations,'new_skills':list(new_skills.values()),
       'deferred':later,'undated':undated_assessments(state,assessments,day,reports),'date_reports':reports,'daily_limit_minutes':limit,'pulled_ahead':ahead,
       'notes':notes,'catalog_documents':len(catalog),'catalog_problems':sum(len(d['problems']) for d in catalog)}
 atomic(BRIDGE/'Runs'/ident/'plan.json',plan)
 return plan

def slot_key(s,pid,day):
 return sha_bytes(json.dumps({'c':s['course'],'s':s['skill_id'],'t':s['skill_name'],'m':s['mode'],'p':pid,'e':s['facts'].get('last_error'),'d':day.isoformat() if s['mode'] in ('mock','prep','catch_up') else None,'tp':s['facts'].get('topics') if s['mode']=='mock' else None},sort_keys=True).encode())[:16]

def human(iso):
 try:return date.fromisoformat(iso).strftime('%B %-d')
 except (TypeError,ValueError):return str(iso)

# ======================================================================
# Writing one task
# ======================================================================
ANSWER_TYPES=('code','code_trace','memory_trace','derivation','numeric','short_answer','proof','multiple_choice','table','explanation','mixed')
MODE_TEXT={
 'learn':'LEARN: the student has not shown this skill yet. Teach the core idea briefly, show one worked example on a different problem, then assign the problem.',
 'repair':'REPAIR: the student got this wrong recently (see last_error). Name the specific misconception plainly, teach the fix, then assign a problem with a DIFFERENT structure from the one they missed.',
 'retrieval':'RETRIEVAL: a spaced review is due. No teaching. Closed notes, from memory, one problem.',
 'mock':'MOCK EXAM SET: the exam is in a few days. Combine the given source problems into one timed set in exam conditions. Questions are the problems below, in order, labelled exactly as in the source. No teaching. Give a suggested time.',
 'prep':'PREP FOR GRADED WORK: a graded assignment is due soon. Teach the prerequisite concept it relies on with an original mini-problem. NEVER solve, outline or give code for the assignment itself.',
 'catch_up':'CATCH-UP: the student missed a class. Point to the exact lecture pages below, summarize the essential idea, and give one short original check question on it.',
 'diagnose':'DIAGNOSE: there is no evidence yet on this topic, which a low exam tested. No teaching. One short closed-book problem, typical of the exam, that shows whether the student can do it. In the rubric, map each likely wrong answer to its cause (choosing the method, setting up the problem, algebra or arithmetic, the concept itself, tracing or writing code) so the next task can target that cause.'}

def generation_prompt(slot,day,feedback=None):
 f=slot['facts'];lines=[]
 lines.append('Write ONE study task for a UCF student. Course: '+LABELS[slot['course']]+'. The app already chose what to study; make the task excellent and exact.')
 lines.append('\nPLANNER FACTS (use only these as reasons; do not invent others):\n'+'\n'.join('- '+k.replace('_',' ')+': '+(', '.join(v) if isinstance(v,list) else str(v)) for k,v in f.items() if v not in (None,'',[],False)))
 lines.append('\nMODE: '+MODE_TEXT[slot['mode']])
 if slot.get('problem'):
  d=slot['problem']['doc'];p=slot['problem']['item']
  lines.append('\nASSIGNED SOURCE PROBLEM — '+d['title']+', '+p['label']+', PDF page(s) '+', '.join(map(str,p['pages']))+' (answer type in catalog: '+p['answer_type']+'):\n<<<\n'+p['prompt_text']+'\n>>>')
  lines.append('Use it as the task problem with origin "exact_source" (faithful statement; you may reformat code and math into blocks). Use "adapted_source" only if it truly cannot stand alone; then say what changed in format_match. Set problem_label to "'+p['label']+'".')
  key=official_solution_text(d,p)
  if key:lines.append('\nOFFICIAL ANSWER KEY (private: use only inside private_solution, never in public fields):\n<<<\n'+key[:5000]+'\n>>>\nSet verification.method to "official_solution".')
 elif slot['mode']=='mock' and not slot.get('mock'):
  lines.append('\nWrite an ORIGINAL timed set of 3 problems that together cover these topics: '+', '.join(slot['facts'].get('topics',[]))+'. Match the professor\'s exam format (see references), mix structures (e.g. one trace, one write-code or derivation, one short explanation), number them Problem 1–3, and give a suggested total time in aids. origin "original_format_matched".')
 elif slot['mode']=='mock':
  for i,m in enumerate(slot['mock'],1):
   lines.append('\nSET PROBLEM %d — %s, %s, PDF page(s) %s:\n<<<\n%s\n>>>'%(i,m['doc']['title'],m['item']['label'],', '.join(map(str,m['item']['pages'])),m['item']['prompt_text']))
   key=official_solution_text(m['doc'],m['item'])
   if key:lines.append('Official key for set problem %d (private):\n<<<\n%s\n>>>'%(i,key[:3000]))
  lines.append('origin "exact_source"; problem_label lists the labels in order.')
 elif slot['mode']=='prep':
  a=slot['assignment'];lines.append('\nGRADED ASSIGNMENT (context only — do not solve it): '+a['name']+'\n<<<\n'+a['text'][:3000]+'\n>>>\nWrite an ORIGINAL mini-problem on the prerequisite; origin "original_format_matched".')
 else:
  lines.append('\nNo catalogued source problem fits. Write an ORIGINAL problem matched to this professor\'s format (origin "original_format_matched") and describe the match in format_match.')
 if slot['mode']=='mock' and not slot.get('mock') and not slot.get('reference'):
  from school_hq_catalog import load_catalog
  docs=[d for d in load_catalog(ROOT) if d['course']==slot['course'] and d['problems']]
  docs.sort(key=lambda d:0 if re.search(r'exam|midterm|sample|quiz|lab',d['title'],re.I) else 1)
  if docs:slot['format_profile']=docs[0].get('format_profile',{});slot['reference']=[{'title':docs[0]['title'],'label':q['label'],'text':q['prompt_text'][:1000]} for q in docs[0]['problems'][:3]]
 if slot.get('format_profile'):lines.append('\nPROFESSOR FORMAT PROFILE: '+json.dumps(slot['format_profile'])[:1500])
 for r in slot.get('reference',[]):lines.append('\nFORMAT REFERENCE ('+r['title']+', '+r['label']+'):\n<<<\n'+r['text']+'\n>>>')
 for t in slot.get('teaching',[]):lines.append('\nTEACHING REFERENCE — `'+t['title']+'` p. '+str(t['page'])+' (cite this exact page in a "read" step):\n<<<\n'+t['excerpt']+'\n>>>')
 lines.append('''
RULES
- Sound like a sharp tutor: short, concrete, no hedging, no disclaimers. Never ask the student to check grades, announcements, Canvas, email or logistics.
- steps: 3–6 ordered steps. Start each with the action verb in **bold** (only that word bold). Put exact things the student must find, type or match in backticks: document names, page ranges (`pp. 4–5`), problem labels (`Problem 4(b)`), function/class/variable names, key formulas. Nothing else in backticks.
- For learn/repair/catch_up/prep: first step = read the teaching reference page(s) (use them exactly as given) or study the explanation; then attempt; then check.
- Highlights in teaching_blocks, example_blocks, hint_blocks and prompt paragraphs: wrap in backticks only (a) code identifiers, expressions and formulas, and (b) the 1–3 key terms a paragraph teaches, on first mention only (e.g. `base case`, `heap`). Never highlight whole phrases, sentences, numbers in running prose, or the same term twice. Most sentences have no highlight.
- teaching_blocks (learn/repair/catch_up/prep only, else []): the core idea in at most 180 words, plus example_blocks: ONE worked example on a different problem. Never solve the assigned problem.
- hint_blocks: one nudge that does not reveal the answer.
- question: complete problem statement as plain text. prompt_blocks: the same problem as blocks — {"kind":"paragraph","text":...}, {"kind":"code","text":exact code,"language":"java"|"c"|...}, {"kind":"displayMath","text":LaTeX}. Inline math in paragraphs uses $...$.
- answer_type: one of '''+json.dumps(ANSWER_TYPES)+''' chosen by what the student must PRODUCE (a pointer trace is memory_trace even if the prompt shows code; only writing a program/function is code).
- aids: the conditions ("Closed notes, on paper", or the professor's exam rules). done_when: the observable output.
- answer_format: ONE short line telling the student how to write the answer in the box so it can be checked, in plain words with a tiny example (e.g. "Write: gcd = 7, s = 3, t = -10" or "One step per line, e.g. f'(x) = 3x^2"). Never ask for LaTeX or $ signs.
- private_solution: {"solution": complete worked answer, "rubric": what earns credit plus 2–3 common wrong answers and what each reveals, "verification": {"method": "official_solution"|"independent_calculation", "evidence": how you checked}, "code": solution code only (code tasks), "harness": complete program in the same language that calls the student's code and prints results, containing the exact line /*STUDENT*/ where the student's code is inserted (code tasks, when feasible), "tests": [{"stdin": "", "expected_stdout": ""}] (2–4, code tasks), "language"}.
- Absolute dates only; today is '''+day.strftime('%A, %B %-d, %Y')+'''. Never write today/tomorrow/yesterday, "mastered", "exam-ready" or "fully prepared".
- title: at most 80 characters, starts with a verb, names the concrete thing (e.g. "Trace `byeList` on a three-node list").
- Write dates the way a person says them ("November 5"), never as 2026-11-05.
- why_now: ONE sentence shown to the student, built from the planner facts (e.g. "Java Exam 2 was 14/100 on class design; this closes the first gap.").
- estimated_minutes (integer) and estimate_basis (short).
- cue: optional one-line memory cue with its limits.
JSON keys: title, kind ("learning"), why_now, steps, question, prompt_blocks, teaching_blocks, example_blocks, hint_blocks, aids, done_when, answer_format, answer_type, estimated_minutes, estimate_basis, cue, origin, format_match, problem_label, language, private_solution.''')
 if slot.get('avoid'):lines.append('\nANOTHER TASK TODAY ALREADY COVERS THIS — do not repeat its idea or problem type; choose a different idea from the teaching reference:\n'+slot['avoid'][:600])
 if feedback:lines.append('\nA reviewer rejected the previous version. Fix these problems:\n'+feedback[:2000])
 return '\n'.join(lines)

TODAY_WORDS=re.compile(r'\b(today|tomorrow|yesterday)\b',re.I)
def validate_generated(v,slot):
 if not isinstance(v,dict):raise ValueError('object required')
 for k in ('title','why_now','question','aids','done_when','estimate_basis'):
  if not isinstance(v.get(k),str) or not v[k].strip():raise ValueError('missing '+k)
 if len(v['title'])>110:raise ValueError('title too long')
 if not isinstance(v.get('steps'),list) or not 2<=len(v['steps'])<=8 or any(not isinstance(x,str) or not x.strip() for x in v['steps']):raise ValueError('2-8 string steps required')
 if v.get('answer_type') not in ANSWER_TYPES:raise ValueError('answer_type invalid')
 if v.get('origin') not in ('exact_source','adapted_source','original_format_matched'):raise ValueError('origin invalid')
 if not slot.get('problem') and not slot.get('mock') and v['origin']!='original_format_matched':raise ValueError('No source problem was assigned; origin must be original_format_matched')
 for k in ('prompt_blocks','teaching_blocks','example_blocks','hint_blocks'):
  b=v.get(k) or []
  if not isinstance(b,list) or any(not isinstance(x,dict) or x.get('kind') not in ('paragraph','code','displayMath') or not isinstance(x.get('text'),str) for x in b):raise ValueError(k+' invalid')
  v[k]=[{kk:x[kk] for kk in ('kind','text','language') if kk in x and isinstance(x[kk],str)} for x in b]
 if not v['prompt_blocks']:raise ValueError('prompt_blocks required')
 for k in ('problem_label','format_match','cue','language','estimate_basis','answer_format'):
  if isinstance(v.get(k),list):v[k]=', '.join(str(x) for x in v[k])
  elif v.get(k) is not None and not isinstance(v[k],str):v[k]=str(v[k])
 ps=v.get('private_solution')
 if not isinstance(ps,dict) or not str(ps.get('solution','')).strip() or not str(ps.get('rubric','')).strip():raise ValueError('private_solution with solution and rubric required')
 ver=ps.get('verification') or {}
 if ver.get('method') not in ('official_solution','independent_calculation','controlled_practice_tests') or not str(ver.get('evidence','')).strip():raise ValueError('verification method/evidence required')
 public=' '.join([v['title'],v['why_now'],v['question'],v['aids'],v['done_when'],*v['steps'],*[b['text'] for b in v['prompt_blocks']+v['teaching_blocks']+v['example_blocks']+v['hint_blocks']]])
 if TODAY_WORDS.search(public):raise ValueError('Use absolute dates, not today/tomorrow/yesterday')
 if re.search(r'\b(mastered|exam.ready|fully prepared)\b',public,re.I):raise ValueError('No readiness claims')
 if re.search(r'check (?:your )?(?:grades?|announcements?|canvas|email)',public,re.I):raise ValueError('No grade/announcement/logistics checks')
 sol=str(ps['solution'])
 if len(sol)>=16 and sol.lower() in public.lower():raise ValueError('The solution appears in public text')
 try:m=int(v.get('estimated_minutes'))
 except (TypeError,ValueError):raise ValueError('estimated_minutes integer required') from None
 v['estimated_minutes']=max(3,min(150,m))
 return v

# ---------- local test runs for code ----------
SANDBOX='(version 1)(allow default)(deny network*)(deny file-write*)(allow file-write* (subpath "{tmp}") (subpath "/private/var/folders") (subpath "/dev"))'
def tool(name):
 for p in ('/usr/bin/'+name,'/opt/homebrew/bin/'+name,'/usr/local/bin/'+name):
  if os.path.exists(p):return p
 return shutil.which(name)

def run_code(language,files,main_class=None,stdin='',timeout=10):
 """Compile and run in a temp dir with network and outside writes denied (macOS
 sandbox-exec). Returns (ok, stdout, stderr). Unavailable toolchains return None."""
 tmp=tempfile.mkdtemp(prefix='shq-run-')
 try:
  for name,text in files.items():Path(tmp,name).write_text(text)
  wrap=[]
  if os.path.exists('/usr/bin/sandbox-exec'):wrap=['/usr/bin/sandbox-exec','-p',SANDBOX.format(tmp=os.path.realpath(tmp))]
  if language=='java':
   javac,java=tool('javac'),tool('java')
   if not javac or not java or subprocess.run([java,'-version'],capture_output=True).returncode:return None
   c=subprocess.run(wrap+[javac,'-d',tmp]+[str(Path(tmp,n)) for n in files if n.endswith('.java')],capture_output=True,text=True,timeout=60,cwd=tmp)
   if c.returncode:return (False,'',c.stderr[-2000:])
   r=subprocess.run(wrap+[java,'-cp',tmp,main_class or 'Main'],input=stdin,capture_output=True,text=True,timeout=timeout,cwd=tmp)
  elif language=='c':
   cc=tool('clang') or tool('gcc')
   if not cc:return None
   c=subprocess.run(wrap+[cc,'-std=c11','-O0','-o',str(Path(tmp,'a.out'))]+[str(Path(tmp,n)) for n in files if n.endswith('.c')]+['-lm'],capture_output=True,text=True,timeout=60,cwd=tmp)
   if c.returncode:return (False,'',c.stderr[-2000:])
   r=subprocess.run(wrap+[str(Path(tmp,'a.out'))],input=stdin,capture_output=True,text=True,timeout=timeout,cwd=tmp)
  else:return None
  return (r.returncode==0,r.stdout[-4000:],r.stderr[-2000:])
 except subprocess.TimeoutExpired:return (False,'','Timed out')
 finally:shutil.rmtree(tmp,ignore_errors=True)

def java_main(text):
 m=re.search(r'public\s+class\s+(\w+)',text) or re.search(r'class\s+(\w+)[^{]*\{[^}]*static\s+void\s+main',text,re.S)
 return m[1] if m else 'Main'

def code_files(language,student,harness):
 """Combine the student's code with the private harness into one compilable file."""
 if '/*STUDENT*/' in harness:src=harness.replace('/*STUDENT*/',student)
 elif language=='c':
  m=re.search(r'\n[^\n]*\bint\s+main\s*\(',harness)
  src=(harness[:m.start()]+'\n'+student+'\n'+harness[m.start():]) if m else student+'\n'+harness
 else:
  if re.search(r'\b(class|interface|enum)\s+\w+',student):
   src=harness+'\n'+re.sub(r'\bpublic\s+(?=(?:abstract\s+|final\s+)?(?:class|interface|enum)\b)','',student)
  else:
   m=re.search(r'(?:public\s+)?static\s+void\s+main\s*\(',harness)
   src=(harness[:m.start()]+student+'\n'+harness[m.start():]) if m else harness+'\n'+student
 return {(java_main(harness)+'.java') if language=='java' else 'main.c':src}

def test_code(language,code,harness,tests):
 """Run tests; returns {'status': passed|failed|unavailable, 'details': [...]}"""
 if language not in ('java','c') or not code or not harness or not tests:return {'status':'unavailable','details':[]}
 details=[];files=code_files(language,code,harness)
 main=java_main(harness) if language=='java' else None
 for t in tests[:6]:
  r=run_code(language,files,main,t.get('stdin',''))
  if r is None:return {'status':'unavailable','details':['No '+language+' toolchain on this Mac']}
  ok,out,err=r
  passed=ok and out.strip()==str(t.get('expected_stdout','')).strip()
  details.append({'stdin':t.get('stdin','')[:200],'expected':str(t.get('expected_stdout',''))[:400],'got':out.strip()[:400],'error':err.strip()[:400],'passed':passed})
 return {'status':'passed' if all(d['passed'] for d in details) else 'failed','details':details}

# ---------- verification by a different model ----------
def public_text(v):
 parts=[]
 for b in v['prompt_blocks']:parts.append(('```'+b.get('language','')+'\n'+b['text']+'\n```') if b['kind']=='code' else ('$$'+b['text']+'$$' if b['kind']=='displayMath' else b['text']))
 return '\n\n'.join(parts)

def verify(v,slot,guard=None,client_factory=None):
 import school_hq_ai as ai
 ps=v['private_solution'];tests=None
 if v['answer_type']=='code' and ps.get('code'):
  tests=test_code(ps.get('language') or LANG.get(slot['course']),ps.get('code'),ps.get('harness'),ps.get('tests') or [])
  if tests['status']=='failed':return False,'The reference code fails its own tests: '+json.dumps(tests['details'])[:1200],tests
 solve='''Solve this '''+LABELS[slot['course']]+''' problem yourself, as an expert grader, before seeing anyone else's answer.
PROBLEM:
'''+public_text(v)+'''
Answer type expected: '''+v['answer_type']+'''
JSON: {"final_answer": concise final answer, "worked_solution": brief but complete reasoning, "well_posed": true/false, "issues": [ambiguities, missing information, impossible constraints]}'''
 compare='''Now compare with the author's reference solution and rubric below.
REFERENCE SOLUTION:
<<<
'''+str(ps['solution'])[:6000]+'''
>>>
RUBRIC:
<<<
'''+str(ps['rubric'])[:3000]+'''
>>>
JSON: {"agrees": true if the reference final answer is correct (equivalent forms count), "reference_correct": true/false, "issues": [specific errors in the reference or rubric], "leak": true if the public problem text gives away the answer, "summary": one sentence}'''
 def check(values):
  a,b=values
  if not isinstance(a,dict) or not isinstance(b,dict):raise ValueError('objects required')
  return {'well_posed':bool(a.get('well_posed',True)),'issues':list(a.get('issues',[]))[:6]+list(b.get('issues',[]))[:6],'agrees':bool(b.get('agrees')) and bool(b.get('reference_correct',True)),'leak':bool(b.get('leak')),'summary':str(b.get('summary',''))[:300],'answer':str(a.get('final_answer',''))[:500]}
 r=ai.run_turns('verify',[solve,compare],check,name='verify-'+slot['key'],timeout=600,guard=guard,client_factory=client_factory)
 ok=r['agrees'] and r['well_posed'] and not r['leak']
 return ok,('Independent check by '+ai.route('verify')[0]+': '+r['summary'] if ok else 'Independent check failed: '+'; '.join(map(str,r['issues']))+(' (answer leaks into problem text)' if r['leak'] else '')+(' (problem not well-posed)' if not r['well_posed'] else '')),tests

def similarity(a,b):
 wa,wb=words(a['title']+' '+a['question']),words(b['title']+' '+b['question'])
 return len(wa&wb)/max(1,len(wa|wb))

def build_task(slot,ident,day,guard=None,client_factory=None):
 import school_hq_ai as ai
 cached=read(CACHE/(slot['key']+'.json'),{}) if not slot.get('avoid') else {}
 if cached.get('task') and cached.get('day') and (day-date.fromisoformat(cached['day'])).days<=3:
  state=read(STUDY/'coaching-state.json',{})
  if not any(a.get('exercise_id')==cached['task']['exercise_id'] for a in state.get('attempts',[])):
   try:
    for s in cached['task']['sources']:
     if s['origin']!='original' and sha(s['snapshot'])!=s['sha256']:raise ValueError()
    return cached['task']
   except (OSError,ValueError,KeyError):pass
 feedback=None;last=''
 for attempt in range(2):
  v=ai.run_json('generate',generation_prompt(slot,day,feedback),lambda x:validate_generated(x,slot),name='task-'+slot['key'],timeout=900,guard=guard,client_factory=client_factory)
  ok,evidence,tests=verify(v,slot,guard,client_factory)
  if ok:break
  feedback=evidence;last=evidence
 else:raise RuntimeError('Task for '+slot['skill_name']+' failed independent verification: '+last[:300])
 ps=v['private_solution']
 ps['verification']={'method':ps['verification']['method'],'evidence':ps['verification']['evidence']+' | '+evidence+(' | Tests: '+tests['status'] if tests and tests['status']!='unavailable' else '')}
 sources=[]
 if slot.get('problem'):
  d=slot['problem']['doc'];p=slot['problem']['item']
  sources.append({**source_for(d['path'],d['title'],p['pages'],p['label']+' — '+p['structure'],d.get('source_url')),'role':'problem','search':p['anchor'][:80],'problem_id':p['id']})
 for m in slot.get('mock',[]):
  sources.append({**source_for(m['doc']['path'],m['doc']['title'],m['item']['pages'],m['item']['label'],m['doc'].get('source_url')),'role':'problem','search':m['item']['anchor'][:80],'problem_id':m['item']['id']})
 for t in slot.get('teaching',[]):
  sources.append({**source_for(t['path'],t['title'],[t['page']],'Read p. '+str(t['page']),t.get('url'),t.get('captured_at')),'role':'read'})
 if slot['mode']=='prep' and slot.get('assignment'):
  a=slot['assignment'];sources.append({**source_for(a['path'],a['name']+' (assignment instructions)',[],'Context only; do not solve here',a.get('url'),a.get('captured_at')),'role':'context'})
 if v['origin']!='exact_source':
  sources.append({'origin':'original','label':'Original practice' if v['origin']=='original_format_matched' else 'Adapted from the source','section':(v.get('format_match') or 'Matched to the professor\'s format')[:300]})
 if not sources:sources.append({'origin':'original','label':'Original practice','section':'Matched to the course format'})
 task={'exercise_id':slot['course']+':'+slug(slot['skill_name'])+':'+slot['key']+':'+sha_bytes(v['question'].encode())[:6],'course':slot['course'],'kind':'learning','title':v['title'].strip(),'question':v['question'].strip(),'reason':v['why_now'].strip(),
  'steps':[s.strip() for s in v['steps']],'aids':v['aids'].strip(),'done_when':v['done_when'].strip(),'prompt_blocks':v['prompt_blocks'],'teaching_blocks':v['teaching_blocks'] or None,'example_blocks':v['example_blocks'] or None,'hint_blocks':v['hint_blocks'] or None,
  'answer_type':v['answer_type'],'answer_format':(v.get('answer_format') or '').strip()[:200] or None,'origin':v['origin'],'format_match':v.get('format_match'),'problem_label':v.get('problem_label') or ((slot.get('problem') or {}).get('item') or {}).get('label'),'mode':slot['mode'],'language':ps.get('language') or LANG.get(slot['course']) if v['answer_type']=='code' else None,
  'estimated_minutes':v['estimated_minutes'],'estimate_basis':v['estimate_basis'],'cue':v.get('cue'),'skill_ids':[slot['skill_id']],'sources':sources,'private_solution':ps,'emphasis_version':1,'context_addition':slot['context_addition']}
 task={k:val for k,val in task.items() if val is not None}
 CACHE.mkdir(parents=True,exist_ok=True);atomic(CACHE/(slot['key']+'.json'),{'day':day.isoformat(),'task':task})
 return task

# ======================================================================
# Assessment facts from announcements (exam dates and scope)
# ======================================================================
def update_assessments(ident,guard=None,client_factory=None):
 import school_hq_ai as ai,school_hq_preparation as prep
 sources=[];texts=[]
 for f in sorted((BRIDGE/'Runs'/ident/'canvas').glob('*-announcements.json')):
  row=read(f,{})
  for item in (row.get('items') or [])[:15]:
   from html import unescape
   body=re.sub(r'<[^>]+>',' ',unescape(item.get('message') or ''));body=re.sub(r'\s+',' ',body)[:1500]
   if re.search(r'exam|test|midterm|quiz|final|cover|chapter|section|topics',item.get('title','')+' '+body,re.I):
    sid='S%d'%(len(sources)+1);sources.append((sid,f,row,item.get('title','')+' '+body));texts.append(sid+' ['+row.get('course','')+', posted '+str(item.get('posted_at',''))[:10]+'] '+item.get('title','')+': '+body)
 if not texts:return {'status':'no exam announcements'}
 digest=sha_bytes('\n'.join(texts).encode())
 state=read(STUDY/'facts-state.json',{})
 if state.get('digest')==digest:return {'status':'unchanged'}
 current=read(STUDY/'assessments.json',{'assessments':[]})['assessments']
 summary=[{'id':a['id'],'course':a['course'],'name':a['name'],'date':a.get('date'),'certainty':a.get('certainty'),'objectives':[o['title'] for o in a.get('objectives',[])]} for a in current]
 prompt='''Update a student's exam list from course announcements. Only use facts stated in the announcements; quote them.
CURRENT ASSESSMENTS:
'''+json.dumps(summary)[:6000]+'''
ANNOUNCEMENTS (each has a source id):
'''+'\n'.join(texts)[:16000]+'''
Return {"updates":[{"id": existing id to update or new "COURSE:slug", "course", "name", "date": "YYYY-MM-DD" or null, "time": "HH:MM" or null, "duration_minutes": int or null, "certainty": "confirmed"|"listed"|"conflicting"|"unknown", "status": "scheduled"|"completed"|"cancelled", "objectives": [{"id": slug, "title": topic as stated, "formats": ["e.g. code tracing","short answer"], "points": number or null}], "source_ids": ["S2"], "quote": exact sentence from that announcement supporting the date/scope}]}
Only include assessments whose date, scope or status the announcements actually change or add. Objectives only when the announcement lists topics. Empty list if nothing changes.'''
 def check(v):
  if not isinstance(v,dict) or not isinstance(v.get('updates'),list):raise ValueError('updates list required')
  return v
 v=ai.run_json('facts',prompt,check,name='facts',timeout=600,guard=guard,client_factory=client_factory)
 by_id={sid:(f,row,text) for sid,f,row,text in sources};merged={a['id']:a for a in current};changed=[]
 for u in v['updates'][:12]:
  try:
   refs=[by_id[s] for s in u.get('source_ids',[]) if s in by_id]
   if not refs or u.get('course') not in LABELS or not u.get('name'):continue
   if norm(u.get('quote',''))[:80] not in norm(' '.join(t for _,_,t in refs)):continue
   srcs=[{'origin':'official','label':row.get('course','')+' Canvas announcements','section':u['quote'][:300],'location':row.get('url',''),'snapshot':str(Path(f).resolve()),'sha256':sha(f),'captured_at':row.get('captured_utc')} for f,row,_ in refs]
   old=merged.get(u['id'],{});objectives=[]
   for o in u.get('objectives') or []:
    if not o.get('title') or not o.get('formats'):continue
    prior=next((x for x in old.get('objectives',[]) if x['id']==slug(o.get('id') or o['title'])),{})
    objectives.append({'id':slug(o.get('id') or o['title']),'title':o['title'][:160],'formats':[str(x)[:60] for x in o['formats']][:6],'points':o.get('points') if isinstance(o.get('points'),(int,float)) else None,'lesson_ids':prior.get('lesson_ids',[])})
   item={**old,'id':re.sub(r'[^A-Za-z0-9:._-]','-',u['id'])[:170],'course':u['course'],'name':u['name'][:160],'certainty':u.get('certainty') if u.get('certainty') in ('confirmed','listed','inferred','conflicting','unknown') else 'listed','status':u.get('status','scheduled'),'sources':srcs}
   if u.get('date'):date.fromisoformat(u['date']);item['date']=u['date']
   if u.get('time'):item['time']=u['time']
   if isinstance(u.get('duration_minutes'),int) and u['duration_minutes']>0:item['duration_minutes']=u['duration_minutes']
   if objectives:item['objectives']=objectives
   item.setdefault('objectives',[])
   prep.validate({'schema':1,'assessments':[item]},ROOT)
   merged[item['id']]=item;changed.append(item['id'])
  except (KeyError,ValueError,TypeError,OSError):continue
 if changed:
  old=STUDY/'assessments.json'
  if old.exists():atomic(STUDY/'AssessmentHistory'/(sha(old)+'.json'),read(old,{}))
  atomic(old,{'schema':1,'assessments':list(merged.values())})
 atomic(STUDY/'facts-state.json',{'digest':digest,'at':now(),'changed':changed})
 return {'status':'updated' if changed else 'no changes','changed':changed}

# ======================================================================
# Assembly and publication
# ======================================================================
def minutes_label(m):
 h,mm=divmod(int(m),60);return (str(h)+' h ' if h else '')+(str(mm)+' min' if mm or not h else '').strip()

def assemble(ident,day,plan,tasks,failures):
 import school_hq_preparation as prep
 from school_hq_source_use import candidates as practice_candidates
 normal=[t for t in tasks if not t.get('context_addition')];extra=[t for t in tasks if t.get('context_addition')]
 for t in tasks:t.pop('context_addition',None)
 total=sum(t['estimated_minutes'] for t in tasks)
 lead=normal[0]['reason'] if normal else ''
 limits=['Plan built from Canvas and your saved work on '+day.strftime('%B %-d')+'. '+str(plan['catalog_problems'])+' catalogued problems from '+str(plan['catalog_documents'])+' practice documents were available.']
 if failures:limits.append(str(len(failures))+' planned task(s) were dropped because they failed independent checking: '+'; '.join(f[:120] for f in failures[:4]))
 preparation=prep.write(ROOT);decisions=[]
 for c in practice_candidates(ROOT,preparation).get('required_decisions',[]):
  cited=[(t,s) for t in tasks for s in t['sources'] if s.get('sha256')==c['sha256']]
  if cited:
   pages=sorted({p for _,s in cited for p in s.get('pages',[])})
   decisions.append({'id':c['id'],'sha256':c['sha256'],'decision':'used','pages_read':pages,'problems':[t.get('problem_label') or t['title'] for t,_ in cited][:6],'reason':'Assigned as exact source practice by the planner.'})
  else:decisions.append({'id':c['id'],'sha256':c['sha256'],'decision':'deferred','pages_read':[],'problems':[],'reason':'Catalogued; higher-priority skills were planned first this sync.'})
 packet={'schema':2,'date':day.isoformat(),'title':day.strftime('%A, %B %-d'),'subtitle':str(len(tasks))+' tasks · about '+minutes_label(total)+(' · '+lead[:120] if lead else ''),
         'tasks':normal,'catch_up_tasks':extra,'new_skills':plan.get('new_skills',[]),'source_limits':'\n'.join(limits),'source_use':decisions,'engine_order':True}
 notes_path=BRIDGE/'Runs'/ident/'context-notes.json'
 if notes_path.exists():packet['context_notes']={'sha256':sha(notes_path)}
 return packet

def write_coverage(plan,tasks,failures,day):
 """Everything upcoming, topic by topic, with what the evidence says and what today
 does about it: planned (with its task), shared with another assessment's task,
 covered by earlier independent work, paced for a later day, or deferred (and why).
 Plus assessments with no date anywhere, and dates you reported."""
 written={sl['key']:t['exercise_id'] for sl in plan['slots'] for t in tasks if ':'+sl['key']+':' in t['exercise_id']}
 out=[]
 for ob in plan.get('obligations',[]):
  rows=[]
  for t in ob['topics']:
   plan_state=t.get('plan','later');ex=written.get(t.get('key'))
   if plan_state in ('today','shared') and not ex:plan_state='not_written'
   rows.append({'title':t['title'],'mode':t.get('mode') if plan_state in ('today','shared') else plan_state,'plan':plan_state,'state':t.get('state'),'reason':t.get('reason'),'exercise_id':ex})
  row={k:ob.get(k) for k in ('id','course','name','date','days','kind','basis','scope','certainty')};row['name']=re.split(r'\s+[—–]\s+|;',ob['name'])[0].strip()   # "Quiz 8", not its availability text
  row['topics']=rows;out.append(row)
 atomic(BRIDGE/'coverage.json',{'schema':2,'day':day.isoformat(),'obligations':out,'deferred':plan.get('deferred',[])[:12],'undated':plan.get('undated',[]),'reports':plan.get('date_reports',[]),
  'daily_limit_minutes':plan.get('daily_limit_minutes'),'dropped':failures[:6]})

def record_usage(tasks,day):
 usage=read(STUDY/'catalog-usage.json',{})
 for t in tasks:
  for s in t['sources']:
   if s.get('problem_id'):
    usage.setdefault(s['problem_id'],{});usage[s['problem_id']]['last_assigned']=day.isoformat();usage[s['problem_id']]['exercise_id']=t['exercise_id']
 atomic(STUDY/'catalog-usage.json',usage)

def run(ident,db=None,progress=None,guard=None,client_factory=None,day=None):
 import school_hq_ai as ai,school_hq_catalog as catalog,school_hq_context as ctx
 progress=progress or (lambda *a:None);day=day or today()
 try:ctx.settle(force=True,client_factory=client_factory)   # combine any phone session still open
 except Exception:pass
 atomic(BRIDGE/'Runs'/ident/'context-notes.json',{'notes':ctx.active(day)})
 progress('catalog',0.42,'Reading your practice files…')
 try:catalog.build(ROOT,guard,progress=lambda n,t:progress('catalog',0.42+0.1*n/max(1,t),'Reading practice files · '+str(n)+' of '+str(t)),client_factory=client_factory)
 except Exception as exc:
  if guard:guard()
  atomic(BRIDGE/'Runs'/ident/'catalog-error.json',{'error':str(exc)[:500]})
 progress('facts',0.53,'Checking announcements for exam changes…')
 try:update_assessments(ident,guard,client_factory)
 except Exception as exc:
  if guard:guard()
  atomic(BRIDGE/'Runs'/ident/'facts-error.json',{'error':str(exc)[:500]})
 progress('plan',0.58,'Choosing what to study…')
 plan=make_plan(ident,day)
 slots=plan['slots']
 if not slots:raise RuntimeError('Nothing to plan: no ranked skills were found. Your previous plan is preserved.')
 progress('write',0.6,'Writing '+str(len(slots))+' tasks…')
 results=ai.parallel(slots,lambda s:build_task(s,ident,day,guard,client_factory),on_done=lambda n,t:progress('write',0.6+0.33*n/t,'Writing and checking task '+str(n)+' of '+str(t)+'…'))
 if guard:guard()
 tasks=[];failures=[]
 for slot,r in results:
  if isinstance(r,Exception):failures.append(slot['skill_name']+': '+str(r)[:200])
  else:tasks.append(r)
 # Tasks are written in parallel, so two can land on the same exercise (e.g. two
 # lectures both yielding base-3 arithmetic). Rewrite the lower-priority twin once.
 # Only new-material tasks are rewritten: a repair, a spaced review or a timed set
 # repeats a skill on purpose, and two different source problems are never twins.
 by_slot={t['exercise_id']:sl for sl,t in results if not isinstance(t,Exception)}
 fresh=('learn','prep','catch_up','diagnose')
 def pid(t):return next((x.get('problem_id') for x in t['sources'] if x.get('problem_id')),None)
 for i,t in enumerate(list(tasks)):
  for u in tasks[:i]:
   if t['course']!=u['course'] or t.get('mode') not in fresh or u.get('mode') not in fresh or similarity(t,u)<0.45:continue
   if pid(t) and pid(u) and pid(t)!=pid(u):continue
   sl=dict(by_slot[t['exercise_id']]);sl['avoid']=u['title']+' — '+u['question'][:300]
   try:tasks[i]=build_task(sl,ident,day,guard,client_factory)
   except Exception as exc:failures.append(sl['skill_name']+': duplicate of another task; rewrite failed ('+str(exc)[:120]+')')
   break
 if not tasks:raise RuntimeError('No task passed independent checking. Your previous plan is preserved. '+' | '.join(failures[:3]))
 packet=assemble(ident,day,plan,tasks,failures)
 path=STUDY/(day.isoformat()+' - '+ident[:8]+' packet.json');atomic(path,packet)
 progress('publish',0.96,'Publishing your plan…')
 result=bridge('publish','--packet',str(path))
 record_usage(tasks,day)
 write_coverage(plan,tasks,failures,day)
 try:write_overview(day)
 except Exception:pass
 return result

def write_overview(day=None):
 """Small UI projection: per-course grade, skill progress, upcoming dates."""
 import school_hq_coaching as c,school_hq_preparation as prep,school_hq_planning as pl
 day=day or today()
 base=c.load(ROOT);state=prep.planning_state(ROOT,copy.deepcopy(base))
 state['_verified_grades']=pl.verified_grades(ROOT);state['_listed_deadlines']=pl.listed_deadlines(ROOT)
 import school_hq_context as ctx
 apply_reported_dates(state,ctx.active(day),day)
 ranked={r['course']:r for r in pl.priorities(state,day)};courses=[]
 for course in LABELS:
  skills=[s for s in base.get('skills',[]) if s.get('course')==course and not s['id'].endswith(':targeted-answer-check')]
  counts={k:sum(1 for s in skills if s.get('status')==k) for k in ('untested','learning','demonstrated','transfer-checked')}
  due=sum(1 for q in base.get('review_queue',[]) if q.get('due','9999')<=day.isoformat() and q['skill_id'].startswith(course+':'))
  events=[e for e in course_events(state,course,day) if -2<=e['days']<=21][:5]
  weak=[{'name':re.sub(r'\s*—.*','',s.get('name',s['id'])),'error':s.get('last_error')} for s in skills if s.get('last_error')][:4]
  courses.append({'id':course,'label':SHORT[course],'title':LABELS[course],'grade':grade_facts(course),'low_exams':recent_exam_scores(course),'skills':counts,'skill_total':len(skills),'due_reviews':due,
                  'events':events,'weak':weak,'priority':round(ranked.get(course,{}).get('priority',0),1)})
 courses.sort(key=lambda x:-x['priority'])
 upcoming=sorted([dict(e,course=c['id']) for c in courses for e in c['events'] if e['days']>=0],key=lambda e:e['date'])[:10]
 value={'schema':1,'as_of':now(),'day':day.isoformat(),'courses':courses,'upcoming':upcoming}
 atomic(BRIDGE/'overview.json',value);return value

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['plan','overview']);p.add_argument('--request-id',default='preview');a=p.parse_args()
 if a.action=='overview':print(json.dumps(write_overview()));return
 plan=make_plan(a.request_id)
 print(json.dumps([{'course':s['course'],'mode':s['mode'],'skill':s['skill_name'],'priority':round(s['priority'],1),'problem':((s.get('problem') or {}).get('item') or {}).get('label'),'teaching':[t['title']+' p.'+str(t['page']) for t in s.get('teaching',[])]} for s in plan['slots']],indent=1))
if __name__=='__main__':main()

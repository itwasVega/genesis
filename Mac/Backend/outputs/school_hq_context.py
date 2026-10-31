#!/usr/bin/env python3
"""Notes you type ("missed Monday's CS1 class", "recursion makes no sense") become
labelled chips that persist until they expire. The planner reads them; they are
your report, never treated as verified course evidence."""
import argparse,hashlib,json,os,re,sys,uuid
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
FILE=ROOT/'School HQ Study/context-notes.json'
ALIASES=__import__('school_hq_connections').aliases()   # from the student's own classes

def today():return datetime.now(__import__('school_hq_connections').zone()).date()
def load():
 try:v=json.loads(FILE.read_text())
 except (OSError,ValueError):v={}
 v.setdefault('schema',1);v.setdefault('notes',[]);return v
def save(v):
 from school_hq_coaching import atomic;atomic(FILE,v)

def courses_in(text):
 return [c for c,pat in ALIASES if re.search(pat,text,re.I)]

def chips(text,course=None):
 out=[];found=[course] if course else courses_in(text)
 if re.search(r'\b(missed|absent|skipped|wasn.t (?:in|at)|couldn.t (?:go|make it)|catch.?up)\b',text,re.I):
  out+= [{'kind':'missed_class','course':c,'label':'Missed class · '+c} for c in (found or [None])]
 if re.search(r"((?:don.t|didn.t|did not|do not|can.t) (?:get|understand)|confus|struggl|lost on|no idea|makes no sense|stuck on|weak (?:at|on)|bad at|hard for me)",text,re.I):
  out+= [{'kind':'struggling','course':c,'label':'Struggling · '+(c or 'topic')} for c in (found or [None])]
 if re.search(r'\b(exam|test|quiz|midterm|final)\b.*\b(covers?|cover(?:ing)?|includes?|including|on|about|chapters?|sections?|topics?|has|have)\b|\bwill be on\b',text,re.I):
  out+= [{'kind':'scope_hint','course':c,'label':'Exam scope hint · unverified'} for c in (found or [None])]
 rep=date_report(text)
 if rep:
  out=[x for x in out if x['kind']!='scope_hint']
  out+=[{'kind':'date_report','course':c,'label':rep['name']+' on '+rep['label']+' · your report','date':rep['date'],'name':rep['name']} for c in (found or [None])]
 if not out:out=[{'kind':'note','course':found[0] if found else None,'label':'Note'+(' · '+found[0] if found else '')}]
 return out

MONTHS={m:i for i,m in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],1)}
def date_report(text,day=None):
 """'Calc test 3 is Nov 12', 'exam 2 moved to 11/10' -> the assessment and date the
 student reports. Year comes from the next occurrence; never invented otherwise."""
 day=day or today()
 m=re.search(r'(?i)\b(exam|test|quiz|midterm|mid term|final(?: exam)?)\s*#?\s*(\d{1,2})?\b',text)
 if not m:return None
 tail=text[m.end():]
 d=re.search(r'(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b',tail) or re.search(r'(?i)\b(\d{1,2})/(\d{1,2})\b',tail)
 if not d or not re.search(r'(?i)\b(is|on|moved|move[sd]?|reschedul\w*|pushed|now|will be|changed|set for)\b',tail[:d.start()+1] if d.start() else tail):return None
 try:
  month,dd=(MONTHS[d[1][:3].lower()],int(d[2])) if d[1].isalpha() else (int(d[1]),int(d[2]))
  when=date(day.year,month,dd)
  if (when-day).days<-60:when=date(day.year+1,month,dd)
 except (ValueError,KeyError):return None
 kind=m[1].lower().replace('mid term','midterm').replace('final exam','final')
 name=kind.capitalize()+(' '+m[2] if m[2] else '')
 return {'name':name,'date':when.isoformat(),'label':when.strftime('%B %-d')}

def effect(note):
 """What this note actually changes, in words (shown under it in Tell Genesis)."""
 kinds={c['kind'] for c in note.get('chips',[])};courses=[c.get('course') for c in note.get('chips',[]) if c.get('course')]
 if 'date_report' in kinds:return 'Plans for this date until Canvas lists one; shown as your report, not a verified date.' if courses else 'Name the class (for example "Calc test 3 is Nov 12") so Genesis knows which test moved.'
 if 'missed_class' in kinds:return 'Adds a catch-up task with the lecture pages at the next sync.' if courses else 'Name the class (for example "missed CS1") so Genesis knows which lecture to catch you up on.'
 if 'struggling' in kinds:return 'Raises matching topics and is given to the task writer at the next sync.'
 if courses:return 'Given to the task writer for this course at the next sync.'
 return 'Not linked to a class, so it does not change the plan. Mention the class to use it.'

def add(text,course=None,ident=None,source=None,created_at=None,extra=None):
 text=text.strip()
 if not text or len(text)>2000:raise ValueError('Write 1–2000 characters')
 if course and course not in dict(ALIASES):course=None
 v=load()
 if ident and any(n['id']==ident for n in v['notes']):return next(n for n in v['notes'] if n['id']==ident)
 # The same text sent twice (a resend from the phone, a double tap) is one note.
 key=re.sub(r'\s+',' ',text.lower())
 for n in v['notes']:
  if re.sub(r'\s+',' ',n['text'].lower())==key and n.get('expires_on','')>=today().isoformat() and (n.get('chips') or [{}])[0].get('course')==(course or (chips(text,course)[0].get('course'))):return n
 made=chips(text,course)
 days=10 if any(c['kind']=='missed_class' for c in made) else 21 if any(c['kind']=='struggling' for c in made) else 14
 expires=(today()+timedelta(days=days)).isoformat()
 reported=[c['date'] for c in made if c['kind']=='date_report']
 if reported:expires=max(expires,(date.fromisoformat(max(reported))+timedelta(days=1)).isoformat())
 note={'id':ident or uuid.uuid4().hex[:12],'text':text,'created_at':created_at or datetime.now(timezone.utc).isoformat(),'source':source or 'mac','expires_on':expires,'chips':made,'authority':'student_report_unverified',**(extra or {})}
 for c in note['chips']:
  if c['kind']=='scope_hint' and (extra or {}).get('topics'):c.update(topics=extra['topics'][:8],assessment=extra.get('assessment'))
 v['notes'].append(note);v['notes']=v['notes'][-60:];save(v);return note

# --- Rapid-fire sessions --------------------------------------------------------
# On the phone you can fire off several short messages in a row ("test 3 will include
# related rates", "didn't get implicit differentiation", "also includes optimization and
# linear approximation"), then swipe the tab down when you're done. Each message carries a
# session id. Messages wait in a session buffer until the session is closed (or has been
# quiet for SESSION_IDLE minutes); then they are combined into self-contained notes, using
# earlier messages as context for later ones, and only then reach the planner.
SESSION_IDLE=10
LOCK=ROOT/'School HQ Study/.context.lock'

def locked(fn):
 def run(*a,**k):
  import fcntl
  LOCK.parent.mkdir(parents=True,exist_ok=True)
  with LOCK.open('a') as h:
   fcntl.flock(h,fcntl.LOCK_EX)
   try:return fn(*a,**k)
   finally:fcntl.flock(h,fcntl.LOCK_UN)
 return run

def receive(payload):
 """One message from the Mac or the phone. With a session id it joins that session's
 buffer; without one it is a note on its own (the old behaviour)."""
 sid=str(payload.get('session_id') or '')[:60]
 if not sid:
  return locked(add)(str(payload.get('text','')),course=payload.get('course'),ident=str(payload.get('id') or '')[:40] or None,source=payload.get('source'),created_at=payload.get('created_at'))
 result=locked(_buffer)(sid,payload)
 settle()
 return result

def _buffer(sid,payload):
 v=load();sessions=v.setdefault('sessions',{})
 if sid in v.get('settled_sessions',[]):
  # A straggler after the burst was combined becomes a note of its own, never lost.
  text=str(payload.get('text') or '').strip()
  if text:add(text,course=payload.get('course') if payload.get('course') in dict(ALIASES) else None,ident=str(payload.get('id') or '')[:40] or None,source=payload.get('source'),created_at=payload.get('created_at'),extra={'session_id':sid,'late':True})
  return {'session_id':sid,'status':'already combined'}
 s=sessions.setdefault(sid,{'course':None,'messages':[],'closed':False,'source':payload.get('source') or 'iphone','started':payload.get('created_at') or datetime.now(timezone.utc).isoformat()})
 course=payload.get('course') if payload.get('course') in dict(ALIASES) else None
 s['course']=s['course'] or course
 if payload.get('session_end'):
  s['closed']=True
  if isinstance(payload.get('count'),int):s['expected']=payload['count']
 text=str(payload.get('text') or '').strip()[:2000]
 mid=str(payload.get('id') or uuid.uuid4().hex)[:40]
 if text and not any(m['id']==mid for m in s['messages']):
  s['messages'].append({'id':mid,'text':text,'course':course,'seq':payload.get('seq') if isinstance(payload.get('seq'),int) else len(s['messages']),'at':payload.get('created_at') or datetime.now(timezone.utc).isoformat()})
 s['last']=datetime.now(timezone.utc).isoformat()
 save(v);return {'session_id':sid,'status':'closed' if s['closed'] else 'waiting','messages':len(s['messages'])}

def due_sessions(v,force=False):
 out=[]
 for sid,s in v.get('sessions',{}).items():
  if s.get('combining') and (datetime.now(timezone.utc)-datetime.fromisoformat(s['combining'])).total_seconds()<600:continue   # a crashed combine is retried after 10 minutes
  quiet=(datetime.now(timezone.utc)-datetime.fromisoformat(s.get('last',s['started']).replace('Z','+00:00'))).total_seconds()/60
  # Closed with every message arrived (the Mac imports a batch in parallel), or quiet for a while.
  if (s['closed'] and len(s['messages'])>=s.get('expected',0)) or force or quiet>=SESSION_IDLE:out.append(sid)
 return out

def settle(force=False,client_factory=None):
 """Combine every finished session into notes. Safe to call often; the model runs
 outside the lock so other messages can keep arriving."""
 done=[]
 for sid in locked(lambda:[x for x in due_sessions(load(),force) if not _claim(x)])():
  s=load()['sessions'].get(sid)
  if not s:continue
  msgs=sorted(s['messages'],key=lambda m:m['seq'])
  try:notes=combine(msgs,s.get('course'),client_factory) if msgs else []
  except Exception:notes=combine_simple(msgs,s.get('course'))
  locked(_finish)(sid,s,notes);done.append(sid)
 return done

def _claim(sid):
 v=load();s=v['sessions'].get(sid)
 if not s:return True
 s['combining']=datetime.now(timezone.utc).isoformat();save(v);return False

def _finish(sid,s,notes):
 ordered=sorted(s['messages'],key=lambda m:m['seq'])
 for n in notes:
  add(n['text'],course=n.get('course'),ident=sid[:20]+'-'+str(n['from'][0]),source=s.get('source'),created_at=s['started'],
      extra={'session_id':sid,'messages':[ordered[i]['text'] for i in n['from'] if i<len(ordered)],**{k:n[k] for k in ('assessment','topics') if n.get(k)}})
 v=load();v.get('sessions',{}).pop(sid,None);v['settled_sessions']=(v.get('settled_sessions',[])+[sid])[-200:];save(v)

CONTINUES=re.compile(r"(?i)^\s*(also|and|plus|oh and|it|that|this|those|they|too|as well|another|more|same)\b|^\s*(includes?|covers?|has|have|will have)\b")
SUBJECT=re.compile(r"(?i)\b((?:exam|test|quiz|midterm|final|lab exam|project|assignment|hw|homework|program)\s*#?\s*\d*)")
def combine_simple(msgs,course=None):
 """No model available: keep every message, carry the class forward, and prefix a
 continuation ("also includes X") with the last thing that was named."""
 out=[];subject=None;owner=None;cur=course
 for i,m in enumerate(msgs):
  t=m['text'];c=m.get('course') or (courses_in(t) or [None])[0] or cur
  named=SUBJECT.search(t)
  if CONTINUES.search(t) and not named and owner is not None and out[owner]['course']==c:
   out[owner]['text']=out[owner]['text'].rstrip('. ')+'; '+t.strip();out[owner]['from'].append(i)   # continues the last thing named
  else:
   if CONTINUES.search(t) and subject and not named:t=subject.strip()+': '+t
   out.append({'text':t,'course':c,'from':[i]})
   if named:subject=named[1];owner=len(out)-1
  cur=c
 return out

def combine(msgs,course=None,client_factory=None):
 if len(msgs)==1:return combine_simple(msgs,course)
 import school_hq_ai as ai
 lines='\n'.join('%d. %s'%(i,m['text']) for i,m in enumerate(msgs))
 prompt='''A student fired off these short messages to their study app, in this order, one right after another. Later messages often continue earlier ones ("also includes X and Y" continues "test 3 will include ..."; "that one too" points back). Combine them into self-contained notes.
Class picked on the phone (a hint, not a rule): '''+(course or 'none')+'''
Classes: '''+', '.join(c+' ('+l+')' for c,l in COURSE_LIST)+'''
MESSAGES:
'''+lines+'''
Rules:
- Every message number must appear in exactly one note's "from". Never drop or invent information.
- Merge messages that are about the same thing; keep separate things separate (an exam's scope, a topic the student is stuck on, a missed class, a date change are different notes).
- "text": one or two sentences in the student's own words, made self-contained by resolving references from earlier messages (e.g. "Calc test 3 will include related rates, optimization and linear approximation."). Keep their wording for topics; do not add topics, dates or facts they did not say.
- "course": the class code it is about, or null if unclear.
- For a note about what an exam/quiz/test covers: "assessment" (e.g. "Test 3") and "topics" (the topic names exactly as said). Otherwise omit both.
JSON: {"notes":[{"text":...,"course":...,"from":[0,2],"assessment":...,"topics":[...]}]}'''
 def check(v):
  notes=v['notes'];seen=[]
  for n in notes:
   if not isinstance(n.get('text'),str) or not n['text'].strip() or not isinstance(n.get('from'),list) or not n['from']:raise ValueError('text and from required')
   if n.get('course') not in dict(ALIASES):n['course']=None
   n['from']=sorted(int(i) for i in n['from']);seen+=n['from']
   if n.get('topics') is not None and not (isinstance(n['topics'],list) and all(isinstance(x,str) for x in n['topics'])):raise ValueError('topics must be a list of strings')
  if sorted(seen)!=list(range(len(msgs))):raise ValueError('every message must be used exactly once')
  return notes
 return ai.run_json('context',prompt,check,name='notes-session',timeout=180,client_factory=client_factory)

# --- iPhone inbox -------------------------------------------------------------
# The Genesis iPhone app writes one JSON file per note into iCloud Drive/Genesis/Notes.
# We import them here (on app launch, every minute while the app is open, and at every sync)
# and publish the course list the phone shows.
PHONE_CONFIG=ROOT/'School HQ Study/phone-inbox.json'

def icloud_root():
 """Where iCloud Drive lives on this Mac: a folder chosen in Settings wins, then the classic
 location, then the newer ~/Library/CloudStorage/iCloudDrive-* layout."""
 try:
  chosen=json.loads(PHONE_CONFIG.read_text()).get('icloud_root')
  if chosen:return Path(chosen)
 except (OSError,ValueError):pass
 classic=Path.home()/'Library/Mobile Documents/com~apple~CloudDocs'
 if classic.is_dir():return classic
 storage=sorted((Path.home()/'Library/CloudStorage').glob('iCloudDrive*'),key=lambda p:p.stat().st_mtime if p.exists() else 0,reverse=True)
 return storage[0] if storage else classic

ICLOUD=None
INBOX=None
from school_hq_connections import labels
COURSE_LIST=list(labels().items())

def inbox():
 global ICLOUD,INBOX
 if ICLOUD is None:ICLOUD=icloud_root()
 if INBOX is None:INBOX=ICLOUD/'Genesis'
 try:result=_inbox()
 except OSError as exc:result={'status':'error','detail':type(exc).__name__+': '+str(exc)[:200],'imported':0}
 result['checked_at']=datetime.now(timezone.utc).isoformat();result['folder']=str(INBOX)
 try:(ROOT/'School HQ App/Bridge/phone-inbox.json').write_text(json.dumps(result,indent=2))
 except OSError:pass
 return result

def _inbox():
 try:os.listdir(ICLOUD)
 except FileNotFoundError:return {'status':'icloud_drive_off','imported':0}
 except PermissionError:return {'status':'permission_needed','detail':'macOS blocked access to iCloud Drive. Allow Genesis under System Settings > Privacy & Security > Files and Folders (iCloud Drive).','imported':0}
 (INBOX/'Notes'/'Imported').mkdir(parents=True,exist_ok=True)
 courses={'schema':1,'updated_at':datetime.now(timezone.utc).isoformat(),'courses':[{'id':c,'label':l} for c,l in COURSE_LIST]}
 path=INBOX/'courses.json'
 try:current=json.loads(path.read_text())['courses']
 except (OSError,ValueError,KeyError):current=None
 if current!=courses['courses']:
  tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(courses,indent=2));tmp.replace(path)
 imported=0
 for f in sorted((INBOX/'Notes').glob('*.json')):
  try:
   n=json.loads(f.read_text())
   receive({**n,'source':'iphone'})
   imported+=1
  except (OSError,ValueError,KeyError,TypeError):continue      # half-synced file: try again next time
  try:f.replace(INBOX/'Notes'/'Imported'/f.name)
  except OSError:pass
 return {'status':'ok','imported':imported}

@locked
def remove(ident):
 v=load();before=len(v['notes']);v['notes']=[n for n in v['notes'] if n['id']!=ident];save(v);return before!=len(v['notes'])

def active(day=None):
 try:settle()
 except Exception:pass
 day=(day or today()).isoformat()
 return [{**n,'effect':effect(n)} for n in load()['notes'] if n.get('expires_on','9999')>=day]

def digest(notes):return hashlib.sha256(json.dumps(notes,sort_keys=True).encode()).hexdigest()

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['add','remove','list','inbox','settle']);p.add_argument('--id');a=p.parse_args()
 if a.action=='inbox':print(json.dumps(inbox()));return
 if a.action=='add':
  print(json.dumps(receive(json.load(sys.stdin))))
 elif a.action=='settle':print(json.dumps({'combined':settle(force=True)}))
 elif a.action=='remove':print(json.dumps({'removed':remove(a.id)}))
 else:print(json.dumps({'notes':active()}))
if __name__=='__main__':main()

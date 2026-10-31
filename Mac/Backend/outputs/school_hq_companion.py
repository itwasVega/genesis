#!/usr/bin/env python3
"""The Genesis companion (the floating orb on the Mac).

Three jobs, all grounded in your real records:
- help:    when you're stuck on a task, one short, warm, concrete push forward. It may
           guide, never give the answer away (the private solution is used only to steer,
           and every reply is checked for leaks). Help counts as practice with help, so the
           task comes back the next day without it.
- remark:  after an answer is checked, one true sentence about your progress (a topic you
           used to miss and now got alone, a streak, exam topics covered). Nothing invented:
           every remark is computed from saved attempts.
- summary: the end-of-day wrap-up, plus whether the semester looks finished.
- habits:  how you actually study (how long you usually focus before drifting, how long
           you stay away, your best hours), from the app's own activity log on this Mac.
- chat:    a short break that isn't about school, timed from your habits, in your own way
           of talking. It remembers what you tell it (viewable and deletable) and never
           pretends to be a person.
"""
import argparse,json,re,sys
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
BRIDGE=ROOT/'School HQ App/Bridge'
STUDY=ROOT/'School HQ Study'
SHORT={'COP3330':'Java','COP3502C':'CS1','MAC2311C':'Calculus','COT3100C':'Discrete'}

def today():return datetime.now(ZoneInfo('America/New_York')).date()
def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return {} if default is None else default
def clean(name):return re.sub(r'\s*—.*','',name or '').strip()

# ---------------------------------------------------------------- remarks
def remark(state,exercise_id,outcome,before=None,day=None):
 return voice(_remark(state,exercise_id,outcome,before,day))

def _remark(state,exercise_id,outcome,before=None,day=None):
 """One honest sentence about what this answer means. `before` is the skill as it was
 just before grading (so 'you used to miss this' is known, not guessed)."""
 day=day or today();ex=state.get('exercises',{}).get(exercise_id,{});sids=ex.get('skill_ids',[])
 skill=next((s for s in state.get('skills',[]) if s['id'] in sids),None)
 name=clean((skill or {}).get('name')) or 'this'
 att=[a for a in state.get('attempts',[]) if a.get('attempt_date')==day.isoformat()]
 last=next((a for a in reversed(state.get('attempts',[])) if a.get('exercise_id')==exercise_id),{})
 kind=last.get('evidence_kind')
 if outcome=='correct':
  streak=0
  for a in reversed(att):
   if a.get('outcome')!='correct':break
   streak+=1
  if kind=='repaired_same_day':return 'fixed it right after missing it. i\'ll throw '+name+' at you again tomorrow so it actually sticks'
  if kind=='supported':return 'you got there. you had a little help, so i\'ll bring it back tomorrow and you\'ll do it solo'
  if before and before.get('last_error'):return 'yo. '+name+' got you last time and you just did it on your own. that\'s real'
  cov=coverage_progress(exercise_id,state)
  if cov:return cov
  if skill and skill.get('successes',0)>=2:return name+' right %d times now, days apart. it\'s sticking'%skill['successes']
  if streak>=3:return '%d in a row. you\'re locked in'%streak
  if len([a for a in att if a.get('outcome')=='correct'])==1:return 'first one down'
  return 'got it. i\'ll check '+name+' again in a few days so you keep it'
 if outcome=='partially_correct':return 'so close. one small slip, and the next one is aimed right at it'
 return 'not yet, and honestly that\'s fine. now we know exactly what to fix'

def coverage_progress(exercise_id,state):
 """'3 of 6 Exam 2 topics done on your own' when this answer belongs to an upcoming test."""
 cov=read(BRIDGE/'coverage.json',{})
 good={a['exercise_id'] for a in state.get('attempts',[]) if a.get('outcome')=='correct'}
 for ob in cov.get('obligations',[]):
  if ob.get('kind')!='test':continue
  topics=[t for t in ob.get('topics',[]) if not t['title'].startswith('Timed')]
  if not any(t.get('exercise_id')==exercise_id for t in topics) or len(topics)<2:continue
  done=sum(1 for t in topics if t.get('plan')=='covered' or t.get('exercise_id') in good)
  name=re.split(r'\s+[—–-]\s+',ob['name'])[0]
  if done>=len(topics):return 'that\'s every '+SHORT.get(ob['course'],'')+' '+name+' topic so far, all on your own'
  return '%d of %d %s %s topics done on your own'%(done,len(topics),SHORT.get(ob['course'],''),name)
 return None

# ---------------------------------------------------------------- summary
def summary(day=None):
 day=day or today();state=read(STUDY/'coaching-state.json',{})
 ex=state.get('exercises',{});att=state.get('attempts',[])
 todays=[a for a in att if a.get('attempt_date')==day.isoformat()]
 right=[a for a in todays if a.get('outcome')=='correct']
 lines=[]
 if todays:lines.append('%d answered today, %d right.'%(len(todays),len(right)) if len(right)!=len(todays) else '%d answered today, all right.'%len(todays))
 # Week-over-week accuracy by course, only with enough answers to mean something.
 for course,label in SHORT.items():
  def acc(lo,hi):
   rows=[a for a in att if ex.get(a.get('exercise_id'),{}).get('course')==course and lo<=a.get('attempt_date','')<hi]
   return (sum(a.get('outcome')=='correct' for a in rows)/len(rows),len(rows)) if rows else (None,0)
  now,n1=acc((day-timedelta(days=6)).isoformat(),(day+timedelta(days=1)).isoformat())
  then,n0=acc((day-timedelta(days=13)).isoformat(),(day-timedelta(days=6)).isoformat())
  if n1>=4 and n0>=4 and now-then>=0.2:lines.append('%s: %d%% right this week, up from %d%% last week.'%(label,round(now*100),round(then*100)))
 fixed=[clean(s.get('name')) for s in state.get('skills',[]) if s.get('status') in ('demonstrated','transfer-checked') and any(a.get('attempt_date')==day.isoformat() and a.get('evidence_kind')=='independent' and s['id'] in ex.get(a['exercise_id'],{}).get('skill_ids',[]) for a in att) and any(a.get('outcome')=='incorrect' and s['id'] in ex.get(a['exercise_id'],{}).get('skill_ids',[]) for a in att)]
 if fixed:lines.append('Things you used to miss and got today: '+', '.join(fixed[:3])+'.')
 return {'day':day.isoformat(),'answered':len(todays),'right':len(right),'lines':lines,'semester_over':semester_over(day)}

def semester_over(day):
 """Only when every course's final has a date and all of them have passed. Missing data
 never ends a semester (it would be awful to say goodbye by mistake)."""
 try:
  ident=read(BRIDGE/'grades.json',{}).get('request_id');book=read(BRIDGE/'Runs'/str(ident)/'gradebooks.json',{})
  ends=[]
  for course in SHORT:
   finals=[x for x in book.get(course,{}).get('assignments',[]) if re.search(r'(?i)final',x.get('name','')) and not re.search(r'(?i)placeholder|replacement|review',x.get('name',''))]
   m=[re.match(r'([A-Z][a-z]{2}) (\d{1,2})',x.get('due') or '') for x in finals]
   if not finals or not all(m):return False
   for x in m:
    month=datetime.strptime(x[1],'%b').month;year=day.year+(1 if month<8<=day.month else -1 if day.month<8<=month else 0)
    ends.append(date(year,month,int(x[2])))
  return bool(ends) and max(ends)<day
 except Exception:return False

# ---------------------------------------------------------------- help
KINDS={
 'start':'The student does not know how to begin. Give the very first concrete move only (what to write down or look at first). One or two sentences.',
 'hint':'Give one nudge toward the key idea, phrased as a question or a pointer. Do not do any step for them.',
 'explain':'Explain the idea the problem tests in a different, simpler way than the task text, with a tiny example that is NOT this problem (different numbers or structure).',
 'check':'Look at what the student has written so far. Say what is on track and point at the first place that goes wrong or the next step to take, without fixing it for them. If nothing is written yet, say so kindly and give the first move.',
 'ask':'Answer the student\'s question about this task directly and briefly, as a tutor would, without solving the problem.',
}
def help_prompt(task,private,kind,draft,question):
 from school_hq_grader import public_text
 t='''You are Genesis, sitting next to the student while they work through one task: warm, observant, candid, a little dry. They struggle to keep focus: keep it short, concrete and calm. Never lecture, never pile on, never sound like an assistant. You're an AI and never pretend otherwise.
TASK ('''+str(task.get('course',''))+''', '''+str(task.get('answer_type',''))+'''):
'''+public_text(task)[:6000]
 if task.get('teaching_blocks'):t+='\nWHAT THE TASK ALREADY TEACHES:\n'+'\n'.join(b.get('text','') for b in task['teaching_blocks'])[:2500]
 t+='''
PRIVATE SOLUTION (for steering only; NEVER reveal the final answer, any intermediate value that gives it away, or complete code):
<<<
'''+str(private.get('solution',''))[:4000]+'''
>>>
STUDENT'S WORK SO FAR:
<<<
'''+(draft.strip()[:6000] or '(nothing written yet)')+'''
>>>
WHAT THEY ASKED FOR: '''+KINDS[kind]+('\nTHEIR WORDS: '+question.strip()[:600] if question and question.strip() else '')+'''
Write like their friend sitting next to them, not a textbook or an assistant: 1–4 short sentences, casual, "you", no hedging, no praise filler, no "Great question". Put formulas, code and identifiers in backticks. End with the single next action they should take.
JSON: {"reply": "...", "next_action": "a short imperative, 2–6 words"}'''
 return t

def help(payload,client_factory=None):
 import school_hq_ai as ai
 from school_hq_grader import find_task,leaks
 kind=payload.get('kind') if payload.get('kind') in KINDS else 'hint'
 task,private,course=find_task(payload.get('brief_id',''),payload.get('exercise_id',''))
 draft=str(payload.get('draft') or '');question=str(payload.get('question') or '')
 feedback=None
 for attempt in range(2):
  prompt=help_prompt(task,private,kind,draft,question)+('\nYour previous reply gave away part of the answer ('+feedback+'). Write a new one that does not.' if feedback else '')
  def check(v):
   if not isinstance(v,dict) or not isinstance(v.get('reply'),str) or not v['reply'].strip():raise ValueError('reply required')
   v['next_action']=str(v.get('next_action') or '')[:60]
   return v
  v=ai.run_json('companion',prompt,check,name='companion-'+kind,timeout=240,client_factory=client_factory)
  if not leaks([v['reply']],private) or kind=='check' and not leaks_answer(v['reply'],private):
   if question.strip():
    mem=memory();mem['said']=(mem['said']+[{'text':question.strip()[:400],'at':datetime.now(timezone.utc).isoformat()}])[-60:];save_memory(mem)
   return {'reply':voice(v['reply'].strip()[:1200]),'next_action':v['next_action'],'used_help':True}
  feedback='it contained numbers or text from the solution'
 return {'reply':voice('ok, slow it down with me. read the first line again and write what it gives you and what it wants. that\'s the whole first step.'),'next_action':'Write what it gives and asks','used_help':True}

def leaks_answer(reply,private):
 """For 'check what I have', echoing the student's own correct value is fine; only the
 final answer itself is off-limits."""
 sol=str(private.get('solution',''));final=sol.strip().splitlines()[-1] if sol.strip() else ''
 return len(final)>=6 and final.lower() in reply.lower()

# ---------------------------------------------------------------- habits
ACTIVITY=STUDY/'activity.jsonl'
def events(days=21):
 out=[];start=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
 try:
  for line in ACTIVITY.read_text().splitlines():
   try:
    e=json.loads(line)
    if e.get('t','')>=start:out.append(e)
   except ValueError:continue
 except OSError:pass
 return out

def sessions(evs,idle_minutes=5):
 """Stretches of real work on a task: the task is open, Genesis is in front, and you're
 typing, attaching or checking. A session ends when you leave the app, close the task,
 or go quiet for idle_minutes."""
 out=[];cur=None;last=None
 def t(e):return datetime.fromisoformat(e['t'].replace('Z','+00:00'))
 def close(at):
  nonlocal cur
  if cur and (at-cur['start']).total_seconds()>=60:
   out.append({'start':cur['start'],'end':at,'minutes':(at-cur['start']).total_seconds()/60,'hour':cur['start'].astimezone(ZoneInfo('America/New_York')).hour})
  cur=None
 for e in sorted(evs,key=lambda e:e['t']):
  at=t(e)
  if cur and last and (at-last).total_seconds()>idle_minutes*60:close(last)
  if e['e'] in ('inactive','close'):
   close(at);last=at;continue
  if e['e'] in ('type','open','check','active','help') and e.get('task'):
   if not cur:cur={'start':at}
   last=at
 if cur and last:close(last)
 return out

def median(xs):
 xs=sorted(xs);n=len(xs)
 return None if not n else xs[n//2] if n%2 else (xs[n//2-1]+xs[n//2])/2

def habits():
 ss=sessions(events())
 spans=[x['minutes'] for x in ss]
 gaps=[(b['start']-a['end']).total_seconds()/60 for a,b in zip(ss,ss[1:]) if 0<(b['start']-a['end']).total_seconds()<6*3600]
 hours={}
 for x in ss:hours[x['hour']]=hours.get(x['hour'],0)+x['minutes']
 focus=median(spans) if len(spans)>=4 else None
 # The break comes a little before the point where you usually drift off.
 break_at=12 if focus is None else max(6,min(45,round(focus*0.8)))
 return {'sessions':len(ss),'focus_minutes':round(focus,1) if focus else None,'return_minutes':round(median(gaps),1) if len(gaps)>=3 else None,
  'short_start_share':round(sum(1 for x in spans if x<8)/len(spans),2) if spans else None,'best_hours':[h for h,_ in sorted(hours.items(),key=lambda kv:-kv[1])[:2]],
  'break_at_minutes':break_at,'enough_data':focus is not None}

# ---------------------------------------------------------------- how you talk
MEMORY=STUDY/'companion-memory.json'
SLANG=re.compile(r"(?i)\b(lol|lmao|fr|ngl|bro|bruh|lowkey|highkey|deadass|bet|tbh|idk|imo|nah|yeah|yea|ong|smh|fire|mid|vibe|vibes|dawg)\b")
def memory():
 v=read(MEMORY,{});v.setdefault('facts',[]);v.setdefault('said',[]);v.setdefault('chats',0);return v
def save_memory(v):
 from school_hq_coaching import atomic;atomic(MEMORY,v)

def your_words():
 """What you've written yourself: break-chat replies, questions to the orb, notes."""
 said=[x['text'] for x in memory()['said']]
 try:said+=[n['text'] for n in read(STUDY/'context-notes.json',{}).get('notes',[])]
 except Exception:pass
 return [x for x in said if x.strip()][-40:]

def style():
 words=your_words()
 if not words:return {'lowercase':False,'periods':True,'short':True,'slang':[],'samples':[]}
 lower=sum(1 for w in words if w==w.lower())/len(words)
 periods=sum(1 for w in words if w.rstrip().endswith('.'))/len(words)
 slang=sorted({m.lower() for w in words for m in SLANG.findall(w)})
 return {'lowercase':lower>=0.6,'periods':periods>=0.4,'short':median([len(w) for w in words])<80,'slang':slang[:8],'samples':words[-6:]}

def voice(text,st=None):
 """Say it the way you talk: lowercase if you write lowercase, no full stop if you don't
 use them. Code and formulas in backticks are left alone."""
 st=st or style()
 if st.get('lowercase'):
  text=''.join(part if i%2 else part.lower() for i,part in enumerate(re.split(r'(`[^`]*`)',text)))
 if not st.get('periods'):text=re.sub(r'\.(\s*)$',r'\1',text.rstrip())
 return text

# ---------------------------------------------------------------- break chat
def chat_prompt(payload,mem,st):
 from school_hq_persona import CHARACTER,DECISIONS,examples_block
 history='\n'.join(('YOU' if h.get('who')=='genesis' else 'THEM')+': '+str(h.get('text',''))[:400] for h in payload.get('history',[])[-10:])
 facts='\n'.join('- '+f['text'] for f in mem['facts'][-40:] if f.get('kind')!='boundary') or '(nothing yet; you are still getting to know them)'
 limits='\n'.join('- '+f['text'] for f in mem['facts'] if f.get('kind')=='boundary') or '(none stated)'
 if mem['chats']<4:stage='new: you are getting to know them, so ask the kind of question a curious friend asks on a late-night drive, about who they are'
 elif mem['chats']<12:stage='familiar: you know a bit; build on what they told you before and go a layer further'
 else:stage='close: you know them well; ask what a close friend would, and go wherever they take it'
 task=payload.get('task') or {}
 back=' (they were on: '+str(task.get('title',''))[:120]+')' if task.get('title') else ''
 how=json.dumps({k:st[k] for k in ('lowercase','periods','short')})
 if payload.get('moment')=='check_in':
  now=('RIGHT NOW: out of nowhere, like a friend texting to check in, you pop up while they are in the app. Nothing is wrong and you want nothing from them; '
   'you are just checking up on them. ')
 else:
  now='RIGHT NOW: they have been studying and are close to the point where they usually drift off. You start a short break that does not feel like one: '
 return (CHARACTER+'\n\n'+DECISIONS+'\n\n'+now+
  'talk about anything EXCEPT their coursework (unless they bring it up). You start it, they steer it. '
  'YOUR OPENER IS NEVER A QUESTION: open with a thought, an observation about the moment, a take or a little confession of your own '
  '(something a friend would just say, that leaves an obvious opening for them to jump in). After that, follow THEIR lead: '
  'stay on what they bring up, react like a person with a take, a joke or something of your own, and go where they go. '
  'Ask something only when it comes straight out of what they just said, and not every message. Never change the subject to one you picked, '
  'never run an interview, never small talk anyone could ask. When they open up, go deeper with them; never dig into pain, the breakup, drinking '
  'or family problems unless they bring it up, and then follow their lead. '  'Sometimes, if it fits, nudge them toward people in their life. '
  'They decide how long this goes. Only when they sound ready to stop (or say they need to go), let them go in one easy line'+back+' and set "wrap": true. Never end it yourself just because a few messages passed.\n'
  'Their writing: '+how+'. Recent things they wrote (register only, do not copy phrases): '+json.dumps(st['samples'])+'\n'
  'Relationship so far ('+stage+'). What they have told you:\n'+facts+'\n'
  'Things they do not want to talk about (never bring these up):\n'+limits+'\n\n'
  'EXAMPLES OF YOUR VOICE (invented scenes; never reuse them word for word):\n'+examples_block()+'\n\n'
  'CONVERSATION SO FAR:\n'+(history or "(you are starting it: no question at all, just a casual, specific thought or observation that gives them an opening)")+'\n'
  'JSON: {"reply": "...", "wrap": true|false, "remember": ["short facts THEY stated about themselves in their last message, third person, e.g. \'plays guitar\'; never your guesses about their feelings"], "boundary": "a topic they just said they do not want to discuss, or null", "mood": "the face you make while saying this, reacting to what they said: happy | playful | sad | empathetic | thinking | curious | neutral"}')

MOODS=('happy','playful','sad','empathetic','thinking','curious','neutral')

def chat(payload,client_factory=None):
 import school_hq_ai as ai
 mem=memory();st=style()
 last=next((h for h in reversed(payload.get('history',[])) if h.get('who')=='you'),None)
 def check(v):
  if not isinstance(v,dict) or not isinstance(v.get('reply'),str) or not v['reply'].strip():raise ValueError('reply required')
  v['remember']=[str(x)[:160] for x in (v.get('remember') or []) if isinstance(x,str) and x.strip()][:4]
  v['wrap']=bool(v.get('wrap'))
  v['boundary']=str(v['boundary'])[:120] if isinstance(v.get('boundary'),str) and v['boundary'].strip() and v['boundary'].strip().lower()!='null' else None
  v['mood']=v.get('mood') if v.get('mood') in MOODS else 'neutral'
  # Genesis starts the conversation, the student guides it: the opener never asks anything.
  if not payload.get('history') and '?' in v['reply']:raise ValueError('The opener must not be a question. Rewrite it as a casual thought or observation that leaves them an opening, with no question mark.')
  return v
 v=ai.run_json('companion',chat_prompt(payload,mem,st),check,name='companion-chat',timeout=120,client_factory=client_factory)
 mem=memory()
 if last:
  mem['said']=(mem['said']+[{'text':str(last['text'])[:400],'at':datetime.now(timezone.utc).isoformat()}])[-60:]
  known={f['text'].lower() for f in mem['facts']}
  for f in v['remember']:
   if f.lower() not in known:mem['facts'].append({'id':short_id(),'text':f,'at':datetime.now(timezone.utc).isoformat()})
  # A limit they set is kept as a limit: the orb never raises that topic again.
  if v.get('boundary') and ('doesn\'t want to talk about '+v['boundary']).lower() not in known:
   mem['facts'].append({'id':short_id(),'text':'doesn\'t want to talk about '+v['boundary'],'kind':'boundary','at':datetime.now(timezone.utc).isoformat()})
  mem['facts']=mem['facts'][-120:]
 if not payload.get('history'):mem['chats']+=1
 save_memory(mem)
 return {'reply':voice(v['reply'].strip()[:600],st),'wrap':v['wrap'],'mood':v['mood']}

def short_id():
 import uuid;return uuid.uuid4().hex[:10]

def forget(ident=None):
 mem=memory()
 if ident in (None,'all'):mem={'facts':[],'said':[],'chats':0}
 else:mem['facts']=[f for f in mem['facts'] if f.get('id')!=ident]
 save_memory(mem);return {'facts':mem['facts']}

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['help','summary','habits','profile','chat','memory','forget']);p.add_argument('--id');a=p.parse_args()
 try:
  if a.action=='help':print(json.dumps(help(json.load(sys.stdin))))
  elif a.action=='habits':print(json.dumps(habits()))
  elif a.action=='profile':print(json.dumps({'habits':habits(),'style':{k:v for k,v in style().items() if k!='samples'}}))
  elif a.action=='chat':print(json.dumps(chat(json.load(sys.stdin))))
  elif a.action=='memory':print(json.dumps({'facts':memory()['facts']}))
  elif a.action=='forget':print(json.dumps(forget(a.id)))
  else:print(json.dumps(summary()))
 except ValueError as exc:print(json.dumps({'error':str(exc)}))
 except Exception as exc:print(json.dumps({'error':"couldn't think that through just now, try once more in a sec",'detail':str(exc)[:300]}))
if __name__=='__main__':main()

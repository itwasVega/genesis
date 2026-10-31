"""Regression tests for Genesis planning and learning policies (no network, no models).
Run: python3 tests/test_policies.py"""
import json,os,sys,re
from pathlib import Path
from datetime import date,timedelta

HERE=Path(__file__).resolve().parent
src=(HERE/'test_engine.py').read_text().rsplit('\nmain()',1)[0]
NS={'__name__':'fixture','__file__':str(HERE/'test_engine.py')};exec(compile(src,'test_engine.py','exec'),NS)
root=NS['setup']();FakeClient=NS['FakeClient']
sys.path.insert(0,str(root));os.chdir(root)
for m in list(sys.modules):
 if m.startswith('school_hq'):del sys.modules[m]
import school_hq_engine as E,school_hq_coaching as C,school_hq_context as X,school_hq_planning as PL,school_hq_grader as G
T=E.today();fails=[];passed=[0]
def check(name,cond,detail=''):
 if cond:passed[0]+=1
 else:fails.append(name+(' :: '+str(detail) if detail else ''))

# ---------- 1. numbered titles never share a skill; same/alias titles do ----------
st={'skills':[{'id':'MAC2311C:l10','course':'MAC2311C','name':'Class lecture 10 derivatives','status':'demonstrated'},
              {'id':'MAC2311C:chain','course':'MAC2311C','name':'Chain rule practice problems','status':'learning'}]}
check('lecture 11 does not inherit lecture 10',E.best_skill('MAC2311C','',st,title='Class lecture 11 derivatives') is None)
check('same lecture title matches',(E.best_skill('MAC2311C','',st,title='class Lecture 10 Derivatives') or {}).get('id')=='MAC2311C:l10')
check('reworded title still matches',(E.best_skill('MAC2311C','',st,title='Chain rule problems') or {}).get('id')=='MAC2311C:chain')

# ---------- 2. pacing ----------
check('pace: last two days take everything',E.paced_quota(5,2,True)==5)
check('pace: midterm in 7 days spreads 5 topics',E.paced_quota(5,7,True)==1)
check('pace: quiz in 3 days, 3 topics',E.paced_quota(3,3,False)==2)
check('pace: nothing outstanding',E.paced_quota(0,5,True)==0)

# ---------- 3. learning evidence ----------
def fresh():
 s={'skills':[{'id':'CS:x','course':'COP3502C','name':'x','status':'untested','evidence':[],'successes':0}],'attempts':[],'review_queue':[],'exercises':{'e1':{'fingerprint':'f1','course':'COP3502C','skill_ids':['CS:x'],'rubric_verified':True},'e2':{'fingerprint':'f2','course':'COP3502C','skill_ids':['CS:x'],'rubric_verified':True}}}
 return s
n=[0]
def grade(s,outcome,day,aids='closed_book',ex='e1',**extra):
 n[0]+=1;sid='sub-%04d'%n[0]
 r={'submission_id':sid,'outcome':outcome,'feedback':'f','verification_evidence':'v',**extra}
 if outcome=='incorrect':r.setdefault('specific_error','err')
 return C.assess(s,r,{'id':sid,'answer':'a','assessment_allowed':True,'exercise_id':ex,'aids':aids},day)
sk=lambda s:s['skills'][0]
due=lambda s:s['review_queue'][-1]['due']
d0=T-timedelta(days=20)
s=fresh();grade(s,'correct',d0);grade(s,'correct',d0+timedelta(days=1))
check('two spaced successes',sk(s)['successes']==2 and due(s)==(d0+timedelta(days=4)).isoformat(),(sk(s),due(s)))
grade(s,'correct',d0+timedelta(days=4),aids='hint')
check('hinted correct keeps earlier successes',sk(s)['successes']==2 and sk(s)['status']=='demonstrated',sk(s))
check('hinted correct is not spaced success (review next day)',due(s)==(d0+timedelta(days=5)).isoformat())
grade(s,'incorrect',d0+timedelta(days=6),partial_score=0.75)
check('partial slip removes one success, not all',sk(s)['successes']==1 and sk(s).get('last_error'),sk(s))
grade(s,'incorrect',d0+timedelta(days=7))
check('a real miss resets',sk(s)['successes']==0 and sk(s)['status']=='learning')
a=grade(s,'correct',d0+timedelta(days=7),ex='e2')
check('immediate retry after a miss: repaired, not spaced success',sk(s)['successes']==0 and not sk(s).get('last_error') and a.get('evidence_kind')=='repaired_same_day',sk(s))
a=grade(s,'correct',d0+timedelta(days=8))
check('next-day independent success counts',sk(s)['successes']==1 and sk(s)['status']=='demonstrated' and a['evidence_kind']=='independent')
before=json.dumps(sk(s));grade(s,'ambiguous',d0+timedelta(days=9))
check('ambiguous changes no mastery',{k:v for k,v in sk(s).items() if k not in ('evidence','last_attempt','needs_clarification')}=={k:v for k,v in json.loads(before).items() if k not in ('evidence','last_attempt','needs_clarification')})

# ---------- 4. notes ----------
c1=X.chips('Calc test 3 is Nov 12')
check('date report parsed',any(c['kind']=='date_report' and c['course']=='MAC2311C' and c['date'].endswith('-11-12') for c in c1),c1)
check('scope sentence is not a date',not X.date_report('quiz 9 covers chapter 4'))
a1=X.add('Discrete exam 2 moved to Nov 10');a2=X.add('Discrete exam 2 moved to Nov 10',source='iphone')
check('same note sent twice is one note',a1['id']==a2['id'])
check('unlinked note says it does nothing',X.effect({'chips':[{'kind':'note','course':None}]}).startswith('Not linked'))

# ---------- 5. planning on a fixture: nothing disappears ----------
ev={'COT3100C':[('Exam2- Requires Respondus LockDown Browser',6,True),('Quiz9',5,False)],'COP3502C':[('Assignment %d'%i,1,False) for i in range(1,21)]}
def fake_events(state,course,day):
 out=[{'name':n,'date':(day+timedelta(days=d)).isoformat(),'days':d,'exam':x,'certainty':'listed','overdue':False,'assignment_id':None} for n,d,x in ev.get(course,[])]
 out+=[{'name':e['name'],'date':e['date'],'days':(date.fromisoformat(e['date'])-day).days,'exam':True,'certainty':e.get('certainty'),'overdue':False,'assignment_id':None} for e in state.get('events',[]) if e.get('course')==course and e.get('reported')]
 return sorted(out,key=lambda x:x['days'])
E.course_events=fake_events
topics=[{'title':t,'query':t,'formats':['short answer']} for t in ('Number Theory Part I','Number Theory Part II','Number Theory Part III','Number Theory Part IV','Functions','Relations')]
E.obligation_topics=lambda course,e,a,day,is_test=False,notes=None:((topics if 'Exam' in e['name'] else topics[2:4]),'published scope: test fixture') if course=='COT3100C' else ([{'title':'Topic of '+e['name'],'query':'linked lists '+e['name'],'formats':[]}],'topic named in the assignment')
plan=E.make_plan('fixture-1',T)
check('no invented time budget',plan['daily_limit_minutes'] is None)
mand=[s for s in plan['slots'] if s.get('days',99)<=3]
check('published plan stays within the packet limit',len([s for s in plan['slots'] if not s['context_addition']])<=E.MAX_TASKS,len(plan['slots']))
exam=next(o for o in plan['obligations'] if o['name'].startswith('Exam2'))
check('every exam topic is accounted for',len(exam['topics'])==7 and all(t.get('plan') in ('today','shared','later','covered','deferred') for t in exam['topics']),[(t['title'],t.get('plan')) for t in exam['topics']])
check('exam topics are paced, with reasons',sum(t['plan']=='later' for t in exam['topics'])>=1 and all(t.get('reason') for t in exam['topics'] if t['plan'] in ('later','deferred')))
overflow=[o for o in plan['obligations'] if o['name'].startswith('Assignment')]
lost=[o['name'] for o in overflow if not o['topics'] or any(t.get('plan') not in ('today','shared','deferred') for t in o['topics'])]
check('20 assignments due tomorrow: each is planned or explicitly deferred',not lost,lost)
check('over-capacity work is listed with a reason',any('full' in d['reason'] for d in plan['deferred']),plan['deferred'][:3])
# limit set by the user is honored, and still never cuts work due within three days
prof=root/'School HQ Study/study-profile.json';prof.write_text(json.dumps({'daily_minutes':60}))
ev['COP3502C']=[('Assignment 1',1,False)]
plan2=E.make_plan('fixture-2',T)
check('a daily limit you set is honored',plan2['daily_limit_minutes']==60 and any('60-minute' in d['reason'] for d in plan2['deferred']),plan2['deferred'][:2])
check('the limit never cuts work due soon',any(s.get('days')==1 for s in plan2['slots']))
prof.unlink()

# ---------- 6. reported dates and undated assessments ----------
X.add('Calc test 3 is '+(T+timedelta(days=8)).strftime('%b %-d'))
plan3=E.make_plan('fixture-3',T)
t3=[o for o in plan3['obligations'] if o['course']=='MAC2311C' and 'Test 3' in o['name']]
check('a date you report puts the test in the plan, labelled',t3 and 'your note' in t3[0]['basis'] and t3[0]['certainty']=='reported',[(o['name'],o['basis']) for o in plan3['obligations']])
exam3=next(o for o in plan3['obligations'] if o['name'].startswith('Exam2'))
quiz=next(o for o in plan3['obligations'] if o['name']=='Quiz9')
shared={t['title'] for t in exam3['topics'] if t['plan']=='shared'}|{t['title'] for t in quiz['topics'] if t['plan']=='shared'}
check('quiz and exam share topics instead of duplicating them',shared and all(t.get('key') for o in (exam3,quiz) for t in o['topics'] if t['plan'] in ('today','shared')),[(t['title'],t['plan']) for t in quiz['topics']])
check('an undated known assessment stays visible',any('lab exam' in u['name'].lower() for u in plan3['undated']),plan3['undated'])

# ---------- 6b. continuation: finishing today's set pulls the next topics forward ----------
sl=[x for x in plan3['slots'] if not x['context_addition']]
s6=C.load(root)
for i,x in enumerate(sl):s6['attempts'].append({'submission_id':'done-%d'%i,'exercise_id':x['course']+':t:'+x['key']+':abc123','outcome':'correct','feedback':'ok','attempt_date':T.isoformat(),'independent':True})
C.persist(s6,root)
st6=json.loads((root/'School HQ App/Bridge/state.json').read_text());st6['brief']={'id':'b6','date':T.isoformat(),'tasks':[{'exercise_id':x['course']+':t:'+x['key']+':abc123'} for x in sl]}
(root/'School HQ App/Bridge/state.json').write_text(json.dumps(st6))
plan5=E.make_plan('fixture-5',T)
check('finished today is detected',plan5['pulled_ahead'])
check('a re-plan never repeats a task already done today',not ({x['key'] for x in sl}&{x['key'] for x in plan5['slots']}),[x['skill_name'] for x in plan5['slots']])
s6['attempts']=[a for a in s6['attempts'] if not a['submission_id'].startswith('done-')];C.persist(s6,root)

# ---------- 7. recovery: unknown is diagnosed, not labelled weak ----------
NS_results={'COP3330':[{'name':'E1','fraction':0.34}]}
PL.exam_results=lambda root:NS_results
plan4=E.make_plan('fixture-4',T)
rec=[s for s in plan4['slots'] if s.get('recovery')]
check('recovery starts with a diagnostic check on untested topics',rec and all(s['mode'] in ('diagnose','repair','retrieval','learn') for s in rec) and any(s['mode']=='diagnose' for s in rec) or all(s['facts'].get('skill_status') not in (None,'untested') for s in rec),[(s['skill_name'],s['mode'],s['facts'].get('skill_status')) for s in rec])
state=C.load(root)
check('strong recent work is detected',not PL.recently_strong(state,'COP3330',T))
fake={'attempts':[{'exercise_id':'q%d'%i,'attempt_date':(T-timedelta(days=i)).isoformat(),'independent':True,'outcome':'correct'} for i in range(4)],'exercises':{'q%d'%i:{'course':'COP3330'} for i in range(4)}}
check('three recent independent correct answers ease the old low exam',PL.recently_strong(fake,'COP3330',T))

# ---------- 8. retries are checked before they are shown ----------
class RejectRetry(FakeClient):
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'Now compare' in prompt and 'sumList' in prompt:
   m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt);Path(m[1]).write_text(json.dumps({'agrees':False,'reference_correct':False,'issues':['reference sums wrong field'],'leak':False,'summary':'wrong'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
st=json.loads((root/'School HQ App/Bridge/state.json').read_text())
task={'exercise_id':'COP3502C:fixture:abc','course':'CS1','course_id':'COP3502C','question':'Write byeList','prompt_blocks':[{'kind':'paragraph','text':'Write byeList'}],'answer_type':'code','skill_ids':['COP3502C:recursion']}
st['brief']={'id':'req-9','tasks':[task]};(root/'School HQ App/Bridge/state.json').write_text(json.dumps(st))
(root/'School HQ App/Bridge/Packets/req-9').mkdir(parents=True,exist_ok=True);(root/'School HQ App/Bridge/Packets/req-9/rubrics.json').write_text(json.dumps({task['exercise_id']:{'solution':'void byeList(node*h){if(!h)return;byeList(h->next);free(h);}','rubric':'recurse first'}}))
s=C.load(root)
if not any(x['id']=='COP3502C:recursion' for x in s['skills']):s['skills'].append({'id':'COP3502C:recursion','course':'COP3502C','name':'Recursion','status':'untested','evidence':[],'successes':0})
C.persist(s,root)
fb=G.submit({'brief_id':'req-9','exercise_id':task['exercise_id'],'answer':'void byeList(node*h){free(h);byeList(h->next);}','attempt_id':'zz11yy22xx33'},client_factory=lambda:RejectRetry)
check('a flawed retry is never offered',fb['retry'] is None and 'next plan' in (fb['latest']['next_step'] or ''),fb.get('retry'))
check('the miss itself is still recorded',any(a['submission_id']=='zz11yy22xx33' for a in C.load(root)['attempts']))

# ---------- 9. unreadable answers record nothing ----------
class Unreadable(FakeClient):
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'Grade a student' in prompt:
   m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt);Path(m[1]).write_text(json.dumps({'outcome':'unreadable','score':0,'feedback':'x','unreadable_reason':'Line 3 could be 1/(2x) or x/2.','rewrite_tip':'Type line 3 in the box.','clear_example':'1/(2x)\n= 0.5/x'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
n_before=len(C.load(root)['attempts'])
out=G.submit({'brief_id':'req-9','exercise_id':task['exercise_id'],'answer':'1/2x','attempt_id':'uu11vv22ww33'},client_factory=lambda:Unreadable)
ev_file=json.loads((root/'School HQ App/Bridge/Evidence/uu11vv22ww33.json').read_text())
check('unreadable: no grade, attempt kept, specific reason',out.get('unreadable') and len(C.load(root)['attempts'])==n_before and ev_file['status']=='unreadable' and 'Line 3' in out['unreadable']['reason'])

# ---------- 10. rapid-fire phone sessions ----------
msgs=[{'id':'m%d'%i,'text':t,'seq':i} for i,t in enumerate(["calc test 3 will include related rates","didn't understand implicit differentiation","also includes optimization and linear approximation"])]
simple=X.combine_simple(msgs,'MAC2311C')
check('fallback keeps every message',sorted(i for n in simple for i in n['from'])==[0,1,2],simple)
check('fallback ties "also includes" back to test 3',any('test 3' in n['text'].lower() and 'optimization' in n['text'] for n in simple),simple)
class Combine(FakeClient):
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'fired off these short messages' in prompt:
   m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
   Path(m[1]).write_text(json.dumps({'notes':[{'text':'Calc test 3 will include related rates, optimization and linear approximation.','course':'MAC2311C','from':[0,2],'assessment':'Test 3','topics':['related rates','optimization','linear approximation']},{'text':"I didn't understand implicit differentiation.",'course':'MAC2311C','from':[1]}]}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
for i,m in enumerate(msgs):X.receive({**m,'session_id':'sess-1','course':'MAC2311C','source':'iphone'})
check('messages wait while the session is open',not any(n.get('session_id')=='sess-1' for n in X.load()['notes']) and len(X.load()['sessions']['sess-1']['messages'])==3)
X.receive({**msgs[2],'session_id':'sess-1','course':'MAC2311C'})
check('a resent message is not duplicated',len(X.load()['sessions']['sess-1']['messages'])==3)
X.receive({'session_id':'sess-1','session_end':True,'text':''}) if False else X.locked(X._buffer)('sess-1',{'session_end':True,'text':''})
X.settle(client_factory=lambda:Combine)
got=[n for n in X.load()['notes'] if n.get('session_id')=='sess-1']
check('swipe-down combines the burst into self-contained notes',len(got)==2 and any('linear approximation' in n['text'] for n in got),[n['text'] for n in got])
scope=[c for n in got for c in n['chips'] if c['kind']=='scope_hint']
check('the exam scope keeps its topics',scope and scope[0].get('topics')==['related rates','optimization','linear approximation'],[n['chips'] for n in got])
check('the stuck topic is recognised',any(c['kind']=='struggling' for n in got for c in n['chips']))
check('a combined session never combines twice',X.locked(X._buffer)('sess-1',{'text':'late message','id':'zz'})['status']=='already combined')
check('a straggler after combining is kept as its own note',any(n['text']=='late message' for n in X.load()['notes']))
X.locked(X._buffer)('sess-3',{'session_end':True,'text':'','count':2});X.receive({'id':'c1','text':'quiz 9 covers modular arithmetic','session_id':'sess-3','course':'COT3100C'})
check('the done marker arriving first waits for the rest','sess-3' in X.load()['sessions'])
X.receive({'id':'c2','text':'also includes gcd','session_id':'sess-3','course':'COT3100C'})
check('then combines once all messages are in','sess-3' not in X.load()['sessions'] and any(n.get('session_id')=='sess-3' for n in X.load()['notes']))
for i,m in enumerate(msgs):X.receive({**m,'id':'b'+m['id'],'session_id':'sess-2','course':'MAC2311C'})
X.locked(X._buffer)('sess-2',{'session_end':True,'text':''})
class Broken(FakeClient):
 def turn(self,*a,**k):raise RuntimeError('network down')
X.settle(client_factory=lambda:Broken)
check('if the model is unavailable, nothing is lost',len([n for n in X.load()['notes'] if n.get('session_id')=='sess-2'])>=2)
check('the scope you sent is used for that test',E.reported_scope('MAC2311C',{'name':'Test 3'},X.active())[:3]==['related rates','optimization','linear approximation'],E.reported_scope('MAC2311C',{'name':'Test 3'},X.active()))
check('and not for a different test',E.reported_scope('MAC2311C',{'name':'Test 4'},X.active())==[])

# ---------- 11. companion ----------
import school_hq_companion as K
s=fresh();d1=T-timedelta(days=3)
grade(s,'incorrect',d1);before=dict(sk(s));grade(s,'correct',d1+timedelta(days=1))
check('remark: a topic you used to miss, now alone',"used to" not in '' and 'got you last time' in K.remark(s,'e1','correct',before,d1+timedelta(days=1)))
s=fresh();grade(s,'incorrect',T);grade(s,'correct',T,ex='e2')
check('remark: same-day fix promises a check tomorrow','tomorrow' in K.remark(s,'e2','correct',None,T))
s=fresh();grade(s,'correct',T,aids='hint')
check('remark: help is named honestly','help' in K.remark(s,'e1','correct',None,T))
check('remark: a miss is never shaming','not yet' in K.remark(fresh(),'e1','incorrect').lower())
task9={'exercise_id':'COP3502C:fixture:abc'}
class Leaky(FakeClient):
 n=0
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'sitting next to them' in prompt:
   Leaky.n+=1;m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
   reply='Just write `void byeList(node*h){if(!h)return;byeList(h->next);free(h);}`' if Leaky.n==1 else 'What has to happen to the rest of the list before you free `head`?'
   Path(m[1]).write_text(json.dumps({'reply':reply,'next_action':'Decide the order'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
h=K.help({'brief_id':'req-9','exercise_id':task9['exercise_id'],'kind':'hint','draft':''},client_factory=lambda:Leaky)
check('companion help never gives the answer away (rewritten once)',Leaky.n==2 and 'byeList(h->next)' not in h['reply'] and h['used_help'],h)
class AlwaysLeaky(FakeClient):
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'sitting next to them' in prompt:
   m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt);Path(m[1]).write_text(json.dumps({'reply':'void byeList(node*h){if(!h)return;byeList(h->next);free(h);}','next_action':'x'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
h=K.help({'brief_id':'req-9','exercise_id':task9['exercise_id'],'kind':'hint'},client_factory=lambda:AlwaysLeaky)
check('if it keeps leaking, a safe first step instead','slow it down' in h['reply'])
sm=K.summary(T)
check('summary is computed from real attempts',isinstance(sm['lines'],list) and sm['semester_over'] is False,sm)

# ---------- 12. habits, voice, break chat ----------
from datetime import datetime as DT,timezone as TZ
base=DT.now(TZ.utc)-timedelta(days=2)
ev=[]
for k in range(6):   # six sessions of ~10 minutes, an hour apart
 st0=base+timedelta(hours=k)
 ev+=[{'t':(st0+timedelta(minutes=m)).isoformat(),'e':'type','task':'x'} for m in range(0,11)]
 ev.append({'t':(st0+timedelta(minutes=10,seconds=30)).isoformat(),'e':'inactive'})
K.ACTIVITY.write_text('\n'.join(json.dumps(e) for e in ev))
hb=K.habits()
check('habits: focus span measured from real activity',hb['enough_data'] and 9<=hb['focus_minutes']<=11 and hb['break_at_minutes']==8,hb)
check('habits: time away measured',hb['return_minutes'] and 45<=hb['return_minutes']<=55,hb)
K.ACTIVITY.write_text('')
check('habits: not enough data means a sensible default',K.habits()['break_at_minutes']==12)
mem=K.memory();mem['said']=[{'text':t,'at':''} for t in ['lol yeah im tired','ngl this is mid','idk bro','fr']];K.save_memory(mem)
stl=K.style()
check('style: picks up lowercase, no periods and slang',stl['lowercase'] and not stl['periods'] and {'lol','ngl','bro'}<=set(stl['slang']),stl)
check('voice: answers in kind, code untouched',K.voice('Nice. Try `F(x)` Next.',stl)=='nice. try `F(x)` next',K.voice('Nice. Try `F(x)` Next.',stl))
class Friend(FakeClient):
 prompts=[]
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'short break that does not feel like one' in prompt:
   Friend.prompts.append(prompt);m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
   Path(m[1]).write_text(json.dumps({'reply':'Okay real talk. The best food is whatever you eat at 3am.','wrap':False,'remember':['plays guitar']}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
r=K.chat({'history':[],'task':{'title':'Trace insertion sort'}},client_factory=lambda:Friend)
check('break chat opens casually, in their voice',r['reply']=='okay real talk. the best food is whatever you eat at 3am',r)
check('break chat is honest about being an AI and watches for real trouble','truthful about what you are' in Friend.prompts[0].lower() and '988' in Friend.prompts[0])
check('break chat steers away from coursework','EXCEPT their coursework' in Friend.prompts[0])
r=K.chat({'history':[{'who':'genesis','text':'best thing you ate?'},{'who':'you','text':'tacos lol, also i play guitar'}]},client_factory=lambda:Friend)
facts=K.memory()['facts']
check('it remembers what you tell it',any(f['text']=='plays guitar' for f in facts) and any(x['text'].startswith('tacos') for x in K.memory()['said']))
K.forget(facts[0]['id'])
check('one memory can be deleted',not any(f['text']=='plays guitar' for f in K.memory()['facts']))
K.forget('all')
check('everything can be deleted',K.memory()=={'facts':[],'said':[],'chats':0})

# ---------- 13. the character from the personality spec ----------
import school_hq_persona as P
src=Path(P.__file__).read_text()
check('persona: no real contact names or private messages in the app',not re.search(r'\b(Gen|Mara|Olivia|Jeremy|Eliany|Carlos)\b',src))
check('persona: honest about being an AI, no invented promises','AI' in P.CHARACTER and "can't call" in P.CHARACTER and 'forever' in P.CHARACTER)
check('persona: not a question every turn',"question at the end of every message" in P.CHARACTER)
class Bounded(FakeClient):
 prompts=[]
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'short break that does not feel like one' in prompt:
   Bounded.prompts.append(prompt);m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
   Path(m[1]).write_text(json.dumps({'reply':'Okay. We can leave the details alone.','wrap':False,'remember':[],'boundary':'the breakup'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
_r=K.chat({'history':[{'who':'genesis','text':'x'},{'who':'you','text':'we broke up, i dont want to get into why'}]},client_factory=lambda:Bounded)
check('the orb always gets a face to make (an unknown mood falls back to neutral)',_r.get('mood')=='neutral',_r)
check('a limit they set is remembered as a limit',any(f.get('kind')=='boundary' and 'breakup' in f['text'] for f in K.memory()['facts']))
K.chat({'history':[]},client_factory=lambda:Bounded)
check('and every later chat is told never to raise it',"doesn't want to talk about the breakup" in Bounded.prompts[-1].split('Things they do not want to talk about')[1][:200])
check('the invented examples shape the voice','impressive hourly rate for a bracket' in Bounded.prompts[-1])
class Moody(FakeClient):
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'short break that does not feel like one' in prompt:
   m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
   Path(m[1]).write_text(json.dumps({'reply':'oof. that sounds like a rough week','wrap':False,'remember':[],'mood':'empathetic'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
_r=K.chat({'history':[{'who':'genesis','text':'x'},{'who':'you','text':'this week has been awful'}]},client_factory=lambda:Moody)
check('the face follows what was said (empathetic to a rough week)',_r['mood']=='empathetic' and 'happy | playful | sad | empathetic' in Bounded.prompts[-1],_r)
class CheckIn(FakeClient):
 seen=[]
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'EXAMPLES OF YOUR VOICE' in prompt:
   CheckIn.seen.append(prompt);m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
   Path(m[1]).write_text(json.dumps({'reply':'ngl just checking on you. it has been a long week','wrap':False,'remember':[],'mood':'curious'}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
_r=K.chat({'history':[],'moment':'check_in'},client_factory=lambda:CheckIn)
check('a check-in out of nowhere is framed as a friend checking up, not a study break','checking up on them' in CheckIn.seen[-1] and 'short break' not in CheckIn.seen[-1] and _r['mood']=='curious',_r)
check('they decide how long a chat goes','Never end it yourself' in CheckIn.seen[-1])
K.forget('all')

# ---------- 14. Genesis starts it, the student guides it ----------
class Asker(FakeClient):
 seen=[]
 def turn(self,prompt,model,effort,timeout=0,check=None):
  if 'short break that does not feel like one' in prompt or 'failed validation' in prompt:
   Asker.seen.append(prompt);m=re.search(r'(/\S+\.json)',prompt)
   reply='what did you want to be as a kid?' if len(Asker.seen)==1 else "ok you've been locked in for a while. i'm just gonna hang out here for a sec"
   Path(m[1]).write_text(json.dumps({'reply':reply,'wrap':False,'remember':[]}));return
  return FakeClient.turn(self,prompt,model,effort,timeout,check)
r=K.chat({'history':[]},client_factory=lambda:Asker)
check('the opener is never a question (rewritten if it is)','?' not in r['reply'] and len(Asker.seen)==2 and 'must not be a question' in Asker.seen[1],r)
check('the prompt tells it to follow their lead','follow THEIR lead' in Asker.seen[0] and 'Never change the subject' in Asker.seen[0])
Asker.seen=[]
r=K.chat({'history':[{'who':'genesis','text':'x'},{'who':'you','text':'i wanted to be a pilot'}]},client_factory=lambda:Asker)
check('later replies may ask, when it follows from what they said',r['reply'].endswith('?') and len(Asker.seen)==1)
K.forget('all')

print('passed',passed[0],'failed',len(fails))
for f in fails:print('FAIL',f)
sys.exit(1 if fails else 0)

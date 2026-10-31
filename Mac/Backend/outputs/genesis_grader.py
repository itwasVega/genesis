#!/usr/bin/env python3
"""Immediate grading for plan tasks.

Code answers are compiled and run against the task's private tests first (network
and outside writes denied). A model then grades against the private rubric and,
after a miss, writes a NEW problem on the same skill with a different structure.
Results feed the same mastery tracker as everything else (coaching.assess).
"""
import argparse,fcntl,json,re,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
BRIDGE=ROOT/'Genesis App/Bridge'
STUDY=ROOT/'Genesis Study'
FEEDBACK=BRIDGE/'Feedback'
RETRIES=STUDY/'retries.json'

def now():return datetime.now(timezone.utc).isoformat()
def day():return datetime.now(__import__('genesis_connections').zone()).date()
def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return {} if default is None else default
def atomic(p,v):
 from genesis_coaching import atomic as write;write(p,v)
def safe(name):return re.sub(r'[^A-Za-z0-9_.-]','_',name)[:150]

def find_task(brief_id,exercise_id):
 state=read(BRIDGE/'state.json',{});brief=state.get('brief') or {}
 retries=read(RETRIES,{})
 if exercise_id in retries:
  r=retries[exercise_id];return r['public'],r['private'],r['course']
 if brief.get('id')!=brief_id:raise ValueError('This plan was replaced by a newer one. Your answer is kept; reopen the task.')
 task=next((t for t in brief.get('tasks',[]) if t.get('exercise_id')==exercise_id),None)
 if not task:raise ValueError('Task not found in the current plan')
 rubrics=read(BRIDGE/'Packets'/brief_id/'rubrics.json',{}) or read(STUDY/'exercise-rubrics.json',{})
 private=rubrics.get(exercise_id) or read(STUDY/'exercise-rubrics.json',{}).get(exercise_id)
 if not private:raise ValueError('No private rubric for this task; it cannot be graded automatically')
 return task,private,task.get('course_id') or task.get('course')

def public_text(task):
 out=[]
 for b in task.get('prompt_blocks') or []:
  out.append(('```'+b.get('language','')+'\n'+b['text']+'\n```') if b.get('kind')=='code' else ('$$'+b['text']+'$$' if b.get('kind')=='displayMath' else b.get('text','')))
 return '\n\n'.join(out) or task.get('question','')

def grade_prompt(task,private,answer,aids,tests,pages=None,transcript=None):
 t='''Grade a student's answer to a '''+str(task.get('course',''))+''' problem. Answer type: '''+str(task.get('answer_type','mixed'))+'''.
PROBLEM:
'''+public_text(task)[:8000]+'''

REFERENCE SOLUTION (private):
<<<
'''+str(private.get('solution',''))[:6000]+'''
>>>
RUBRIC (private):
<<<
'''+str(private.get('rubric',''))[:3000]+'''
>>>'''
 if private.get('unverified'):
  t+='\nNOTE: this reference was written quickly after an earlier miss and has not been independently checked. Solve the problem yourself first; if the reference is wrong, grade against the correct answer and say so in feedback.'
 if tests and tests.get('status')!='unavailable':t+='\nRESULTS FROM ACTUALLY COMPILING AND RUNNING THE STUDENT\'S CODE:\n'+json.dumps(tests)[:3000]
 t+='''
STUDENT ANSWER (conditions: '''+aids+'''):
<<<
'''+(answer[:15000] or '(nothing typed — the answer is on the attached pages)')+'''
>>>'''
 if pages:
  t+='''
ATTACHED PAGES: '''+str(pages)+''' image(s) of the student's handwritten or digital-paper work are attached. Read them as the answer (together with anything typed).'''
  if transcript:t+='''
Machine transcription of those pages (OCR; it can garble symbols, so trust the image over it):
<<<
'''+transcript[:6000]+'''
>>>'''
 t+='''
HOW TO READ THE ANSWER
- Students type math in plain text however is natural: x^2, x**2, x², sqrt(x), √x, 3/(x+1), 1/2 x, lim x->0, d/dx, integral of ... dx, pi, e^x, ln x, <= >=, ->. Interpret any reasonable notation the way a teacher reading the paper would. Never penalize notation or formatting itself.
- Only if the answer, or a step the grade depends on, genuinely cannot be read or has two readings that would change the grade (e.g. 1/2x could be 1/(2x) or x/2 and it matters, handwriting that is illegible, a blurry or cut-off photo), return outcome "unreadable". Never guess a grade you are not confident in.
Return JSON:
{"outcome": "correct" | "partially_correct" | "incorrect" | "unreadable",
 "score": number 0-1,
 "feedback": 2-4 short sentences to the student: what is right, the exact error, and the fix. Put identifiers, values and formulas in backticks, plus at most one key concept term on first mention; nothing else. No hedging.,
 "specific_error": short phrase or null,
 "misconception": the underlying misunderstanding in one sentence, or null,
 "next_step": one imperative sentence,
 "unreadable_reason": when outcome is "unreadable", ONE sentence naming exactly what could not be read (e.g. "Line 3 could be 1/(2x) or x/2."), else null,
 "rewrite_tip": when outcome is "unreadable", one short tip. If only one line or symbol is unclear, ask for just that part to be typed in the box (e.g. "Type line 3 in the box, like: 1/(2x)"); the rest of the work stays attached and is read again. Otherwise a tip for writing it clearly. Else null,
 "clear_example": when outcome is "unreadable", 2-4 short lines showing what a clearly written answer to THIS KIND of problem looks like, worked on a DIFFERENT small made-up instance (never this problem's numbers or answer), else null,
 "retry": null when correct; otherwise {"title": verb-first title, "question": full statement, "prompt_blocks": [{"kind":"paragraph"|"code"|"displayMath","text":...,"language":...}], "answer_type": same kinds as above, "solution": complete answer, "rubric": what earns credit} — a NEW problem on the same skill with a DIFFERENT structure (not just new numbers) that targets the misconception, in the same course format.}
Equivalent forms are correct. Judge the reasoning the answer type requires (a trace needs the states; a derivation needs the steps). Failing tests outweigh claims in prose.'''
 return t

# What a clear answer looks like, by answer type (shown when an answer can't be read).
CLEARER={
 'derivation':["f'(x) = 3x^2 - 4x","= x(3x - 4)","lim x->0 sin(3x)/x = 3","(x + 1)/(x - 1)   not   x + 1/x - 1"],
 'numeric':["7","-3/4","2.5"],
 'short_answer':["gcd = 7, s = 3, t = -10","O(n log n)"],
 'proof':["1. Let n = 2k for some integer k   (definition of even)","2. Then n^2 = 4k^2 = 2(2k^2)   (algebra)","3. So n^2 is even   (definition of even)"],
 'memory_trace':["line 4: x = 5, y = 2","line 6: p -> node A (val 3)","output: 5 3"],
 'code_trace':["i=0: arr = [5, 2, 9]","i=1: arr = [2, 5, 9], shifts = 1","output: 1"],
 'table':["n | T(n)","1 | 1","2 | 3"],
 'code':["int pop(Stack *s) {","    Node *top = s->head;","    ...","}"],
 'multiple_choice':["B"],
 'explanation':["The loop runs n times because i doubles each pass, so ..."],
 'mixed':["Part a: gcd = 7","Part b: 7 = 3·91 - 10·27"],
}
CLEARER.update({
 ('discrete','derivation'):["42 = 1·30 + 12","30 = 2·12 + 6","12 = 2·6 + 0  →  gcd = 6, 3 divisions","6 = 42 - 1·30 ... so 6 = 42·(-2) + 30·3"],
 ('discrete','proof'):["1. Suppose n is odd, so n = 2k + 1   (definition)","2. n^2 = 4k^2 + 4k + 1 = 2(2k^2 + 2k) + 1   (algebra)","3. So n^2 is odd   (definition)"],
 ('discrete','short_answer'):["gcd = 6, x = -2, y = 3","{1, 2, 3}"],
 ('math','derivation'):["f'(x) = 3x^2 - 4x","lim x->0 sin(3x)/x = 3","(x + 1)/(x - 1)   not   x + 1/x - 1"],
 ('cs','derivation'):["T(n) = 2T(n/2) + n","= 4T(n/4) + 2n","= n log2(n) + n"],
})

def leaks(lines,private):
 # An example must not contain the private answer's distinctive numbers or text.
 sol=str(private.get('solution',''))
 nums={n for n in re.findall(r'-?\d{2,}',sol)}
 text=' '.join(lines)
 return any(n in re.findall(r'-?\d{2,}',text) for n in nums) or (len(sol)>=16 and sol.lower()[:60] in text.lower())

PAGE_TIPS=["Write one step per line with space between lines, in dark ink.","Export the page as an image or PDF, or take the photo straight on in good light with the whole page in frame."]

def retry_checked(r,course,exercise_id,client_factory=None):
 """A retry is only offered after a second model solves it independently and agrees
 with its reference answer, the same check every planned task gets. If the check
 fails or cannot run, no retry is offered (nothing unverified reaches the student)."""
 try:
  from genesis_engine import verify
  v={'prompt_blocks':r['prompt_blocks'],'answer_type':r.get('answer_type') or 'mixed','private_solution':{'solution':r['solution'],'rubric':r['rubric']}}
  ok,_,_=verify(v,{'course':course,'key':safe(exercise_id)[-40:]+'-retry'},None,client_factory)
  return ok
 except Exception:return False

def validate_grade(v):
 if not isinstance(v,dict) or v.get('outcome') not in ('correct','partially_correct','incorrect','unreadable'):raise ValueError('outcome required')
 if not isinstance(v.get('feedback'),str) or not v['feedback'].strip():raise ValueError('feedback required')
 try:v['score']=max(0.0,min(1.0,float(v.get('score',1 if v['outcome']=='correct' else 0))))
 except (TypeError,ValueError):v['score']=1.0 if v['outcome']=='correct' else 0.0
 r=v.get('retry')
 if v['outcome'] in ('incorrect','partially_correct'):
  if not isinstance(r,dict) or not all(isinstance(r.get(k),str) and r[k].strip() for k in ('title','question','solution','rubric')):raise ValueError('retry problem required after a miss')
  blocks=r.get('prompt_blocks') or [{'kind':'paragraph','text':r['question']}]
  if not isinstance(blocks,list) or any(not isinstance(b,dict) or b.get('kind') not in ('paragraph','code','displayMath') or not isinstance(b.get('text'),str) for b in blocks):raise ValueError('retry prompt_blocks invalid')
  r['prompt_blocks']=blocks
 else:v['retry']=None
 return v

def submit(payload,client_factory=None):
 import genesis_ai as ai,genesis_coaching as coaching
 brief_id=payload.get('brief_id','');exercise_id=payload.get('exercise_id','');answer=payload.get('answer','')
 attempt_id=payload.get('attempt_id') or str(uuid.uuid4())
 pages=[str(x) for x in (payload.get('attachments') or []) if isinstance(x,str)][:8]
 uploads=(BRIDGE/'Evidence'/'uploads').resolve()
 for x in pages:
  q=Path(x).resolve()
  if uploads not in q.parents or not q.is_file() or q.suffix.lower()!='.png':raise ValueError('An attached page is missing. Remove it and attach it again.')
 if not isinstance(answer,str) or (not answer.strip() and not pages):raise ValueError('Write an answer or attach your page first')
 if len(answer)>20000:raise ValueError('Answer too long (20,000 characters max)')
 if not re.fullmatch(r'[A-Za-z0-9-]{8,64}',attempt_id):raise ValueError('Invalid attempt id')
 task,private,course=find_task(brief_id,exercise_id)
 aids='hint' if payload.get('used_help') else 'closed_book'
 evidence={'id':attempt_id,'exercise_id':exercise_id,'brief_id':brief_id,'answer':answer,'aids':aids,'assessment_allowed':True,'status':'grading','submitted_at':now(),'task_id':exercise_id}
 if pages:
  import hashlib
  evidence.update(attachments=pages,attachment=pages[0],attachment_sha256=hashlib.sha256(Path(pages[0]).read_bytes()).hexdigest())
 atomic(BRIDGE/'Evidence'/(attempt_id+'.json'),evidence)
 tests=None
 if task.get('answer_type')=='code' and private.get('harness') and private.get('tests'):
  from genesis_engine import test_code,LANG
  tests=test_code(private.get('language') or task.get('language') or LANG.get(course),answer,private['harness'],private['tests'])
 transcript=None
 if pages:
  try:
   from genesis_catalog import ocr_pages
   got=ocr_pages(pages);transcript='\n\n'.join('[page %d]\n%s'%(i+1,'\n'.join(got.get(p,['']))) for i,p in enumerate(pages)).strip() or None
  except Exception:transcript=None
 result=ai.run_json('grade',grade_prompt(task,private,answer,'closed notes' if aids=='closed_book' else 'used a hint or the worked solution',tests,len(pages),transcript),validate_grade,name='grade-'+safe(exercise_id)[:40],timeout=420,client_factory=client_factory,images=pages or None)
 if result['outcome']=='unreadable':
  # Not a grade. Record nothing, keep the evidence marked unreadable, and show how to fix it.
  evidence.update(status='unreadable');atomic(BRIDGE/'Evidence'/(attempt_id+'.json'),evidence)
  kind=task.get('answer_type') or 'short_answer'
  tips=[x for x in [result.get('rewrite_tip')] if x]+(PAGE_TIPS if pages else [])
  example=result.get('clear_example')
  if isinstance(example,str):example=[x for x in example.splitlines() if x.strip()]
  if not (isinstance(example,list) and example and all(isinstance(x,str) for x in example)) or leaks(example,private):
   example=CLEARER.get((__import__('genesis_connections').subject(course),kind)) or CLEARER.get(kind,CLEARER['short_answer'])
  return {'unreadable':{'reason':result.get('unreadable_reason') or result['feedback'],'tips':tips[:4],'examples':[x[:120] for x in example[:5]]}}
 retry_public=None;remark=None
 with (STUDY/'.coaching.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  state=coaching.load(ROOT)
  skill_ids=task.get('skill_ids') or []
  if exercise_id not in state['exercises']:
   state['exercises'][exercise_id]={'fingerprint':coaching.hashlib.sha256(json.dumps({'q':task.get('question','')},sort_keys=True).encode()).hexdigest(),'course':course,'skill_ids':skill_ids,'rubric_verified':True}
  if result['outcome']!='unreadable' and not any(a['submission_id']==attempt_id for a in state['attempts']):
   outcome='correct' if result['outcome']=='correct' else 'incorrect'
   review={'submission_id':attempt_id,'outcome':outcome,'feedback':result['feedback'],'verification_evidence':'Model rubric grading ('+ai.route('grade')[0]+')'+(' with test run: '+tests['status'] if tests and tests['status']!='unavailable' else ''),
           'transfer_variant':bool(read(RETRIES,{}).get(exercise_id))}
   if outcome=='incorrect':review['specific_error']=result.get('specific_error') or result.get('misconception') or 'Incorrect answer'
   # Mostly right with one slip (0.6 <= score < 1): a retry tomorrow, but it does not wipe
   # out earlier independent successes the way a real misunderstanding does.
   if result['outcome']=='partially_correct':review['partial_score']=result['score']
   before=next((dict(x) for x in state['skills'] if x['id'] in skill_ids),None)
   coaching.assess(state,review,{**evidence,'aids':aids},day())
   try:
    import genesis_companion as companion
    remark=companion.remark(state,exercise_id,result['outcome'],before)
   except Exception:remark=None
  if result.get('retry') and not retry_checked(result['retry'],course,exercise_id,client_factory):
   result['retry']=None;result['next_step']=(result.get('next_step') or '')+' A checked retry problem comes in your next plan.'
  if result.get('retry'):
   r=result['retry'];n=1+sum(1 for k in read(RETRIES,{}) if k.startswith(exercise_id.split(':retry')[0]+':retry'))
   rid=exercise_id.split(':retry')[0]+':retry'+str(n)
   retry_public={'id':rid,'number':0,'exercise_id':rid,'title':r['title'][:110],'question':r['question'],'prompt_blocks':r['prompt_blocks'],'answer_type':r.get('answer_type') or task.get('answer_type'),'course':task.get('course'),'course_id':course,'skill_ids':skill_ids,'language':task.get('language'),'kind':'learning','parent':exercise_id}
   retries=read(RETRIES,{});retries[rid]={'public':retry_public,'private':{'solution':r['solution'],'rubric':r['rubric'],'verification':{'method':'independent_calculation','evidence':'Written by the grader after a miss; solved independently by a second model before it was shown.'}},'course':course,'created_at':now()}
   atomic(RETRIES,retries)
   state['exercises'][rid]={'fingerprint':coaching.hashlib.sha256(r['question'].encode()).hexdigest(),'course':course,'skill_ids':skill_ids,'rubric_verified':True}
  coaching.persist(state,ROOT)
 usage=read(STUDY/'catalog-usage.json',{})
 for key,row in usage.items():
  if row.get('exercise_id')==exercise_id:row['last_outcome']='correct' if result['outcome']=='correct' else 'incorrect'
 atomic(STUDY/'catalog-usage.json',usage)
 record={'attempt_id':attempt_id,'at':now(),'outcome':result['outcome'],'score':result['score'],'feedback':result['feedback'],'specific_error':result.get('specific_error'),'misconception':result.get('misconception'),'next_step':result.get('next_step'),'aids':aids,'tests':tests}
 path=FEEDBACK/(safe(exercise_id)+'.json');fb=read(path,{'exercise_id':exercise_id,'attempts':[]})
 fb['attempts'].append(record);fb['latest']=record;fb['remark']=remark;fb['retry']=retry_public;fb['worked_solution']=str(private.get('solution',''))[:12000]
 atomic(path,fb)
 evidence.update(status='reviewed',outcome=result['outcome']);atomic(BRIDGE/'Evidence'/(attempt_id+'.json'),evidence)
 try:
  from genesis_engine import write_overview;write_overview()
 except Exception:pass
 return fb

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['submit']);a=p.parse_args()
 try:print(json.dumps(submit(json.load(sys.stdin))))
 except ValueError as exc:print(json.dumps({'error':str(exc)}));sys.exit(0)
if __name__=='__main__':main()

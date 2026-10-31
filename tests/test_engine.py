"""End-to-end engine test with a fake Codex client (no network, no models)."""
import json,os,re,shutil,sys,tempfile,hashlib,importlib
from pathlib import Path
from datetime import datetime,timezone,date

HERE=Path(__file__).resolve().parent
SRC=HERE.parent/'Mac/Backend/outputs'
STAGED=HERE/'fixtures'

def sha(b):return hashlib.sha256(b).hexdigest()

def setup():
 tmp=Path(tempfile.mkdtemp());root=tmp/'outputs';root.mkdir()
 for f in SRC.glob('*.py'):shutil.copy(f,root/f.name)
 for f in SRC.glob('*.json'):shutil.copy(f,root/f.name)
 (root/'School HQ App/Bridge').mkdir(parents=True);(root/'School HQ Study').mkdir(parents=True)
 (root/'School HQ Study/connections.json').write_text(json.dumps({'courses':[{'id':i,'canvas_id':c,'label':l} for i,c,l in [('COP3330','1000004','Java'),('COP3502C','1000001','CS1'),('COT3100C','1000002','Discrete'),('MAC2311C','1000003','Calculus')]]}))
 shutil.copy(STAGED/'School HQ Study/coaching-state.json',root/'School HQ Study/coaching-state.json')
 shutil.copy(HERE.parent/'Mac/Source/lesson-bank.json',root/'School HQ Study/lesson-bank.json')
 (root/'School HQ Study/assessments.json').write_text(json.dumps({'schema':1,'assessments':[{'id':'COP3502C:lab-exam','course':'COP3502C','name':'Week 10 lab exam','date':None,'certainty':'unknown','status':'scheduled','sources':[],'objectives':[{'id':'dma','title':'Dynamic memory allocation','formats':['write code']},{'id':'ll','title':'Linked lists','formats':['write code']},{'id':'rec','title':'Recursion','formats':['trace']},{'id':'stk','title':'Stacks and queues','formats':['write code']}]}]}))
 mat=root/'School HQ App/Bridge/Runs/r1/material';mat.mkdir(parents=True)
 docs=[('COP3502C','CS1 Midterm Sample.pdf',['B. Recursion question 2: Write a recursive function byeList that frees every node of a linked list. void byeList(node* head)','Q3 Trace the following pointer code and give the output of each printf.']),
       ('COP3502C','CS1 Midterm Sample Answer Key.pdf',['void byeList(node* head){ if(head==NULL) return; byeList(head->next); free(head); }','Output: 5 7']),
       ('COP3502C','LinkedLists.pdf',['Linked lists: each node stores data and a pointer next. Freeing a list recursively: free the rest first then the node. linked list traversal deletion pointer ownership recursion '*3]),
       ('COP3330','Sample Exam #2 Questions.pdf',['Problem 1. Write a class Rectangle with private fields width and height, a constructor, and a method area(). class design constructor','Problem 2. Given class Animal and class Dog extends Animal trace the output of the calls (polymorphism inheritance).'])]
 assets=[]
 for course,title,pages in docs:
  p=mat/title;data=b'%PDF-1.4 fixture '+title.encode();p.write_bytes(data)
  (root/'School HQ Study/Catalog/text').mkdir(parents=True,exist_ok=True)
  (root/'School HQ Study/Catalog/text'/(sha(data)+'.json')).write_text(json.dumps({'sha256':sha(data),'pages':pages}))
  assets.append({'id':course+':'+str(p),'path':str(p),'title':title,'kind':'Course material','course':course,'sha256':sha(data),'source_url':'https://webcourses.ucf.edu/courses/1/files/1','verification_state':'verified_bytes_not_learning_coverage'})
 (root/'School HQ App/Bridge/library.json').write_text(json.dumps({'courses':[{'id':c} for c in ('COP3330','COP3502C','MAC2311C','COT3100C','CIS3360')],'assets':assets}))
 (root/'School HQ App/Bridge/state.json').write_text(json.dumps({'schema':1,'request':{'id':'req-1','status':'processing','manual':True,'requested_at':datetime.now(timezone.utc).isoformat(),'policy_id':'local-first-v3'},'sources':{},'events':[],'brief':None}))
 return root

class FakeClient:
 calls=[]
 def __init__(self):pass
 def resume(self,instructions=None,model=None):self.model=model
 def close(self):pass
 def turn(self,prompt,model,effort,timeout=0,check=None):
  FakeClient.calls.append((model,effort,prompt[:60]))
  m=re.search(r'(?:nothing else|to): (/\S+\.json)',prompt)
  out=Path(m[1]);v=None
  if 'Catalog every individual problem' in prompt:
   pages=re.findall(r'=== PAGE (\d+) ===\n(.*?)(?=\n\n=== PAGE|\n\nANSWER KEY|\Z)',prompt,re.S)
   probs=[]
   for n,text in pages:
    probs.append({'label':text.split(':')[0][:40] if ':' in text[:60] else text[:20],'pages':[int(n)],'anchor':text[:40],'prompt_text':text[:400],'subparts':[],'answer_type':'code' if 'Write' in text else 'memory_trace','skills':['recursion','linked list deletion','class design','constructor','polymorphism tracing'],'structure':'write function' if 'Write' in text else 'trace output','difficulty':3,'has_official_solution':'ANSWER KEY' in prompt,'solution_pages':[int(n)] if 'ANSWER KEY' in prompt else [],'needs_figure':False})
   v={'problems':probs,'format_profile':{'question_types':'write functions, trace code'}}
  elif 'Write ONE study task' in prompt:
   label=re.search(r'Set problem_label to "([^"]+)"',prompt)
   v={'title':'Write `byeList` recursively','kind':'learning','why_now':'CS1 midterm was 10/100 on recursion; this closes the first gap.',
      'steps':['**Read** `LinkedLists.pdf` `p. 1`.','**Write** the function on paper.','**Check** the base case.'],
      'question':'Write a recursive C function byeList that frees every node of a singly linked list.','prompt_blocks':[{'kind':'paragraph','text':'Write `byeList` so that it frees every node.'},{'kind':'code','text':'void byeList(node* head);','language':'c'}],
      'teaching_blocks':[{'kind':'paragraph','text':'Free the rest of the list before the current node.'}],'example_blocks':[{'kind':'paragraph','text':'Example: counting nodes recursively.'}],'hint_blocks':[{'kind':'paragraph','text':'What must happen before free(head)?'}],
      'aids':'Closed notes, on paper','done_when':'A compiling function that frees all nodes','answer_type':'code','estimated_minutes':20,'estimate_basis':'One function plus trace',
      'origin':'exact_source' if label else 'original_format_matched','format_match':'Matches sample midterm style','problem_label':label[1] if label else None,'language':'c',
      'private_solution':{'solution':'void byeList(node* head){ if(head==NULL) return; byeList(head->next); free(head); }','rubric':'Base case NULL; recurse before free.','verification':{'method':'official_solution','evidence':'Matches answer key'}}}
  elif 'Solve this' in prompt:v={'final_answer':'recurse then free','worked_solution':'...','well_posed':True,'issues':[]}
  elif 'Now compare' in prompt:v={'agrees':True,'reference_correct':True,'issues':[],'leak':False,'summary':'Reference correct.'}
  elif 'Update a student' in prompt:v={'updates':[]}
  elif 'Grade a student' in prompt:
   v={'outcome':'incorrect','score':0.3,'feedback':'You free `head` before recursing, so `head->next` is read after free.','specific_error':'use after free','misconception':'Order of free vs recursion','next_step':'Recurse first, then free.',
      'retry':{'title':'Write `sumList` recursively','question':'Write int sumList(node* h) returning the sum of all values.','prompt_blocks':[{'kind':'paragraph','text':'Write `sumList`.'}],'answer_type':'code','solution':'int sumList(node*h){return h?h->v+sumList(h->next):0;}','rubric':'Base case and recursion.'}}
  out.write_text(json.dumps(v))

def main():
 root=setup();sys.path.insert(0,str(root));os.chdir(root)
 for m in list(sys.modules):
  if m.startswith('school_hq'):del sys.modules[m]
 import school_hq_engine as engine,school_hq_ai as ai,school_hq_coaching as c,school_hq_context as ctx
 ai.WORK=root.parent/'work/engine'
 ctx.add('I missed Monday CS1 class and recursion makes no sense')
 published={}
 def fake_bridge(*args):
  if args[0]=='publish':
   packet=json.loads(Path(args[2]).read_text())
   state=c.load(root);tasks,rubrics=c.validate_packet(packet,root,state,count_pages=lambda p,r:10)
   import school_hq_source_use as su,school_hq_brief_context as bc
   req=json.loads((root/'School HQ App/Bridge/state.json').read_text())['request']
   (root/'School HQ App/Bridge/Runs/req-1').mkdir(parents=True,exist_ok=True)
   json.dump({'request_id':'req-1','source_use_contract':su.candidates(root,json.loads((root/'School HQ App/Bridge/preparation.json').read_text()))},open(root/'School HQ App/Bridge/Runs/req-1/source-manifest.json','w'))
   notes=su.validate(packet,root,'req-1')+bc.validate(packet,root,req)
   published.update(tasks=tasks,rubrics=rubrics,notes=notes,packet=packet)
   return {'status':'published','tasks':len(tasks)}
  return {}
 engine.bridge=fake_bridge
 from datetime import date as _d,timedelta as _t
 T=engine.today()
 def fake_events(state,course,day):
  ev={'COP3502C':[('Lab Exam',0,True),('Lab 10 Attendance - Lab Exam',1,True)],'COT3100C':[('Quiz8',1,False)],'MAC2311C':[("4.4 L'Hopital's Rule (fix this for early 6pm exit)",4,False),('Reflection and Responsibility 10',2,False)],'COP3330':[('P7',4,False)]}.get(course,[])
  return [{'name':n,'date':(T+_t(days=d)).isoformat(),'days':d,'exam':x,'certainty':'listed','overdue':False,'assignment_id':None} for n,d,x in ev]
 engine.course_events=fake_events
 prog=[]
 result=engine.run('req-1',progress=lambda *a:prog.append(a),client_factory=lambda:FakeClient)
 print('RESULT',result)
 print('progress',[p[0] for p in prog])
 tasks=published['tasks']
 print('tasks',len(tasks),[ (t['course_id'],t['mode'],t.get('origin'),t.get('problem_label')) for t in tasks])
 t=tasks[0];print('keys',sorted(t))
 assert all('private_solution' not in t for t in tasks)
 assert any(s.get('pages') for t in tasks for s in t['sources'])
 plan=json.loads((root/'School HQ App/Bridge/Runs/req-1/plan.json').read_text())
 print('slots',[(s['course'],s['mode'],s['skill_name'][:30],(s.get('problem') or {}).get('item',{}).get('label')) for s in plan['slots']])
 print('obligations',[(o['name'][:20],o['basis'][:30],len(o['slots'])) for o in plan['obligations']])
 cov=json.loads((root/'School HQ App/Bridge/coverage.json').read_text());print('coverage',[(o['name'][:15],[(t['title'][:18],bool(t['exercise_id'])) for t in o['topics']]) for o in cov['obligations']])
 print('new skills',[x['id'] for x in plan['new_skills']])
 print('catalog files',[p.name for p in (root/'School HQ Study/Catalog').glob('*.json')])
 print('models used',sorted(set((m,e) for m,e,_ in FakeClient.calls)))
 # Grade the first code task.
 st=json.loads((root/'School HQ App/Bridge/state.json').read_text());st['brief']={'id':'req-1','tasks':tasks};(root/'School HQ App/Bridge/state.json').write_text(json.dumps(st))
 (root/'School HQ App/Bridge/Packets/req-1').mkdir(parents=True);(root/'School HQ App/Bridge/Packets/req-1/rubrics.json').write_text(json.dumps(published['rubrics']))
 st2=c.load(root);c.record_packet(published['packet'],tasks,st2);c.persist(st2,root)
 import school_hq_grader as g
 fb=g.submit({'brief_id':'req-1','exercise_id':tasks[0]['exercise_id'],'answer':'void byeList(node*h){free(h);byeList(h->next);}','attempt_id':'a1b2c3d4e5f6'},client_factory=lambda:FakeClient)
 print('grade',fb['latest']['outcome'],fb['retry']['exercise_id'])
 fb2=g.submit({'brief_id':'req-1','exercise_id':fb['retry']['exercise_id'],'answer':'int sumList(node*h){return h?h->v+sumList(h->next):0;}','attempt_id':'b1b2c3d4e5f6'},client_factory=lambda:FakeClient)
 print('retry graded',fb2['latest']['outcome'])
 s=c.load(root);print('attempts recorded',len(s['attempts']),[ (a['outcome'],a['exercise_id'][-20:]) for a in s['attempts'][-2:]])
 print("PACKET normal",len(published["packet"]["tasks"]),"extra",len(published["packet"]["catch_up_tasks"]),[t["title"] for t in published["packet"]["tasks"]][:3]);print("LIMITS",published["packet"]["source_limits"][:1500]);print("OK")
main()

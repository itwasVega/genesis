"""Saved mixed assessments over original practice; answers stay hidden until finish."""
import json,uuid
from pathlib import Path
from datetime import datetime,timezone
import genesis_coaching as c

def session_path(root):return Path(root)/'Genesis Study/mixed-session.json'
def public(s):
 if not s:return {'status':'none','questions':[]}
 result={k:v for k,v in s.items() if k!='items'};result['questions']=[]
 for item in s.get('items',[]):
  q=item['question'];result['questions'].append({'id':item['lesson_id']+':'+q['id'],'lesson_id':item['lesson_id'],'prompt':q['prompt'],'format':q.get('format','targeted answer'),'input':__import__('genesis_exercises').answer_input(q['checker']),'answer':item.get('answer','')})
 return result

def result_row(item,outcome,feedback):
 title=item.get('objective_title') or item.get('lesson_title') or item['lesson_id'].replace('-',' ')
 return {'question_id':item['lesson_id']+':'+item['question']['id'],'objective_ids':item.get('objective_ids',[]),'outcome':outcome,'feedback':title+'\n\n'+feedback}

def run(action,root,data,j,payload,when):
 p=session_path(root);s=json.loads(p.read_text()) if p.exists() else {}
 if action=='mixed-start':
  if s.get('status') in ('active','paused'):return public(s)
  from genesis_preparation import build
  plan=build(root,when);eligible=[e for e in plan['assessments'] if e['active'] and e['source_verified'] and not e['stale'] and e.get('certainty') in ('confirmed','listed')]
  scores={r['course']:r['priority'] for r in plan['course_priorities']}
  if not eligible:raise ValueError('No current verified assessment scope is available for a mixed check.')
  exam=max(eligible,key=lambda e:scores.get(e['course'],0));ids={v for o in exam['objectives'] for v in o.get('lesson_ids',[])};items=[]
  for l in data['lessons']:
   if l['id'] not in ids:continue
   q=min(l['questions'],key=lambda q:sum(a['lesson_id']==l['id'] and a['question_id']==q['id'] for a in j['attempts']))
   objectives=[o for o in exam['objectives'] if l['id'] in o.get('lesson_ids',[])]
   items.append({'lesson_id':l['id'],'lesson_title':l['title'],'objective_ids':[o['id'] for o in objectives],'objective_title':' / '.join(o['title'] for o in objectives),'question':q,'answer':''})
  if not items:raise ValueError('No original practice is mapped to this assessment yet.')
  s={'id':str(uuid.uuid4()),'assessment_id':exam['id'],'course':exam['course'],'name':exam['name'],'status':'active','started_at':when.isoformat(),'last_resumed_at':when.isoformat(),'elapsed_seconds':0,'target_minutes':min(exam.get('duration_minutes') or 5*len(items),5*len(items)),'limits':'Sampled mixed practice, not a full exam or readiness certification. No forced cutoff. Written programs remain pending review.','items':items,'plan_version':plan['version']}
 elif action=='mixed-status':return public(s)
 else:
  if not s or s.get('id')!=payload.get('session_id'):raise ValueError('The mixed check changed; saved work is preserved.')
  if s['status']=='finished':return public(s)
  if action=='mixed-answer':
   key=payload.get('question_id');item=next((x for x in s['items'] if x['lesson_id']+':'+x['question']['id']==key),None)
   if item is None:raise ValueError('Unknown assessment question')
   answer=payload.get('answer','')
   if not isinstance(answer,str) or len(answer)>20000:raise ValueError('Answer too long')
   item['answer']=answer
  elif action in ('mixed-pause','mixed-finish'):
   answers=payload.get('answers',{})
   keys={x['lesson_id']+':'+x['question']['id'] for x in s['items']}
   if not isinstance(answers,dict) or any(k not in keys or not isinstance(v,str) or len(v)>20000 for k,v in answers.items()):raise ValueError('Invalid mixed answer drafts; session preserved')
   for item in s['items']:
    key=item['lesson_id']+':'+item['question']['id']
    if key in answers:item['answer']=answers[key]
   if s['status']=='active':s['elapsed_seconds']+=max(0,(when-datetime.fromisoformat(s['last_resumed_at'])).total_seconds())
   s['status']='paused'
   if action=='mixed-finish':
    from genesis_learning import grade,canonical
    reviewed=[]
    for item in s['items']:
     q=item['question'];answer=item['answer'];outcome,feedback=grade(answer,q['checker'])
     if outcome=='invalid':reviewed.append(result_row(item,'unanswered' if not answer.strip() else 'invalid',feedback));continue
     ident=s['id']+':'+item['lesson_id']+':'+q['id'];aids='hint' if item['lesson_id']+'|'+q['id'] in j['hints'] or payload.get('used_help') else 'closed_book'
     row={'id':ident,'lesson_id':item['lesson_id'],'question_id':q['id'],'answer':answer,'aids':aids,'outcome':outcome,'feedback':feedback,'phase':'mixed','at':when.isoformat(),'question_sha256':canonical(q)}
     if not any(a['id']==ident for a in j['attempts']):j['attempts'].append(row)
     if outcome=='incorrect' and item['lesson_id']+'|'+q['id'] not in j['hints']:j['hints'].append(item['lesson_id']+'|'+q['id'])
     reviewed.append(result_row(item,outcome,feedback))
    c.atomic(Path(root)/'Genesis Study/learning-journal.json',j);s.update(status='finished',finished_at=when.isoformat(),results=reviewed)
  elif action=='mixed-resume':
   if s['status']=='paused':s.update(status='active',last_resumed_at=when.isoformat())
  else:raise ValueError('Unknown mixed action')
 c.atomic(p,s);return public(s)

#!/usr/bin/env python3
"""Offline guided practice. Original exercises; no model, networking or code execution.

The journal is authoritative: projection into the existing coaching state is
idempotent and recoverable after interruption. Never alters source readiness.
"""
import argparse, ast, fcntl, hashlib, json, re, uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo
import school_hq_coaching as coaching
from school_hq_exercises import blocks, answer_input
from school_hq_planning import priorities, verified_grades, listed_deadlines

ROOT=Path(__file__).resolve().parent
BANK=ROOT/'School HQ Study/lesson-bank.json'
CHECKS={'number','sequence','tokens','polynomial','choice','multi_select','review'}

def clock(): return datetime.now(timezone.utc)
def school_day(when): return when.astimezone(__import__('school_hq_connections').zone()).date()
def canonical(value): return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def polynomial(value):
    """Exact rational polynomial arithmetic; intentionally not a general CAS."""
    if len(value)>400: raise ValueError('Expression too long')
    value=value.replace('^','**').replace('−','-').replace('×','*')
    value=re.sub(r'(?<=\d)(?=x)|(?<=\))(?=[x(])|(?<=x)(?=\()', '*',value)
    tree=ast.parse(value.strip(),mode='eval')
    if sum(1 for _ in ast.walk(tree))>100: raise ValueError('Expression too complex')
    def tidy(p):return {i:v for i,v in p.items() if v}
    def add(a,b):
        out=dict(a)
        for i,v in b.items():out[i]=out.get(i,Fraction(0))+v
        return tidy(out)
    def mul(a,b):
        out={}
        for i,v in a.items():
            for j,w in b.items():
                if i+j>20:raise ValueError('Degree limit')
                out[i+j]=out.get(i+j,Fraction(0))+v*w
        return tidy(out)
    def visit(n):
        if isinstance(n,ast.Constant) and type(n.value) in (int,float) and abs(n.value)<=1000000:return tidy({0:Fraction(str(n.value))})
        if isinstance(n,ast.Name) and n.id=='x':return {1:Fraction(1)}
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):
            return {i:v*(-1 if isinstance(n.op,ast.USub) else 1) for i,v in visit(n.operand).items()}
        if isinstance(n,ast.BinOp):
            a=visit(n.left)
            if isinstance(n.op,ast.Pow):
                if not isinstance(n.right,ast.Constant) or type(n.right.value)!=int or not 0<=n.right.value<=10:raise ValueError('Use nonnegative integer powers up to 10')
                out={0:Fraction(1)}
                for _ in range(n.right.value):out=mul(out,a)
                return out
            b=visit(n.right)
            if isinstance(n.op,ast.Add):return add(a,b)
            if isinstance(n.op,ast.Sub):return add(a,{i:-v for i,v in b.items()})
            if isinstance(n.op,ast.Mult):return mul(a,b)
            if isinstance(n.op,ast.Div) and set(b)=={0} and b[0]:return {i:v/b[0] for i,v in a.items()}
        raise ValueError('Use x, numbers, +, -, *, / by constants, and integer powers')
    return visit(tree.body)

def grade(answer, checker):
    if checker.get('type')=='review':
        return ('pending_review','Saved for review against the written-work rubric. No correctness or mastery was awarded.') if isinstance(answer,str) and answer.strip() and len(answer)<=20000 else ('invalid','Write your response first.')
    if not isinstance(answer,str):return 'invalid','Enter a supported text answer.'
    answer=answer.strip()
    if not answer:return 'invalid','Write an answer first.'
    if len(answer)>2000:return 'invalid','Keep this answer under 2,000 characters.'
    try:
        kind=checker['type'];expected=checker['expected']
        if kind=='number':
            # Reject prose and unexpected expressions rather than guessing intent.
            if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?(?:\s*/\s*[+-]?\d+)?',answer):raise ValueError('Enter one number or fraction, without a label.')
            a=Fraction(answer.replace(' ',''));b=Fraction(str(expected));tolerance=Fraction(str(checker.get('absolute_tolerance',0)))
            if tolerance<0 or tolerance>1:raise ValueError('Unsupported tolerance')
            ok=abs(a-b)<=tolerance
        elif kind=='sequence':
            normalized=re.sub(r'\s*(?:->|→|,)\s*',' ',answer).split()
            if not normalized or any(not re.fullmatch(r'-?\d+',x) for x in normalized):raise ValueError('Enter only the numbers in order, separated by spaces, commas or arrows.')
            ok=[int(x) for x in normalized]==expected
        elif kind=='tokens':
            clean=lambda s:re.sub(r'\s+','',s).casefold()
            ok=clean(answer) in {clean(x) for x in expected}
            if not ok and (len(answer)>80 or '\n' in answer):raise ValueError('Use the short answer format shown in the question; this checker cannot grade a written explanation.')
        elif kind=='polynomial':ok=polynomial(answer)==polynomial(expected)
        elif kind in ('choice','multi_select'):
            choices=checker['choices']
            if kind=='choice':
                if answer not in choices:raise ValueError('Choose one listed answer.')
                ok=answer==expected
            else:
                import json as _json
                selected=_json.loads(answer)
                if not isinstance(selected,list) or not selected or len(selected)!=len(set(selected)) or any(x not in choices for x in selected):raise ValueError('Choose one or more listed answers.')
                ok=set(selected)==set(expected)
        else:return 'invalid','This answer needs a reviewed assessment; it is not auto-graded.'
    except (ValueError,TypeError,KeyError,SyntaxError,ZeroDivisionError,OverflowError) as e:
        return 'invalid',str(e) or 'I could not interpret that answer. No grade was recorded.'
    return ('correct',checker['explanation']) if ok else ('incorrect',checker['feedback']+'\n\nWorked answer: '+checker['solution'])

def bank(path=BANK,include_extensions=False):
    data=json.loads(Path(path).read_text());extra=Path(path).parent/'practice-extension.json'
    if include_extensions and extra.exists():data['lessons']+=json.loads(extra.read_text()).get('lessons',[])
    lessons=data['lessons'];ids={x['id'] for x in lessons}
    if len(ids)!=len(lessons):raise ValueError('Duplicate lesson')
    for l in lessons:
        if any(x not in ids for x in l['prerequisites']):raise ValueError('Unknown prerequisite')
        if len(l['questions'])<3:raise ValueError('Need distinct practice, transfer and retention variants')
        for q in l['questions']:
            if q['checker']['type'] not in CHECKS:raise ValueError('Unknown checker')
            if q['checker']['type']!='review' and grade(q['checker']['answer_for_test'],q['checker'])[0]!='correct':raise ValueError('Practice key fails its checker')
    def visit(i,seen):
        if i in seen:raise ValueError('Prerequisite cycle')
        for p in next(x for x in lessons if x['id']==i)['prerequisites']:visit(p,seen|{i})
    for l in lessons:visit(l['id'],set())
    return data

def load(root):
    p=root/'School HQ Study/learning-journal.json'
    return json.loads(p.read_text()) if p.exists() else {'schema':1,'attempts':[],'hints':[],'lessons_seen':[]}

def independent(a):return a['outcome']=='correct' and a.get('aids')=='closed_book'

def lesson_status(l,j,when):
    rows=[a for a in j['attempts'] if a['lesson_id']==l['id'] and a['outcome'] not in ('invalid','pending_review')]
    # An error or use of help reopens practice. Historical evidence stays intact.
    last_reset=max((i for i,a in enumerate(rows) if not independent(a)),default=-1)
    good=rows[last_reset+1:]
    distinct={a['question_id'] for a in good if independent(a)}
    retained=any(a.get('phase')=='retention' and independent(a) for a in good)
    level='retained' if retained and len(distinct)>=3 else 'proficient' if len(distinct)>=2 else 'familiar' if distinct else 'learning' if rows else 'untested'
    due=None
    if good:
        offset=[1,3,7,14,30][min(max(0,len(distinct)-2),4)]
        due=(school_day(datetime.fromisoformat(good[-1]['at']))+timedelta(days=offset)).isoformat()
    return {'level':level,'independent_variants':len(distinct),'due':due,'attempts':len(rows),'last_error':bool(rows and not independent(rows[-1]))}

def choose(data,j,when,planning_state=None):
    day=school_day(when).isoformat();lessons=data['lessons']
    statuses={l['id']:lesson_status(l,j,when) for l in lessons}
    scores={r['course']:r['priority'] for r in priorities(planning_state or {},school_day(when))}
    plan=(planning_state or {}).get('_preparation',{});focus=plan.get('focus_lessons',{});objective_scores=plan.get('lesson_scores',{})
    pending_lessons={a['lesson_id'] for a in j['attempts'] if a.get('outcome')=='pending_review'}
    lessons=[l for l in lessons if l['id'] not in pending_lessons]
    active_courses={l['course'] for l in lessons if statuses[l['id']]['level'] not in ('proficient','retained') or (statuses[l['id']]['due'] and statuses[l['id']]['due']<=day)}
    preferred=max(sorted(active_courses),key=lambda c:scores.get(c,0)) if active_courses else None
    # Misses lead to the nearest not-yet-demonstrated prerequisite, not a menu.
    failed=[l for l in lessons if statuses[l['id']]['last_error'] and l['course']==preferred]
    def unmet(l):
        for p in l['prerequisites']:
            if statuses[p]['level'] in ('untested','learning'):
                parent=next((x for x in lessons if x['id']==p),None)
                if parent is not None:return unmet(parent)
        return l
    # Finish a recent failed learning step before switching courses. This is
    # local question continuity, not a mutation of course/deadline priorities.
    recent=j['attempts'][-1] if j['attempts'] else None
    if recent and recent.get('outcome')=='incorrect':
        try:age=(when-datetime.fromisoformat(recent['at'])).total_seconds()
        except (ValueError,KeyError,TypeError):age=-1
        target=next((l for l in lessons if l['id']==recent.get('lesson_id')),None)
        if target is not None and 0<=age<=86400:
            return unmet(target),statuses,'Repair the last error with a different question before resuming the course plan.'
    if failed:
        latest=max(failed,key=lambda l:next(a['at'] for a in reversed(j['attempts']) if a['lesson_id']==l['id']))
        selected=unmet(latest)
        # Don't repeat already-satisfied repair indefinitely.
        if selected==latest or statuses[selected['id']]['level'] in ('untested','learning'):return selected,statuses,'Repair the last error before moving on.'
    eligible=[l for l in lessons if all(statuses[p]['level'] in ('familiar','proficient','retained') for p in l['prerequisites'])]
    due=[l for l in eligible if l['course']==preferred and statuses[l['id']]['due'] and statuses[l['id']]['due']<=day]
    if due:return min(due,key=lambda l:(statuses[l['id']]['due'],l['order'])),statuses,'A spaced retrieval check is due.'
    candidates=[l for l in eligible if statuses[l['id']]['level'] not in ('proficient','retained')]
    if not candidates:return None,statuses,'This practice set is complete for now. Return on the next review date; this is not proof of full exam readiness.'
    scores={r['course']:r['priority'] for r in priorities(planning_state or {},school_day(when))}
    # Bank size/order only breaks ties within a course; never raises its score.
    selected=min(candidates,key=lambda l:(-scores.get(l['course'],0),0 if l['id'] in focus.get(l['course'],[]) else 1,-objective_scores.get(l['id'],0),l['order']))
    selected=unmet(selected)
    ranked=priorities(planning_state or {},school_day(when))
    missing=[r['course'] for r in ranked if not any(l['course']==r['course'] for l in lessons)]
    reason='Build the next prerequisite, then solve a different problem without notes.'
    if missing:reason+=' No guided question bank for '+', '.join(missing)+'. Use their source-backed brief tasks; this practice is not their complete plan.'
    return selected,statuses,reason

def view(data,j,when,planning_state=None):
    selected,statuses,why=choose(data,j,when,planning_state)
    today=school_day(when).isoformat();count=sum(school_day(datetime.fromisoformat(a['at'])).isoformat()==today and a['outcome']!='invalid' for a in j['attempts'])
    out={'schema':1,'reason':why,'limits':data['limits'],'statuses':statuses,'attempts_in_session':count,
         'feedback':j['attempts'][-1] if j['attempts'] else None,'lesson':None,
         'checkpoint':count>0 and count%6==0,'next_review':min((s['due'] for s in statuses.values() if s['due'] and s['due']>today),default=None)}
    if out['feedback']:
        last=out['feedback']
        previous=next((l for l in data['lessons'] if l['id']==last.get('lesson_id')),None)
        out['feedback']={**last,'blocks':blocks(last['feedback'],previous['course'] if previous else '')}
    if selected:
        rows=[a for a in j['attempts'] if a['lesson_id']==selected['id'] and a['outcome'] not in ('invalid','pending_review')]
        used={a['question_id'] for a in rows if independent(a)}
        last=rows[-1]['question_id'] if rows else None
        questions=selected['questions']
        exposed={key.split('|',1)[1] for key in j['hints'] if key.startswith(selected['id']+'|')}
        q=next((q for q in questions if q['id'] not in used and q['id'] not in exposed and q['id']!=last),None) or next((q for q in questions if q['id'] not in used and q['id']!=last),None) or next((q for q in questions if q['id']!=last),questions[0])
        pinned=j.get('active_question',{})
        if pinned.get('lesson_id')==selected['id']:
            q=next((item for item in questions if item['id']==pinned.get('question_id')),q)
        hint_key=selected['id']+'|'+q['id']
        out['lesson']={k:v for k,v in selected.items() if k not in ('questions',)}
        due=statuses[selected['id']]['due']
        phase='retention' if due and due<=today else 'checkpoint' if statuses[selected['id']]['independent_variants'] else 'practice'
        out['lesson'].update(question={k:v for k,v in q.items() if k!='checker'},phase=phase,
                             hint_used=hint_key in j['hints'],lesson_seen=selected['id'] in j['lessons_seen'])
        out['lesson']['presentation_schema']=2
        out['lesson']['teaching_blocks']=blocks(selected['teaching'],selected['course'])
        out['lesson']['example_blocks']=blocks(selected['worked_example'],selected['course'])
        out['lesson']['hint_blocks']=blocks(selected['hint'],selected['course'])
        out['lesson']['question']['blocks']=q.get('blocks') or blocks(q['prompt'],selected['course'])
        out['lesson']['question']['input']=answer_input(q['checker'])
        out['lesson']['token']=canonical({'lesson':selected['id'],'question':q,'journal':j})
    return out

def project(data,j,root):
    """Merge actual graded evidence into the existing evidence/mastery tracker."""
    state=coaching.load(root);known={a['submission_id'] for a in state['attempts']}
    changed=False
    for a in j['attempts']:
        if a['outcome'] in ('invalid','pending_review') or a['id'] in known:continue
        l=next(x for x in data['lessons'] if x['id']==a['lesson_id']);q=next(x for x in l['questions'] if x['id']==a['question_id'])
        if a.get('question_sha256')!=canonical(q):raise ValueError('A pending practice question changed; keep the original evidence for review')
        eid='guided:'+l['id']+':'+q['id'];sid=l['skill_id']
        if sid not in {s['id'] for s in state['skills']}:
            if l['parent_skill_id'] not in {s['id'] for s in state['skills']}:
                state['skills'].append({'id':l['parent_skill_id'],'course':l['course'],'name':l['title'],'status':'untested','evidence':[],'successes':0})
            state['skills'].append({'id':sid,'course':l['course'],'name':l['title']+' — targeted final-answer checks',
                'parent_skill_id':l['parent_skill_id'],'evidence_scope':l['evidence_scope'],
                'status':'untested','evidence':[],'successes':0})
        state['exercises'].setdefault(eid,{'fingerprint':canonical(q['prompt']),'course':l['course'],'skill_ids':[sid],'rubric_verified':True})
        evidence={'id':a['id'],'exercise_id':eid,'answer':a['answer'],'aids':a['aids'],'assessment_allowed':True}
        review={'submission_id':a['id'],'outcome':a['outcome'],'feedback':a['feedback'],
                'verification_evidence':'Deterministic original-practice '+q['checker']['type']+' checker; bank '+canonical(q),
                'specific_error':q['checker']['feedback'],'transfer_variant':q.get('transfer_context') is True and a['phase']=='retention'}
        coaching.assess(state,review,evidence,school_day(datetime.fromisoformat(a['at'])))
        changed=True
    if changed:coaching.persist(state,root)

def learning_context(root,when=None):
    from school_hq_preparation import planning_state,write
    s=planning_state(root,coaching.load(root),when);s['_verified_grades']=verified_grades(root);s['_listed_deadlines']=listed_deadlines(root)
    s['_preparation']=write(root,when)
    return s

def run(action,root=ROOT,submission=None,when=None):
    when=when or clock();data=bank(root/'School HQ Study/lesson-bank.json',include_extensions=True);j=load(root);planning_state=learning_context(root,when)
    if action.startswith('mixed-'):
        from school_hq_mixed import run as mixed
        result=mixed(action,root,data,j,submission or {},when)
        if action=='mixed-finish':project(data,j,root)
        return result
    if action=='next':project(data,j,root)
    if action=='submit' and submission and any(a['id']==submission.get('id') for a in j['attempts']):
        project(data,j,root)
        planning_state=learning_context(root,when)
        return view(data,j,when,planning_state)
    if action in ('submit','hint','learn'):
        current=view(data,j,when,planning_state)['lesson']
        if not current or not submission or submission.get('token')!=current['token']:raise ValueError('The practice changed. Your answer is preserved; reload before submitting.')
        key=current['id']+'|'+current['question']['id']
        if action in ('hint','learn'):j['active_question']={'lesson_id':current['id'],'question_id':current['question']['id']}
        if action=='hint':
            if key not in j['hints']:j['hints'].append(key)
        elif action=='learn':
            if current['id'] not in j['lessons_seen']:j['lessons_seen'].append(current['id'])
        else:
            l=next(x for x in data['lessons'] if x['id']==current['id']);q=next(x for x in l['questions'] if x['id']==current['question']['id'])
            answer=submission.get('answer','')
            outcome,feedback=grade(answer,q['checker'])
            if outcome=='invalid':return {**view(data,j,when,planning_state),'validation_message':feedback}
            if any(a['id']==submission['id'] for a in j['attempts']):return view(data,j,when,planning_state)
            if not re.fullmatch(r'[a-zA-Z0-9-]{8,64}',submission.get('id','')):raise ValueError('Submission ID is invalid')
            j.pop('active_question',None)
            j['attempts'].append({'id':submission['id'],'lesson_id':l['id'],'question_id':q['id'],
                'answer':answer,'aids':'hint' if key in j['hints'] or submission.get('used_help') else 'closed_book',
                'outcome':outcome,'feedback':feedback,'phase':current['phase'],'at':when.isoformat(),'question_sha256':canonical(q)})
            # Once a worked solution was exposed, this exact variant can never
            # establish new independent evidence. Use a fresh variant instead.
            if outcome=='incorrect' and key not in j['hints']:j['hints'].append(key)
        coaching.atomic(root/'School HQ Study/learning-journal.json',j)
        if action=='submit':project(data,j,root)
    elif action=='recover':project(data,j,root)
    # Assessment projection may change course priorities. Return the same planner
    # snapshot that the next action will load, never a pre-assessment next question.
    planning_state=learning_context(root,when)
    return view(data,j,when,planning_state)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('next','submit','hint','learn','recover','mixed-start','mixed-status','mixed-answer','mixed-pause','mixed-resume','mixed-finish'));a=p.parse_args()
    # One lock serializes journal and coaching projection with normal coaching.
    with (ROOT/'School HQ Study/.coaching.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        import sys
        payload=json.load(sys.stdin) if a.action in ('submit','hint','learn') or a.action.startswith('mixed-') and a.action not in ('mixed-start','mixed-status') else None
        print(json.dumps(run(a.action,submission=payload)))
if __name__=='__main__':main()

"""Course-neutral deterministic planning. Content-bank size is never an input.

Scores are interpretable evidence signals, not exam-readiness probabilities.
"""
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import re
EXCLUDED_COURSES=set()
DEFAULT_PASS=70
def configured_courses(state):
    return sorted((set(state.get('_courses',[]))|{x['course'] for key in ('skills','events','_listed_deadlines','_assessments') for x in state.get(key,[]) if x.get('course')})-{'School'}-EXCLUDED_COURSES)

def verified_grades(root):
    """Only the request-bound app projection of actual verified gradebooks."""
    import json,hashlib
    from pathlib import Path
    try:
        bridge=Path(root)/'Genesis App/Bridge'
        summary=json.loads((bridge/'grades.json').read_text());ident=summary['request_id']
        receipt=json.loads((bridge/'Receipts'/(ident+'-canvas.json')).read_text())
        snapshots=receipt.get('snapshots',[])
        row=next(x for x in snapshots if x.get('role')=='gradebooks')
        if hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()!=row['sha256']:return {}
        book=json.loads(Path(row['path']).read_text())
        if receipt.get('schema')!=2 or receipt.get('partial') or receipt.get('error') or receipt.get('request_id')!=ident:return {}
        captured=datetime.fromisoformat(receipt['checked_at'].replace('Z','+00:00')).astimezone(__import__('genesis_connections').zone()).date()
        if not 0<=(datetime.now(__import__('genesis_connections').zone()).date()-captured).days<=14:return {}
        values={}
        for course,entry in book.items():
            match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)%\s*',str(entry.get('total_displayed','')))
            if match:values[course]=float(match[1])
        return values
    except (OSError,ValueError,KeyError,StopIteration,TypeError):return {}

EXAM_ITEM=re.compile(r'(?i)\b(?:exam|midterm|mid term|test)\b|\bE\d\b|exam\d|^test\s*\d')
NOT_EXAM=re.compile(r'(?i)placeholder|replacement|review|practice|survey|attendance|reflection|preparedness|syllabus')
def exam_results(root):
    """Scored exams/tests per course from the latest gradebook, as fractions,
    oldest first: {'COP3330': [{'name':'E1','fraction':0.34}, ...]}."""
    import json
    from pathlib import Path
    out={}
    try:
        bridge=Path(root)/'Genesis App/Bridge';ident=json.loads((bridge/'grades.json').read_text())['request_id']
        book=json.loads((bridge/'Runs'/ident/'gradebooks.json').read_text())
    except (OSError,ValueError,KeyError,TypeError):return out
    for course,entry in book.items():
        for a in entry.get('assignments',[]):
            name=a.get('name','')
            if NOT_EXAM.search(name) or not EXAM_ITEM.search(name):continue
            m=re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',str(a.get('score_displayed','')))
            if m and float(m[2])>0:out.setdefault(course,[]).append({'name':re.split(r'\s+[-–(]\s*',name)[0].strip()[:40],'fraction':round(float(m[1])/float(m[2]),3)})
    return out

def low_exams(root):
    return {c:[r['fraction'] for r in rows if r['fraction']<0.7] for c,rows in exam_results(root).items() if any(r['fraction']<0.7 for r in rows)}

def _displayed_deadlines(root):
    """Bounded date signals from hashed Canvas rows; explicit year inference.
    Assessment labels alone never confirm an exam appointment or its scope.
    """
    import json,hashlib
    from pathlib import Path
    try:
        bridge=Path(root)/'Genesis App/Bridge';summary=json.loads((bridge/'grades.json').read_text());ident=summary['request_id']
        receipt=json.loads((bridge/'Receipts'/(ident+'-canvas.json')).read_text())
        row=next(x for x in receipt['snapshots'] if x.get('role')=='gradebooks');data=Path(row['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256'] or receipt.get('partial') or receipt.get('error'):return []
        captured=datetime.fromisoformat(receipt['checked_at'].replace('Z','+00:00')).astimezone(__import__('genesis_connections').zone()).date();book=json.loads(data);out=[]
        for course,entry in book.items():
            for item in entry.get('assignments',[]):
                if item.get('submitted'):continue
                quoted=item.get('due','');match=re.match(r'([A-Z][a-z]{2}) (\d{1,2})(?:\b|,)',quoted)
                if not match:continue
                month=datetime.strptime(match[1],'%b').month;year=captured.year
                if captured.month==12 and month==1:year+=1
                due=date(year,month,int(match[2]))
                if (due-captured).days>90:continue
                out.append({'course':course,'date':due.isoformat(),'name':item['name'],'certainty':'listed','quoted_due':quoted,'year_inferred_from_capture':captured.isoformat(),'scope_verified':False,'url':item.get('source'),'source_hash':row['sha256']})
        return out
    except (OSError,ValueError,KeyError,StopIteration,TypeError):return []

def listed_deadlines(root):
    """Prefer hash-verified structured assignments; preserve unresolved overdue work.

    Displayed date inference is only a labelled fallback for courses without a
    structured collection. Never infer submission from a numeric score alone.
    """
    import json,hashlib
    from pathlib import Path
    bridge=Path(root)/'Genesis App/Bridge'
    try:
        summary=json.loads((bridge/'grades.json').read_text());ident=summary['request_id']
        receipt=json.loads((bridge/'Receipts'/(ident+'-canvas.json')).read_text())
        if receipt.get('schema')!=2 or receipt.get('request_id')!=ident or receipt.get('partial') or receipt.get('error'):return []
        captured=datetime.fromisoformat(receipt['checked_at'].replace('Z','+00:00'))
        if captured.tzinfo is None or captured>datetime.now(timezone.utc):return []
        zone=__import__('genesis_connections').zone();day=captured.astimezone(zone).date()
        rows=[];structured=set();seen=set()
        for source in receipt.get('snapshots',[]):
            if not source.get('role','').endswith((':assignments',':detail')):continue
            path=Path(source['path']).resolve();path.relative_to(Path(root).resolve())
            data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=source['sha256']:return []
            payload=json.loads(data);course=payload.get('course')
            if not course:continue
            if payload.get('kind')=='assignments' and isinstance(payload.get('items'),list):
                structured.add(course);items=payload['items']
            elif isinstance(payload.get('assignment'),dict):items=[payload['assignment']]
            else:continue
            for item in items:
                key=(str(item.get('course_id') or payload.get('url','')),str(item.get('id')))
                if item.get('id') is None or key in seen:continue
                seen.add(key)
                sub=item.get('submission') or {};types=item.get('submission_types') or []
                if item.get('published') is False or sub.get('excused') is True:continue
                # These are informational items, not student submissions.
                if types==['not_graded']:continue
                submitted=bool(sub.get('submitted_at')) or sub.get('workflow_state') in ('submitted','pending_review')
                resolved=sub.get('workflow_state')=='graded' and sub.get('missing') is False
                if submitted or resolved:continue
                value=sub.get('cached_due_date') or item.get('due_at')
                if not value:continue  # Undated is not an invented deadline.
                try:
                    due=datetime.fromisoformat(value.replace('Z','+00:00'))
                    if due.tzinfo is None:continue
                except (ValueError,TypeError):continue
                local=due.astimezone(zone)
                if (local.date()-day).days>90:continue
                rows.append({'course':course,'assignment_id':str(item['id']),'date':local.date().isoformat(),
                    'due_at':due.isoformat(),'timezone':__import__('genesis_connections').zone_name(),'name':item.get('name','Untitled assignment'),
                    'certainty':'listed','quoted_due':local.strftime('%b %d, %Y at %I:%M %p %Z'),
                    'due_is_exact':True,'scope_verified':False,'url':item.get('html_url'),
                    'source_hash':source['sha256'],'source_path':str(path),'captured_at':captured.isoformat(),
                    'submission_state':sub.get('workflow_state','unknown'),'missing':sub.get('missing'),
                    'overdue':due<captured,'locked_for_user':bool(item.get('locked_for_user')),
                    'action':'Check late-work options' if item.get('locked_for_user') and due<captured else 'Resolve unfinished work'})
        return rows+[r for r in _displayed_deadlines(root) if r['course'] not in structured]
    except (OSError,ValueError,KeyError,TypeError):return []


def recently_strong(state,course,day,window=14):
    """Recent independent work outweighs an old low exam: at least three independent
    correct answers in the last two weeks and four of the last five answers correct."""
    day=date.fromisoformat(day) if isinstance(day,str) else day
    rows=sorted([a for a in state.get('attempts',[]) if state.get('exercises',{}).get(a.get('exercise_id'),{}).get('course')==course],key=lambda a:a.get('attempt_date',''))
    start=(day-timedelta(days=window)).isoformat();last=rows[-5:]
    return sum(1 for a in rows if a.get('attempt_date','')>=start and a.get('independent'))>=3 and bool(last) and sum(a.get('outcome')=='correct' for a in last)/len(last)>=0.8

def priorities(state,day,grades=None):
    result=[];day=date.fromisoformat(day) if isinstance(day,str) else day
    for course in configured_courses(state):
        skills=[s for s in state.get('skills',[]) if s['course']==course]
        attempts=[a for a in state.get('attempts',[]) if state.get('exercises',{}).get(a.get('exercise_id'),{}).get('course')==course]
        # Max/ratio/recency: adding duplicate exercises cannot inflate priority.
        score=20.;reasons=['diagnostic evidence needed'];events=[]
        for event in state.get('events',[])+state.get('_listed_deadlines',[]):
            if event.get('course')!=course or event.get('certainty') not in ('confirmed','listed','reported') or event.get('superseded'):continue
            if re.search(r'(?i)attendance|reflection|survey|syllabus',event.get('name','')):continue   # not study work
            days=(date.fromisoformat(event['date'])-day).days
            if 0<=days<=14 or (days<0 and event in state.get('_listed_deadlines',[])):
                exam=event.get('kind')=='exam' or bool(re.search(r'^(?:exam|test|midterm|quiz|final)(?:\b|\d)',event.get('name',''),re.I))
                value=300 if days<0 else (420 if exam and event.get('certainty')=='confirmed' else 170 if exam else 260)/(days+1)
                events.append((value,event,days))
        if events:
            value,event,days=max(events,key=lambda x:x[0]);score+=value
            reasons=[event['name']+(' · overdue; '+event.get('action','check unfinished work') if days<0 else '')+(' · listed due '+event.get('quoted_due',event['date'])+(' (structured Canvas due date; exam appointment/scope not established)' if event.get('due_is_exact') else ' (year from '+event.get('year_inferred_from_capture','source')+' capture; assessment timing unconfirmed)') if event.get('certainty')=='listed' else ' on '+event['date']+(' · scope unverified' if not event.get('scope_verified') else ''))]
        recent=sorted(attempts,key=lambda a:a.get('attempt_date',''))[-5:]
        if recent:
            errors=sum(a.get('outcome')=='incorrect' for a in recent)/len(recent);score+=60*errors
            if errors:reasons.append(str(round(errors*100))+'% incorrect in recent reviewed attempts')
        due=[q for q in state.get('review_queue',[]) if q.get('due','9999')<=day.isoformat() and any(s['id']==q['skill_id'] for s in skills)]
        if due:score+=55;reasons.append('spaced retrieval due')
        grade=(grades or state.get('_verified_grades',{})).get(course)
        if isinstance(grade,(int,float)) and 0<=grade<=100:
            policy=state.get('_grade_policies',{}).get(course,{})
            target=policy.get('passing_percent');assumed=False
            reasons.append('verified grade '+str(round(grade,2))+'%')
            if not (isinstance(target,(int,float)) and 0<=target<=100):
                # No mapped syllabus policy: use the usual C line (70%) so a failing
                # grade still counts. Labelled as an assumption, never as the policy.
                target=DEFAULT_PASS;assumed=True
            risk=max(0,target-grade)*1.5;score+=risk
            if risk:reasons.append('below '+('the assumed ' if assumed else 'the verified ')+str(target)+'% '+('C line (syllabus policy not mapped)' if assumed else 'course passing threshold'))
        # Exams are where the grade is made: low exam results raise the course even
        # when nothing is due this week (they also drive the recovery track).
        # Units: each low exam's shortfall is a fraction (a 50% exam is 0.20 below 0.70), so
        # one 50% exam adds 24 points; a deadline in two days adds about 87-140. Fresh
        # independent work in the course halves it: an old score is not current evidence.
        lows=state.get('_low_exams',{}).get(course,[])
        if lows:
            gap=sum(max(0,0.7-x) for x in lows)/len(lows);strong=recently_strong(state,course,day)
            score+=round(120*gap*(0.5 if strong else 1),2);reasons.append('low exam results ('+', '.join('%d%%'%round(x*100) for x in lows[:3])+')'+(', recent independent work is strong' if strong else ''))
        last=max((a.get('attempt_date','') for a in attempts),default='')
        gap=min(10,max(0,(day-date.fromisoformat(last)).days)) if last else 10
        score+=gap*2
        reasons.append('no reviewed work yet' if not last else 'last reviewed '+last)
        result.append({'course':course,'priority':round(score,2),'reason':'; '.join(reasons),'has_reviewed_work':bool(attempts)})
    return sorted(result,key=lambda x:(-x['priority'],x['course']))

def duration(task):
    """Informational effort, never an invented time budget or completion claim."""
    given=task.get('estimated_minutes');basis=task.get('estimate_basis')
    if type(given)==int and 1<=given<=180 and isinstance(basis,str) and basis.strip():return given,basis
    text=' '.join(str(task.get(k,'')) for k in ('title','question','body')).lower()
    if re.search(r'complete (?:c |java |python )?program|allocation.failure|implement.*function',text):return 35,'Complete paper program, edge cases and dry run'
    if re.search(r'derivative|differentiat|extrema|mean value',text):return 22,'Rule choice, algebra steps and independent check'
    if re.search(r'trace|pointer|recurs|queue|stack|postfix',text):return 15,'Paper trace, explanation and correction'
    return (8,'Concrete source/logistics check') if task.get('kind') in ('deadline','event','exam') else (18,'Read the specified material, produce the requested work and check it')

def generic_filler(task):
    return task.get('kind')=='break' or bool(re.search(r'^(take (?:a )?(?:short )?(?:reset|break)|short reset|pause and reset)\b',str(task.get('title','')),re.I))

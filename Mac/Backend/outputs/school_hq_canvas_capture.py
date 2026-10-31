#!/usr/bin/env python3
"""Validate and stage visible Canvas accessibility captures. No browser or network access.

The browser worker supplies real UI text in JSON. Only the Canvas page body is
retained; unrelated tabs, favorites and account navigation are discarded.
"""
import sys
import argparse, fcntl, json, os, re, hashlib, shutil, subprocess
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'Canvas School Source'
from school_hq_connections import courses
COURSES = courses()
EXCLUDED_COURSES = set()

def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(data, encoding='utf-8'); os.replace(temp, path)

def jsonwrite(path, value):
    atomic(path, json.dumps(value, indent=2, ensure_ascii=False)+'\n')

def request(ident):
    state = json.loads((ROOT/'School HQ App/Bridge/state.json').read_text())
    row = state.get('request') or {}
    if row.get('id') != ident or not row.get('manual') or row.get('status') not in ('queued','processing'):
        raise ValueError('No matching active manual request')
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(row['requested_at'])).total_seconds()
    if not 0 <= age <= 7200: raise ValueError('Manual request expired')
    return row

def page_body(course, kind, ax):
    lines = ax.splitlines()
    html = next((i for i,l in enumerate(lines) if 'HTML content ' in l and 'URL:' in l), None)
    if html is None: raise ValueError('No browser page evidence')
    url = lines[html].split('URL: ',1)[1].strip()
    if not url.startswith('http'): url = 'https://'+url
    parsed = urlparse(url)
    prefix = '/courses/'+COURSES[course]+'/'
    if parsed.hostname != 'webcourses.ucf.edu' or not parsed.path.startswith(prefix):
        raise ValueError('Wrong course or domain; preserve previous snapshot')
    section = 'assignments' if kind=='detail' else kind
    if not parsed.path[len(prefix):].startswith(section): raise ValueError('Wrong Canvas section')
    end = next((i for i in range(html+1,len(lines)) if 'Description: Tab bar' in lines[i] or 'Description: Favorites bar' in lines[i] or re.match(r'\s*\d+ toolbar',lines[i])),len(lines))
    body = lines[html+1:end]
    # Skip global navigation and the course sidebar, which appear before main content.
    if kind=='grades':
        start = next((i for i,l in enumerate(body) if re.search(r'heading Grades for ',l)), None)
    elif kind=='assignments':
        start = next((i for i,l in enumerate(body) if re.search(r'heading (?:Value: \d+, )?Assignments\b|heading Assignments',l)), None)
        if start is None:
            start = next((i for i,l in enumerate(body) if 'Search for Assignment' in l or 'Search assignments' in l),None)
    elif kind=='files':
        start = next((i for i,l in enumerate(body) if 'heading Files' in l or 'Search for files' in l or 'Search files' in l),None)
    else:
        nav = next((i for i,l in enumerate(body) if 'container Courses Navigation Menu' in l),None)
        start = next((i for i,l in enumerate(body) if (nav is None or i>nav) and ' heading ' in l),None)
    if start is None: raise ValueError('Main content is not loaded or recognized; do not overwrite')
    body = '\n'.join(body[start:])
    if re.search(r'heading (?:Log In|Sign in)|Access Denied|You are not authorized',body,re.I):
        raise ValueError('Login or unavailable page')
    return url, body

def entries(body, role):
    """Read AX nodes with continuation text, preserving row and cell boundaries."""
    nodes=[];current=None
    for line in body.splitlines():
        m = re.match(r'^(\s*)(\d+) ([^\n]*)',line)
        if m:
            if current: nodes.append(current)
            current={'indent':len(m[1]),'text':m[3]}
        elif current: current['text']+='\n'+line
    if current:nodes.append(current)
    return nodes

def cell_text(text):
    text = re.sub(r'^cell(?: \([^)]*\))*\s*','',text)
    if 'Value: ' in text: text=text.split('Value: ',1)[1]
    return text.strip()

def parse_grades(body, url, captured):
    nodes=entries(body,'row'); rows=[]; row=None
    for n in nodes:
        if n['text'].startswith('row'):
            if row: rows.append(row)
            row={'caption':n['text'],'cells':[],'indent':n['indent']}
        elif row and n['text'].startswith('cell') and n['indent']>row['indent']:
            row['cells'].append(cell_text(n['text']))
    if row:rows.append(row)
    assignments=[];groups=[];total=None
    for row in rows:
        cells=row['cells']
        if len(cells)>=7:
            if '\n' in cells[0]:
                name,group=cells[0].rsplit('\n',1)
                assignments.append({'name':name,'group':group,'due':cells[1],'submitted':cells[2],'status':cells[3],
                    'score_displayed':cells[4] or 'unknown','dropped':'dropped' in row['caption'].lower() or any('dropped' in c.lower() for c in cells)})
            elif cells[0]=='Total':total=cells[4]
        elif len(cells)==2 and cells[1].endswith('%'):groups.append({'name':cells[0],'weight':cells[1]})
    display=re.search(r'\bTotal: ([^\n]+)',body)
    if display:total=display[1].strip()
    if not assignments or not total:raise ValueError('Grade table incomplete: assignment rows and displayed total required')
    graded = re.search(r'checkbox Calculate based only on graded assignments, Value: ([01])',body)
    return {'source':url,'captured_utc':captured,'total_displayed':total,'based_only_on_graded_assignments':bool(int(graded[1])) if graded else None,
        'assignments':assignments,'weights':groups}

def clean(body):
    return re.sub(r'(?m)^\s*\d+ ', '',body).strip()+'\n'

def parse_files(body):
    if 'Loading data' in body:raise ValueError('Files are still loading')
    if not re.search(r'\b\d+-\d+ of \d+|No files|This folder is empty|No items',body,re.I):
        raise ValueError('File table has no loaded completion/count evidence')
    nodes=entries(body,'row');rows=[];row=None
    for n in nodes:
        if n['text'].startswith('row'):
            if row:rows.append(row)
            row={'caption':n['text'],'cells':[],'indent':n['indent'],'folder':False}
        elif row and n['text'].startswith('cell') and n['indent']>row['indent']:
            row['folder'] = row['folder'] or 'Description: Folder' in n['text']
            row['cells'].append(cell_text(n['text']))
    if row:rows.append(row)
    return [{'name':r['cells'][1],'folder':r['folder'],'created':r['cells'][2],'modified':r['cells'][3],'size':r['cells'][5]}
        for r in rows if len(r['cells'])>=8]

def capture(payload):
    ident=payload['request_id'];request(ident)
    course=payload['course'];kind=payload['kind']
    if course not in COURSES or kind not in ('grades','assignments','files','detail'):raise ValueError('Unsupported capture')
    captured=payload['captured_utc'];stamp=datetime.fromisoformat(captured.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('Capture timestamp must include timezone')
    req=request(ident)
    if stamp<datetime.fromisoformat(req['requested_at']) or stamp>datetime.now(timezone.utc):raise ValueError('Capture does not belong to this request')
    if 'dom' in payload:
        dom=payload['dom'];url=payload['url'];u=urlparse(url)
        prefix='/courses/'+COURSES[course]+'/'
        section='assignments' if kind=='detail' else kind
        if u.hostname!='webcourses.ucf.edu' or not u.path.startswith(prefix+section):raise ValueError('Wrong visible course URL')
        body=dom['body']
        if not body.strip() or 'Loading data' in body:raise ValueError('Page is incomplete')
        parsed=dom.get('grades') if kind=='grades' else None
        files=dom.get('files') if kind=='files' else None
        if kind=='grades':
            if not parsed or not parsed.get('assignments') or not parsed.get('total_displayed'):raise ValueError('Incomplete grade capture')
            for item in parsed['assignments']:
                if not item.get('name') or not all(k in item for k in ('due','submitted','status','score_displayed','group')):raise ValueError('Incomplete grade row')
            parsed.update(source=url,captured_utc=captured)
        if kind=='files':
            count=re.search(r'(\d+)-(\d+) of (\d+)',body)
            if files is None or not count or len(files)!=int(count[2])-int(count[1])+1:raise ValueError('Incomplete file table/count')
    else:
        url,body=page_body(course,kind,payload['ax'])
        parsed=parse_grades(body,url,captured) if kind=='grades' else None
        files=parse_files(body) if kind=='files' else None
    staging=SOURCE/'.checks'/ident
    key=course+'-'+kind
    if kind in ('files','detail'):key+='-'+re.sub(r'[^a-zA-Z0-9]','_',urlparse(url).path[len('/courses/'+COURSES[course]+'/'):]+urlparse(url).query)+'-'+str(payload.get('page',1))
    record={'course':course,'kind':kind,'source':url,'captured_utc':captured,'body':(body.strip()+'\n' if 'dom' in payload else clean(body)),'parsed':parsed,
        'files':files,'folder_path':payload.get('folder_path',''),'page':payload.get('page',1),
        'links':payload.get('dom',{}).get('links',[]),
        'has_next':bool(payload.get('dom',{}).get('has_next',bool(re.search(r'button Next Page',body)))) if kind=='files' else False}
    jsonwrite(staging/(key+'.json'),record)
    return {'saved':str(staging/(key+'.json')),'rows':len(parsed['assignments']) if parsed else None,'source':url}

def audit(ident):
    request(ident);staging=SOURCE/'.checks'/ident
    records=[json.loads(p.read_text()) for p in staging.glob('*.json') if p.name!='downloads.json']
    missing=[c+' '+k for c in COURSES for k in ('grades','assignments','files') if not any(r['course']==c and r['kind']==k for r in records)]
    pending=[]
    for r in records:
        if r['kind']!='files':continue
        for f in r['files']:
            if f['folder']:
                path='/'.join(filter(None,[r['folder_path'],f['name']]))
                if not any(x['course']==r['course'] and x['kind']=='files' and x['folder_path']==path for x in records):pending.append(r['course']+' / '+path)
        if r['has_next'] and not any(x['course']==r['course'] and x['kind']=='files' and x['folder_path']==r['folder_path'] and x['page']==r['page']+1 for x in records):pending.append(r['course']+' / '+r['folder_path']+' page '+str(r['page']+1))
    return {'required_pages_complete':not missing and not pending,'missing':missing,'pending_folders':pending,'captures':len(records),
        'grade_rows':sum(len(r['parsed']['assignments']) for r in records if r['parsed'])}

def normalized_date(value, captured):
    day=datetime.fromisoformat(captured.replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date()
    if value in ('Today','Yesterday'):return (day-timedelta(days=value=='Yesterday')).isoformat()
    weekdays=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    if value in weekdays:return (day-timedelta(days=(day.weekday()-weekdays.index(value))%7 or 7)).isoformat()
    if re.fullmatch(r'\d{1,2}:\d{2}(?:am|pm)',value):return day.isoformat()+' '+value
    try:return datetime.strptime(value,'%b %d, %Y').date().isoformat()
    except ValueError:return value

def plan(ident):
    request(ident);records=[json.loads(p.read_text()) for p in (SOURCE/'.checks'/ident).glob('*.json') if p.name!='downloads.json']
    old=json.loads((SOURCE/'file-inventory.json').read_text()) if (SOURCE/'file-inventory.json').exists() else {}
    old_files={}
    for course,folders in old.items():
        for folder in folders:
            for f in folder['files']:
                old_files[(course,f.get('source'))]=(f['size'],normalized_date(f['modified'],folder['captured_utc']))
    pending=[];all_files=[]
    allow={'.pdf','.png','.jpg','.jpeg','.docx','.pptx','.xlsx','.txt','.md','.csv','.c','.h','.java','.py','.out','.zip','.sh','.html','.gz'}
    for r in records:
        if r['kind']!='files':continue
        for f in r['files']:
            if f['folder'] or Path(f['name']).suffix.lower() not in allow:continue
            item={**f,'course':r['course'],'folder_path':r['folder_path'],'captured_utc':r['captured_utc']}
            all_files.append(item)
            candidates=[p for p in (SOURCE/r['course']/'Materials').rglob('*') if p.is_file() and ' '.join(p.name.split())==' '.join(f['name'].split()) and p.parent.relative_to(SOURCE/r['course']/'Materials').as_posix()==(r['folder_path'] or '.')]
            prior=old_files.get((r['course'],f.get('source')))
            signature=(f['size'],normalized_date(f['modified'],r['captured_utc']))
            # Initial exports completed Oct 8. Resolve later visible modifications
            # by downloading that file, never by silently treating it as unchanged.
            needs=not candidates or (prior is not None and prior!=signature) or (prior is None and signature[1]>'2026-10-08')
            if needs:pending.append(item)
    known={}
    if (SOURCE/'assignment-details.json').exists():known=json.loads((SOURCE/'assignment-details.json').read_text())
    links=[]
    for r in records:
        if r['kind']!='assignments':continue
        found=re.findall(r'link (.*?), Value: (webcourses\.ucf\.edu/courses/\d+/assignments/\d+)',r['body'])
        found += [(x['name'],'webcourses.ucf.edu'+x['source'] if x['source'].startswith('/') else x['source']) for x in r.get('links',[]) if '/assignments/' in x.get('source','')]
        for name,url in found:
            if re.search(r'\bquiz|\bexam|\bfinal|\bmid.?term',name,re.I):continue
            url=url if url.startswith('https://') else 'https://'+url
            links.append({'course':r['course'],'name':name,'source':url,'previously_captured':url in known})
    unique={x['source']:x for x in links}
    # Recheck current programming assignments, then make bounded progress on
    # missing descriptions. External/locked bodies stay explicitly unavailable.
    first=[x for x in unique.values() if x['name'] in ('P5','PA 02') or x['name'].startswith('Assignment 3') or x['name'].startswith(('3.5','3.6'))]
    missing=[x for x in unique.values() if not x['previously_captured'] and x not in first]
    detail_plan=(first+missing)[:20]
    return {'files_to_verify':pending,'eligible_files':all_files,'details_to_capture':detail_plan,'detail_backlog':len(missing),'audit':audit(ident)}

def import_downloads(payload):
    ident=payload['request_id'];request(ident);items=payload['files'];inventory=plan(ident)['eligible_files'];receipts=[]
    for entry in items:
        found=next((f for f in inventory if f['course']==entry['course'] and f['folder_path']==entry['folder_path'] and f['name']==entry['name']),None)
        if not found:raise ValueError('Download was not observed in this request\'s file inventory')
        raw_source=Path(entry['path']);source=raw_source.resolve()
        if (Path.home()/'Downloads') not in source.parents or raw_source.is_symlink():raise ValueError('Use the actual official-browser download path')
        if ' '.join(source.name.split())!=' '.join(entry['name'].split()):raise ValueError('Download filename does not match source')
        data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if source.suffix.lower()=='.pdf':
            if not data.startswith(b'%PDF-'):raise ValueError('Downloaded PDF is not a PDF')
            runtime=Path(sys.executable)
            from school_hq_pdf import document
            document(source)
        materials=SOURCE/entry['course']/'Materials'
        same=next((p for p in materials.rglob('*') if p.is_file() and ' '.join(p.name.split())==' '.join(entry['name'].split()) and hashlib.sha256(p.read_bytes()).hexdigest()==digest),None)
        target=same or materials/entry['folder_path']/entry['name']
        if materials.resolve() not in target.resolve().parents:raise ValueError('Invalid destination path')
        if not same:
            if target.exists():target=target.with_name(target.stem+' - '+digest[:16]+target.suffix)
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():shutil.copy2(source,target)
        receipts.append({**found,'local_path':str(target.relative_to(SOURCE)),'sha256':digest,'bytes':len(data)})
    path=SOURCE/'.checks'/ident/'downloads.json'
    previous=json.loads(path.read_text()) if path.exists() else []
    by_source={(x['course'],x['source']):x for x in previous+receipts}
    jsonwrite(path,list(by_source.values()))
    return {'verified_downloads':len(receipts),'receipt':str(path)}

def commit(ident):
    result=audit(ident)
    if result['missing'] or result['pending_folders']:raise ValueError('Incomplete five-course capture: '+', '.join(result['missing']+result['pending_folders']))
    records=[json.loads(p.read_text()) for p in (SOURCE/'.checks'/ident).glob('*.json') if p.name!='downloads.json']
    check_plan=plan(ident)
    receipt_path=SOURCE/'.checks'/ident/'downloads.json'
    receipts=json.loads(receipt_path.read_text()) if receipt_path.exists() else []
    unmatched=[f['name'] for f in check_plan['files_to_verify'] if not any(x['course']==f['course'] and x['source']==f['source'] for x in receipts)]
    if unmatched:raise ValueError('New/changed files still require verified downloads: '+', '.join(unmatched))
    grades={r['course']:r['parsed'] for r in records if r['kind']=='grades'}
    # All validated captures stay in the versioned check directory for recovery.
    for r in records:
        suffix=r['kind']
        if suffix in ('files','detail'):suffix+=' - '+re.sub(r'[^a-zA-Z0-9]','_',urlparse(r['source']).path+urlparse(r['source']).query)+' - '+str(r['page'])
        atomic(SOURCE/(r['course']+' - '+suffix+'.txt'),f"Source: {r['source']}\nCaptured UTC: {r['captured_utc']}\n\n"+r['body'])
        if r['parsed']:
            g=r['parsed'];lines=[f"# {r['course']} grades",f"Source: {r['source']}",f"Captured UTC: {r['captured_utc']}",f"Total displayed: {g['total_displayed']}",'','| Assignment | Group | Due | Submitted | Status | Score |','|---|---|---|---|---|---|']
            for a in g['assignments']:lines.append('| '+' | '.join(str(a[k]).replace('|','\\|').replace('\n',' ') for k in ('name','group','due','submitted','status','score_displayed'))+' |')
            atomic(SOURCE/(r['course']+' - grades.md'),'\n'.join(lines)+'\n')
    jsonwrite(SOURCE/'gradebooks.json',grades)
    overview=['# Current student-visible grades','Captured UTC: '+max(g['captured_utc'] for g in grades.values()),'','| Course | Displayed total | Rows |','|---|---|---|']
    for c,g in grades.items():overview.append('| '+c+' | '+g['total_displayed']+' | '+str(len(g['assignments']))+' |')
    overview.extend(['','Totals are the values Canvas displays; unknown/unposted scores are not zeros. External and hidden grades remain outside this collection.'])
    atomic(SOURCE/'Grade overview.md','\n'.join(overview)+'\n')
    prior_inventory=json.loads((SOURCE/'file-inventory.json').read_text()) if (SOURCE/'file-inventory.json').exists() else {}
    previous_paths={(c,f.get('source')):f.get('local_path') for c,folders in prior_inventory.items() for folder in folders for f in folder['files']}
    inventory={}
    for c in COURSES:
        folders=[];pointers=[]
        for r in records:
            if r['course']!=c or r['kind']!='files':continue
            for f in r['files']:
                if f['folder']:continue
                receipt=next((x for x in receipts if x['course']==c and x['source']==f.get('source')),None)
                local=receipt['local_path'] if receipt else previous_paths.get((c,f.get('source')))
                if not local:
                    materials=SOURCE/c/'Materials'
                    candidates=[p for p in materials.rglob('*') if p.is_file() and ' '.join(p.name.split())==' '.join(f['name'].split()) and p.parent.relative_to(materials).as_posix()==(r['folder_path'] or '.')]
                    if len(candidates)==1:local=str(candidates[0].relative_to(SOURCE))
                if local:
                    f['local_path']=local;pointers.append(local)
            folders.append({'folder_path':r['folder_path'],'source':r['source'],'captured_utc':r['captured_utc'],'files':r['files']})
        inventory[c]=folders
        atomic(SOURCE/(c+' - current materials.txt'),'Captured UTC: '+max(r['captured_utc'] for r in records if r['course']==c)+'\nCurrent copied course files, matched to the visible inventory:\n'+'\n'.join(sorted(set(pointers)))+'\n\nLecture media, hidden/locked/external items and complete assignment-only attachments are outside this list.\n')
    jsonwrite(SOURCE/'file-inventory.json',inventory)
    details=json.loads((SOURCE/'assignment-details.json').read_text()) if (SOURCE/'assignment-details.json').exists() else {}
    for r in records:
        if r['kind']=='detail':details[r['source']]={'course':r['course'],'captured_utc':r['captured_utc'],'source':r['source']}
    jsonwrite(SOURCE/'assignment-details.json',details)
    for c in COURSES:
        listing=next(r for r in records if r['course']==c and r['kind']=='assignments')
        links=re.findall(r'link (.*?), Value: (webcourses\.ucf\.edu/courses/\d+/assignments/\d+)',listing['body'])
        links += [(x['name'],'webcourses.ucf.edu'+x['source'] if x['source'].startswith('/') else x['source']) for x in listing.get('links',[]) if '/assignments/' in x.get('source','')]
        missing=[name for name,url in links if ('https://'+url if not url.startswith('https://') else url) not in details and not re.search(r'\bquiz|\bexam|\bfinal|\bmid.?term',name,re.I)]
        coverage=['Captured UTC: '+listing['captured_utc'],'Current grades and assignment listing checked. Accessible file-folder pagination audited.','Descriptions not yet captured: '+str(len(missing)),*missing,'External Hawkes/Gradescope bodies, hidden/unposted grades, locked files, complete assignment-only attachments and email attachments remain incomplete.']
        atomic(SOURCE/(c+' - collection coverage.txt'),'\n'.join(coverage)+'\n')
    result['committed_at']=datetime.now(timezone.utc).isoformat();result['request_id']=ident
    jsonwrite(SOURCE/'collection-check.json',result)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('capture','audit','plan','import-downloads','commit'));p.add_argument('--input',help='JSON capture file, or - for stdin');p.add_argument('--request-id');a=p.parse_args()
    SOURCE.mkdir(parents=True,exist_ok=True)
    with (SOURCE/'.capture.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if a.action in ('capture','import-downloads'):
            import sys
            payload=json.loads(sys.stdin.read() if a.input=='-' else Path(a.input).read_text())
            result=import_downloads(payload) if a.action=='import-downloads' else [capture(item) for item in payload] if isinstance(payload,list) else capture(payload)
        else:result=audit(a.request_id) if a.action=='audit' else plan(a.request_id) if a.action=='plan' else commit(a.request_id)
        print(json.dumps(result))

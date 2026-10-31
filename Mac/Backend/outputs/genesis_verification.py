"""Validate bounded, request-specific source receipts. No network or source-cache reads.

Receipts document checks actually performed by the connected collector. They are
not cryptographic remote attestations. A mounted Drive copy is never readback.
"""
import hashlib, json
from pathlib import Path
from datetime import datetime, timezone


def timestamp(value):
    try:
        if not isinstance(value,str):raise ValueError()
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result
    except (ValueError,TypeError): raise ValueError('Receipt timestamp must include a timezone')

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def loaded_list(row,kind):
    """Reject the real Canvas toolbar-only shell seen during acceptance testing."""
    body=row.get('body','').lower();links=row.get('links',[])
    if kind=='announcements':return any('/discussion_topics/' in str(x.get('source','')) for x in links) or 'no announcements' in body or 'there are no announcements' in body
    if kind=='assignments':return any('/assignments/' in str(x.get('source','')) for x in links) or 'no assignments' in body
    if kind=='files':return any(len(x.get('cells',[]))>=4 for x in row.get('files',[]) or []) or any(x in body for x in ('no files','this folder is empty','0 files'))
    return True

def validate(receipt, request, source, root, current=None):
    if receipt.get('schema')==2:return validate_local(receipt,request,source,root,current)
    raise ValueError('Legacy remote receipts cannot establish current readiness. Run a new Sync in Genesis.')

def validate_local(receipt,request,source,root,current=None):
    root=Path(root).resolve();current=current or datetime.now(timezone.utc)
    from genesis_source_policy import policy_file as resolve_policy,required_sources
    policy_file=resolve_policy(root,request.get('policy_id'));policy=json.loads(policy_file.read_text())
    if (receipt.get('policy_id')!=request.get('policy_id') or policy.get('id')!=request.get('policy_id')
        or source not in required_sources(request)
        or digest(policy_file)!=request.get('policy_sha256') or policy.get('required_sources')!=required_sources(request)
        or policy.get('remote_publication_required') is not False or policy.get('consumer')!='app_owned_local_worker_and_local_files'):
        raise ValueError('Local-only verification requires the explicitly pinned same-request policy')
    if receipt.get('request_id')!=request['id'] or receipt.get('source')!=source or receipt.get('producer')!='genesis_local_worker':raise ValueError('Local adapter receipt mismatch')
    start=timestamp(receipt.get('started_at'));end=timestamp(receipt.get('checked_at'))
    if not timestamp(request['requested_at'])<=start<=end<=current:raise ValueError('Local receipt timestamps are stale/future')
    if receipt.get('partial') is not False or receipt.get('error') is not None or receipt.get('result') not in (('changed','unchanged','checked') if source=='canvas' else ('changed','unchanged')):raise ValueError('Incomplete/failed source cannot be current')
    files=receipt.get('snapshots',[])
    if not files or sorted(x.get('path','') for x in files)!=sorted(receipt.get('expected_artifacts',[])):raise ValueError('Complete expected-artifact enumeration required')
    roles=[]
    for f in files:
        raw=Path(f['path']);p=raw.resolve()
        if raw.is_symlink() or root not in p.parents or not p.is_file() or digest(p)!=f.get('sha256'):raise ValueError('Local adapter snapshot missing or changed')
        roles.append(f.get('role'))
    required={'canvas':[c+':'+kind for c in __import__('genesis_canvas_capture').COURSES for kind in ('grades','assignments','files','announcements')]+['gradebooks'],
              'email':['mail-check','mail-index'],'gmail':['gmail-check','gmail-state'],'remarkable':['notes-index','cache-index','notes-check']}[source]
    if any(role not in roles for role in required):raise ValueError('Required local source coverage missing')
    if not receipt.get('source_objects') or not str(receipt.get('coverage_limits','')).strip():raise ValueError('Object identity and coverage limits required')
    by_role={role:[Path(f['path']) for f in files if f['role']==role] for role in roles}
    def payload(role):
        paths=by_role.get(role,[])
        if len(paths)!=1:raise ValueError('One unambiguous source artifact required: '+role)
        return json.loads(paths[0].read_text())
    def observed(value):
        if not start<=timestamp(value)<=end:raise ValueError('Artifact was not checked during this source check')
    if source=='gmail':
        raise ValueError('Legacy Gmail collection is not enabled in this release. Configure Email in Settings.')
    elif source=='email':
        config=json.loads((root/'genesis_mail_config.json').read_text());summary=payload('mail-check');index=payload('mail-index')
        if summary.get('request_id')!=request['id'] or summary.get('configured_recipient')!=config.get('address') or summary.get('mailbox')!=config.get('inbox'):raise ValueError('Mailbox identity/request does not match configured school email')
        observed(summary.get('checked_at'));counts=summary.get('counts',{})
        if type(counts.get('cached_files_checked')) is not int or counts['cached_files_checked']<=0 or counts.get('incomplete_or_unsupported_pending')!=0:raise ValueError('Mailbox check was empty or incomplete')
        if not isinstance(index,dict) or not index or summary.get('state_sha256')!=digest(by_role['mail-index'][0]):raise ValueError('Mailbox index evidence is absent or inconsistent')
    elif source=='canvas':
        from urllib.parse import urlparse
        course_ids=dict(__import__('genesis_canvas_capture').COURSES)
        if not course_ids: raise ValueError('No classes configured; empty coverage cannot pass verification')
        book=payload('gradebooks')
        for course,cid in course_ids.items():
            for kind in ('grades','assignments','files','announcements'):
                row=payload(course+':'+kind);u=urlparse(row.get('url',''))
                if row.get('course')!=course or row.get('kind')!=kind or u.hostname!=__import__('genesis_connections').canvas_host() or not u.path.startswith('/courses/'+cid+'/') or not row.get('body','').strip() or row.get('authenticated') is not True:raise ValueError('Canvas page identity/access evidence invalid')
                observed(row.get('captured_utc'))
                if not loaded_list(row,kind):raise ValueError('Canvas '+kind+' capture is a loading shell, not a loaded list')
                if kind=='grades':
                    grade=row.get('grades',{})
                    if not grade.get('assignments') or not grade.get('total_displayed') or course not in book or book[course].get('assignments')!=grade['assignments']:raise ValueError('Canvas grade table and gradebook evidence differ')
    elif source=='remarkable':
        summary=payload('notes-check');state=payload('notes-index');index=payload('cache-index')
        if summary.get('request_id')!=request['id'] or summary.get('tablet_sync_confirmed') is not False:raise ValueError('Notes check identity or tablet freshness claim invalid')
        observed(summary.get('checked_at'))
        docs=summary.get('documents');changed=summary.get('changed')
        if not isinstance(docs,list) or not docs or not isinstance(changed,list):raise ValueError('Current render evidence required')
        witnessed=set()
        for path in by_role.get('manifest',[]):
            m=json.loads(path.read_text());uid=m.get('notebook_id');fingerprint=m.get('fingerprint')
            doc=next((x for x in docs if x.get('document_id')==uid and x.get('fingerprint')==fingerprint),None)
            if not doc or state.get(uid)!=fingerprint or index.get(uid,{}).get('fingerprint')!=fingerprint:raise ValueError('Notes fingerprint evidence differs')
            parent=path.parent;report=parent/'render-report.json';pdf=parent/'handwriting.pdf'
            if report not in by_role.get('render-report',[]) or pdf not in by_role.get('readable-pdf',[]):raise ValueError('Expected render artifacts missing')
            rendered=json.loads(report.read_text()).get('pages',[]);pages=m.get('pages',0)
            if not pages or len(rendered)!=pages or doc.get('pages')!=pages or not m.get('quality','').startswith('EXPERIMENTAL_VECTOR_') or pdf.read_bytes()[:5]!=b'%PDF-':raise ValueError('Notes render incomplete')
            for number in range(1,pages+1):
                image=parent/'rendered'/('page-%03d.png'%number)
                if image not in by_role.get('readable-page',[]) or image.read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Readable note page missing')
            if receipt.get('render_validation_version')==2:
                validations=[json.loads(p.read_text()) for p in by_role.get('render-validation',[])]
                proof=next((v for v in validations if v.get('document_id')==uid and v.get('fingerprint')==fingerprint),None)
                if not proof or proof.get('validated') is not True or proof.get('errors') or proof.get('pdf_sha256')!=digest(pdf):raise ValueError('Decoded/raster render validation absent or changed')
                if len(proof.get('pages',[]))!=pages:raise ValueError('Render validation page coverage incomplete')
                for n,v in enumerate(proof['pages'],1):
                    if v.get('png_sha256')!=digest(parent/'rendered'/('page-%03d.png'%n)):raise ValueError('Validated readable page changed')
            witnessed.add(uid)
        if witnessed!={x.get('document_id') for x in docs} or not set(changed).issubset(witnessed):raise ValueError('Changed/current notes missing complete render witnesses')
    publication=receipt.get('publication',{})
    if publication.get('required') is not False or publication.get('policy_id')!=request['policy_id'] or publication.get('status')!='not_required_local_consumer':raise ValueError('Publication exemption must match the local consumer policy')
    return {'schema':1,'source':source,'request_id':request['id'],'verified_at':end.isoformat(),'snapshot_count':len(files),'readback_ids':[],
            'local_policy_id':request['policy_id'],'remote_publication_required':False}

def load_receipt(path, request, source, root):
    root=Path(root).resolve();raw=Path(path);p=raw.resolve()
    if raw.is_symlink() or root/'Genesis App/Bridge/Receipts' not in p.parents or p.suffix!='.json':
        raise ValueError('Save receipts inside Genesis App/Bridge/Receipts')
    receipt=json.loads(p.read_text())
    verified=validate(receipt,request,source,root)
    verified.update(receipt_file=str(p),receipt_sha256=digest(p))
    return verified

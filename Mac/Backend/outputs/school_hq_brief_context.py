"""User-authored context on one manual request; never a source-ready receipt."""
import hashlib,json,re
from pathlib import Path

def attach(root,request,path):
 root=Path(root).resolve();path=Path(path)
 if path.is_symlink() or path.resolve()!=root/'School HQ App/Bridge/brief-context-draft.json':raise ValueError('Context must be the app-owned local draft')
 value=json.loads(path.read_text());text=value.get('text')
 if not isinstance(text,str) or not text.strip() or len(text)>4000:raise ValueError('Context needs 1–4000 characters')
 if value.get('appliedToRequest'):
  ident=value['appliedToRequest']
  if not isinstance(ident,str) or ident in ('.','..') or Path(ident).name!=ident:raise ValueError('Invalid previous context request ID')
  prior=root/'School HQ App/Bridge/Runs'/value['appliedToRequest']/'brief-context.json'
  if prior.exists():
   state=json.loads((root/'School HQ App/Bridge/state.json').read_text()) if (root/'School HQ App/Bridge/state.json').exists() else {}
   if (state.get('request') or {}).get('id')==value['appliedToRequest'] and state['request'].get('status')=='complete':raise ValueError('Previous brief context was consumed. Edit or clear the note before a new Sync.')
 text=text.strip();saved={'schema':1,'request_id':request['id'],'text':text,'reported_at':request['requested_at'],'authority':'user_report_not_verified_course_evidence','no_new_notes_reported':bool(re.search(r'\bno\s+new\s+(?:remarkable\s+|reMarkable\s+)?notes\b',text,re.I)),'catch_up_reported':bool(re.search(r'\b(missed|absent|catch[ -]?up)\b',text,re.I)),'limits':'User report. Does not bypass any required collection/readiness check. Catch-up tasks append to the normal plan.'}
 target=root/'School HQ App/Bridge/Runs'/request['id']/'brief-context.json';target.parent.mkdir(parents=True,exist_ok=True);raw=(json.dumps(saved,indent=2)+'\n').encode();target.write_bytes(raw);target.chmod(0o600)
 request['user_context']={'path':str(target),'sha256':hashlib.sha256(raw).hexdigest()}
 return saved

def load(root,request):
 ref=request.get('user_context')
 if not ref:return None
 path=Path(ref['path']);expected=Path(root).resolve()/'School HQ App/Bridge/Runs'/request['id']/'brief-context.json'
 if path.is_symlink() or path.resolve()!=expected or hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('Manual request context is missing or changed')
 value=json.loads(path.read_text())
 if value.get('request_id')!=request['id']:raise ValueError('Manual request context ID mismatch')
 return {**value,'sha256':ref['sha256']}

def validate(packet,root,request):
 context=load(root,request)
 additions=packet.get('catch_up_tasks',[])
 if not context:
  notes=packet.get('context_notes')
  if notes:
   path=Path(root).resolve()/'School HQ App/Bridge/Runs'/request['id']/'context-notes.json'
   if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=notes.get('sha256'):raise ValueError('Context-note snapshot missing or changed')
   saved=json.loads(path.read_text()).get('notes',[])
   if additions and not any(c.get('kind')=='missed_class' for n in saved for c in n.get('chips',[])):raise ValueError('Catch-up additions need a missed-class note')
   return ['Your notes: '+'; '.join(n['text'][:200] for n in saved)] if saved else []
  if additions:raise ValueError('Catch-up additions require this request’s user context')
  return []
 response=packet.get('context_response',{})
 if response.get('sha256')!=context['sha256'] or not isinstance(response.get('summary'),str) or not response['summary'].strip():raise ValueError('Brief must acknowledge the exact request context')
 if context['catch_up_reported'] and not additions:raise ValueError('Missed-class report needs additive catch-up tasks, including a scope-resolution step when coverage is unknown')
 return ['Your context: '+context['text'],'Context response: '+response['summary'],'Catch-up additions: '+str(len(additions))+'. Normal-plan tasks are retained. Reports do not certify attendance, cloud sync or learning mastery.']

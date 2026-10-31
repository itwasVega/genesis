#!/usr/bin/env python3
"""Optional email supplement for any IMAP provider (iCloud, Gmail, Outlook, Yahoo, others).

Read-only by construction: the mailbox is opened with EXAMINE (readonly select) and bodies are
fetched with BODY.PEEK, so nothing is marked read, moved or deleted. Only messages from Canvas
(instructure.com) and senders from the student's school are saved, as plain text, for Library search. The password is
an app password kept in the macOS Keychain (service Genesis.Mail.v1); it is never written to disk
or logs. Failures never block a sync.

CLI:  python3 genesis_mail.py test     -> {"ok": true} or {"ok": false, "detail": "..."}
      python3 genesis_mail.py collect  -> {"status": ..., "new": n, ...}
"""
import email,hashlib,imaplib,json,re,socket,subprocess,sys
from datetime import datetime,timedelta,timezone
from email.header import decode_header,make_header
from email.utils import parseaddr,parsedate_to_datetime
from html import unescape
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CONFIG=ROOT/'Genesis Study/mail.json'
OUT=ROOT/'Genesis App/Bridge/Mail'
SERVICE='Genesis.Mail.v1'
def _sender():
 # Canvas notifications plus the student's own school domain (from setup), nothing else.
 domain=__import__('genesis_connections').school_domain()
 return re.compile(r'(?:@|\.)(?:instructure\.com'+('|'+re.escape(domain) if domain else '')+r')$',re.I)
SENDER=_sender()
WINDOW_DAYS=30
MAX_NEW=150

class MailFailure(Exception):pass

def read(path,default):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError):return default

def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)

def config():
 c=read(CONFIG,None)
 if not c or not c.get('enabled') or not c.get('email') or not c.get('host'):return None
 return c

def password(c):
 r=subprocess.run(['/usr/bin/security','find-generic-password','-s',SERVICE,'-a',c['email'],'-w'],capture_output=True,text=True,timeout=15)
 if r.returncode or not r.stdout.strip():raise MailFailure('The saved app password is missing. Reconnect email in Settings.')
 return r.stdout.rstrip('\n')

def connect(c):
 try:
  m=imaplib.IMAP4_SSL(c['host'],int(c.get('port') or 993),timeout=25)
  m.login(c['email'],password(c))
  return m
 except imaplib.IMAP4.error as exc:
  text=str(exc)
  if re.search(r'auth|login|credential|password|invalid',text,re.I):
   raise MailFailure('Sign-in was refused. Use an app password from your provider, not your normal password.') from None
  raise MailFailure('The mail server refused the request.') from None
 except (socket.timeout,TimeoutError):raise MailFailure('The mail server did not answer in time.') from None
 except OSError:raise MailFailure('Could not reach '+c['host']+'. Check the server name and your connection.') from None

def header(value):
 try:return str(make_header(decode_header(value or ''))).strip()
 except Exception:return (value or '').strip()

def body_text(msg):
 plain,html=[],[]
 for part in msg.walk() if msg.is_multipart() else [msg]:
  if part.get_content_maintype()=='multipart' or part.get_filename():continue
  try:payload=part.get_payload(decode=True) or b''
  except Exception:continue
  text=payload.decode(part.get_content_charset() or 'utf-8',errors='replace')
  (plain if part.get_content_type()=='text/plain' else html if part.get_content_type()=='text/html' else []).append(text)
 if plain:text='\n'.join(plain)
 else:
  text=re.sub(r'(?is)<(script|style).*?</\1>',' ','\n'.join(html));text=re.sub(r'(?i)<br\s*/?>|</p>|</div>|</li>','\n',text)
  text=unescape(re.sub(r'<[^>]+>',' ',text))
 text=re.sub(r'[ \t]+',' ',text);text=re.sub(r'\n\s*\n\s*\n+','\n\n',text)
 return text.strip()[:20000]

def test():
 c=config()
 if not c:return {'ok':False,'detail':'No email account is connected.'}
 try:
  m=connect(c)
  try:
   typ,_=m.select('INBOX',readonly=True)
   if typ!='OK':return {'ok':False,'detail':'Signed in, but the inbox could not be opened.'}
  finally:
   try:m.logout()
   except Exception:pass
  return {'ok':True,'detail':'Connected to '+c['email']+' (read-only).'}
 except MailFailure as exc:return {'ok':False,'detail':str(exc)}

def collect():
 c=config()
 if not c:return {'status':'not_connected','new':0,'paths':[]}
 state=read(OUT/'state.json',{})
 if state.get('email')!=c['email'] or state.get('host')!=c['host']:state={}
 m=connect(c)
 paths=[]
 try:
  typ,data=m.select('INBOX',readonly=True)
  if typ!='OK':raise MailFailure('The inbox could not be opened.')
  validity=None
  try:
   typ,resp=m.response('UIDVALIDITY')
   validity=(resp or [None])[0];validity=validity.decode() if isinstance(validity,bytes) else validity
  except Exception:pass
  if validity and state.get('uidvalidity') not in (None,validity):state={}
  last=int(state.get('last_uid') or 0)
  since=(datetime.now(timezone.utc)-timedelta(days=WINDOW_DAYS)).strftime('%d-%b-%Y')
  domain=__import__('genesis_connections').school_domain()
  query='(SINCE %s OR FROM "instructure.com" FROM "%s")'%(since,domain) if domain else '(SINCE %s FROM "instructure.com")'%since
  typ,data=m.uid('search',None,query)
  if typ!='OK':raise MailFailure('The mail search failed.')
  uids=sorted(int(u) for u in (data[0] or b'').split() if int(u)>last)[-MAX_NEW:]
  for uid in uids:
   typ,parts=m.uid('fetch',str(uid),'(BODY.PEEK[])')
   raw=next((p[1] for p in parts or [] if isinstance(p,tuple) and len(p)>1),None)
   if typ!='OK' or not raw:continue
   msg=email.message_from_bytes(raw)
   sender=parseaddr(header(msg.get('From')))[1]
   if not SENDER.search(sender or ''):continue
   subject=header(msg.get('Subject'))
   try:sent=parsedate_to_datetime(msg.get('Date')).astimezone(timezone.utc).isoformat()
   except Exception:sent=''
   key=hashlib.sha256((msg.get('Message-ID') or (sender+subject+sent)).encode()).hexdigest()[:20]
   path=OUT/'messages'/key/'message.txt'
   if not path.exists():
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('From: '+sender+'\nSubject: '+subject+'\nDate: '+sent+'\n\n'+body_text(msg)+'\n')
    paths.append(str(path))
  if uids:state['last_uid']=max(uids)
 finally:
  try:m.logout()
  except Exception:pass
 checked=datetime.now(timezone.utc).isoformat()
 state.update({'email':c['email'],'host':c['host'],'uidvalidity':validity or state.get('uidvalidity'),'checked_at':checked})
 write(OUT/'state.json',state)
 return {'status':'checked','new':len(paths),'paths':paths,'checked_at':checked}

def main():
 action=sys.argv[1] if len(sys.argv)>1 else 'test'
 if action=='test':print(json.dumps(test()))
 elif action=='collect':
  try:print(json.dumps({k:v for k,v in collect().items() if k!='paths'}))
  except MailFailure as exc:print(json.dumps({'status':'failed','detail':str(exc)}));sys.exit(1)
 else:sys.exit('usage: genesis_mail.py test|collect')

if __name__=='__main__':main()

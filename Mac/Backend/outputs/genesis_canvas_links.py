"""Bounded public module-link readback, inside the existing local worker only.
No account links, cookies, recursive mirroring, execution, or private data in requests.
"""
import hashlib,json,urllib.request,urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime,timezone
class Reader(HTMLParser):
 def __init__(self):super().__init__();self.skip=0;self.parts=[]
 def handle_starttag(self,t,a):
  if t in ('script','style','noscript'):self.skip+=1
 def handle_endtag(self,t):
  if t in ('script','style','noscript'):self.skip=max(0,self.skip-1)
 def handle_data(self,d):
  if not self.skip and d.strip():self.parts.append(d.strip())
ALLOW=set(__import__('genesis_connections').read().get('public_resource_hosts',[]))   # public course sites the student added
class SafeRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,h,new):
  u=urllib.parse.urlparse(new)
  if u.scheme!='https' or u.hostname not in ALLOW:raise ValueError('Public resource redirect outside exact allowed hosts')
  return super().redirect_request(req,fp,code,msg,h,new)
def collect(response,output):
 refs={}
 for row in response['captures']:
  if row.get('kind')!='modules':continue
  for item in row.get('items',[]):
   u=item.get('external_url');parsed=urllib.parse.urlparse(u or '')
   if item.get('type')=='ExternalUrl' and parsed.scheme=='https' and parsed.hostname in ALLOW:refs[u]={'course':row['course'],'title':item.get('title'),'url':u}
 out=[];folder=Path(output);folder.mkdir(parents=True,exist_ok=True);opener=urllib.request.build_opener(SafeRedirect())
 for url,ref in refs.items():
  try:
   with opener.open(urllib.request.Request(url,headers={'User-Agent':'Genesis/0.8.1 public course reference','Accept':'text/html'}),timeout=20) as r:
    raw=r.read(2*1024*1024+1);mime=r.headers.get_content_type();status=r.status
   if len(raw)>2*1024*1024 or mime!='text/html':raise ValueError('Public linked page exceeds HTML/2MB bound')
   reader=Reader();reader.feed(raw.decode('utf-8'));text='\n'.join(reader.parts);sha=hashlib.sha256(text.encode()).hexdigest();path=folder/(sha+'.txt')
   if not path.exists():path.write_text(text)
   out.append({**ref,'status':status,'checked_at':datetime.now(timezone.utc).isoformat(),'path':str(path.resolve()),'sha256':sha,'coverage':'Linked landing-page text only; no recursive website, videos or client-generated exercise catalog collected.','text_characters':len(text)})
  except Exception as e:out.append({**ref,'status':'failed','error':str(e),'fixable':True})
 return out

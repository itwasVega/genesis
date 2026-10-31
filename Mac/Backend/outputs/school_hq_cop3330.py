"""COP3330 dual-source record. Public instructional site supplements Canvas;
never replaces a Canvas check, changes grades/deadlines or executes source code.
"""
import sys
import argparse,hashlib,json,os,re,subprocess,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime,timezone
BASE='https://www.cs.ucf.edu/courses/cop3330/fall2026/'
PREFIX='/courses/cop3330/fall2026/'
AUTHORITY={'canvas':['assigned_work','deadlines','grades','announcements','submission_status'], 'professor_site':['syllabus','instructional_material','examples','practice','exam_preparation']}
ROOT=Path(__file__).resolve().parent

def stamp():return datetime.now(timezone.utc).isoformat()
def sha(data):return hashlib.sha256(data).hexdigest()
def atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);data=json.dumps(value,ensure_ascii=False,indent=2).encode();tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_bytes(data);tmp.chmod(0o600);tmp.replace(path)
def canonical(url):
 p=urllib.parse.urlsplit(url);host=p.hostname or ''
 if p.scheme not in ('http','https') or host!='www.cs.ucf.edu' or p.username or p.password or p.port not in (None,80,443) or p.query:raise ValueError('Outside approved public course origin')
 path=urllib.parse.unquote(p.path)
 if not (path.startswith(PREFIX) or path.startswith('/~dmarino/ucf/cop3330/') or path.startswith('/~dmarino/ucf/introjava/')) or '..' in path.split('/') or '\\' in path:raise ValueError('Outside approved course path')
 return urllib.parse.urlunsplit(('https',host,urllib.parse.quote(path,safe='/~!$&\'()*+,;=:@-._'),'', ''))
class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):return super().redirect_request(req,fp,code,msg,headers,canonical(newurl))
class Catalog(HTMLParser):
 """Table-aware links; comments/scripts and unpublished commented rows ignored."""
 def __init__(self,url):super().__init__(convert_charrefs=True);self.url=url;self.base=url;self.links=[];self.row=None;self.cell=None;self.anchor=None;self.skip=0;self.text=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag in ('script','style'):self.skip+=1
  if self.skip:return
  if tag=='base' and a.get('href'):
   try:self.base=canonical(urllib.parse.urljoin(self.url,a['href']))
   except ValueError:pass
  if tag=='tr':self.row=[]
  if tag in ('td','th') and self.row is not None:self.cell={'text':[],'links':[]};self.row.append(self.cell)
  if tag=='a' and a.get('href'):self.anchor={'url':urllib.parse.urljoin(self.base,a['href']),'title':[]}
 def handle_data(self,data):
  if self.skip:return
  self.text.append(data)
  if self.cell is not None:self.cell['text'].append(data)
  if self.anchor is not None:self.anchor['title'].append(data)
 def handle_endtag(self,tag):
  if tag in ('script','style') and self.skip:self.skip-=1;return
  if self.skip:return
  if tag=='a' and self.anchor is not None:
   row={'url':self.anchor['url'],'title':' '.join(''.join(self.anchor['title']).split()),'catalog_url':self.url}
   self.links.append(row)
   if self.cell is not None:self.cell['links'].append(row)
   self.anchor=None
  if tag in ('td','th'):self.cell=None
  if tag=='tr' and self.row:
   cells=[' '.join(''.join(c['text']).split()) for c in self.row]
   headings=['week','topic','lecture_notes','java_examples','in_class_notes','in_class_code','weekly_practice'] if '/notes' in self.url else ['exam','review_notes','sample_questions','sample_solutions','exam_questions','exam_solutions','exam_code']
   for i,c in enumerate(self.row):
    for link in c['links']:
     link.update(category=headings[i] if i<len(headings) else 'reference',week=cells[0] if cells else '',topic=cells[1] if '/notes' in self.url and len(cells)>1 else 'Exam '+cells[0])
   self.row=None

def object_write(folder,data,suffix):
 path=folder/'Objects'/(sha(data)+suffix)
 if path.exists():
  if sha(path.read_bytes())!=sha(data):raise ValueError('Stored public material hash mismatch')
 else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o600)
 return path.resolve()

def fetch(url,folder,cache,opener=None):
 url=canonical(url);previous=cache.get(url,{});headers={'User-Agent':'SchoolHQ/0.8 (personal course material reader)'}
 valid=previous.get('path') and Path(previous['path']).is_file() and sha(Path(previous['path']).read_bytes())==previous.get('sha256')
 if valid:
  if previous.get('etag'):headers['If-None-Match']=previous['etag']
  if previous.get('last_modified'):headers['If-Modified-Since']=previous['last_modified']
 request=urllib.request.Request(url,headers=headers);opener=opener or urllib.request.build_opener(RestrictedRedirect())
 try:
  with opener.open(request,timeout=15) as response:
   if canonical(response.url)!=url and not canonical(response.url).rstrip('/')==url.rstrip('/'):raise ValueError('Unexpected material redirect')
   data=response.read(12_000_001)
   if len(data)>12_000_000:raise ValueError('Material exceeds 12 MB limit')
   suffix=Path(urllib.parse.urlsplit(url).path).suffix.lower() or '.html'
   if suffix=='.pdf' and not data.startswith(b'%PDF-'):raise ValueError('PDF link returned a non-PDF page')
   if suffix=='.java' and (b'<html' in data[:300].lower() or b'\0' in data):raise ValueError('Java reference returned an invalid file')
   path=object_write(folder,data,suffix);value={'url':url,'path':str(path),'sha256':sha(data),'bytes':len(data),'etag':response.headers.get('ETag'),'last_modified':response.headers.get('Last-Modified'),'checked_at':stamp(),'retrieval':'downloaded' if not valid or previous.get('sha256')!=sha(data) else 'content_unchanged'}
 except urllib.error.HTTPError as e:
  if e.code==304 and valid:value={**previous,'checked_at':stamp(),'retrieval':'not_modified'}
  else:raise ValueError('Public course server returned HTTP '+str(e.code)) from None
 cache[url]=value;return value

def extract(row,folder):
 path=Path(row['path']);suffix=path.suffix.lower()
 if suffix=='.pdf':
  pages_path=folder/'Objects'/(row['sha256']+'-pages.json')
  if not pages_path.exists():
   p=subprocess.run([str(Path(sys.executable)),str(ROOT/'school_hq_professor_pdf.py'),str(path)],capture_output=True,text=True,timeout=25)
   if p.returncode:raise ValueError('PDF extraction failed; original retained, not marked instruction-readable')
   value=json.loads(p.stdout);atomic(pages_path,value)
  value=json.loads(pages_path.read_text())
  return {'page_count':value['page_count'],'pages_path':str(pages_path.resolve()),'pages_sha256':sha(pages_path.read_bytes()),'text_available':value['text_available']}
 if suffix=='.java':
  try:
   source_text=path.read_text(encoding='utf-8');return {'text_path':str(path),'text_sha256':row['sha256'],'text_available':bool(source_text.strip())}
  except UnicodeDecodeError:pass
 data=path.read_text(encoding='utf-8',errors='replace')
 if suffix in ('.html','.htm'):parser=Catalog(row['url']);parser.feed(data);data=' '.join(' '.join(parser.text).split())
 text=object_write(folder,data.encode(),'.txt');return {'text_path':str(text),'text_sha256':sha(text.read_bytes()),'text_available':bool(data.strip())}

def canvas_evidence(receipt_path,expected_request=None):
 if not receipt_path:return {'status':'unavailable','detail':'No verified Canvas receipt supplied','references':[]},[]
 receipt_path=Path(receipt_path);r=json.loads(receipt_path.read_text())
 if r.get('schema')!=2 or r.get('source')!='canvas' or r.get('partial') or r.get('error') or (expected_request and r.get('request_id')!=expected_request):raise ValueError('Canvas receipt cannot support the unified course record')
 refs=[];rows=[]
 for item in r.get('snapshots',[]):
  if not item.get('role','').startswith('COP3330:'):continue
  p=Path(item['path'])
  if not p.is_file() or sha(p.read_bytes())!=item['sha256']:raise ValueError('COP3330 Canvas artifact failed hash verification')
  row=json.loads(p.read_text())
  parsed=urllib.parse.urlsplit(row.get('url',''))
  if row.get('authenticated') is not True or parsed.hostname!='webcourses.ucf.edu' or not parsed.path.startswith('/courses/'+__import__('school_hq_connections').courses().get('COP3330','unconfigured')+'/'):raise ValueError('COP3330 Canvas origin/authentication mismatch')
  refs.append(item)
  if row.get('kind') in ('announcements','announcement-detail'):rows.append({**row,'snapshot_path':str(p),'snapshot_sha256':item['sha256']})
 required={'COP3330:'+kind for kind in ('grades','assignments','files','announcements')}
 if not required<={r['role'] for r in refs}:raise ValueError('Existing Canvas COP3330 coverage is incomplete; website cannot substitute for it')
 return {'status':'verified_snapshot','request_id':r['request_id'],'checked_at':r['checked_at'],'receipt_path':str(receipt_path.resolve()),'receipt_sha256':sha(receipt_path.read_bytes()),'references':refs,'authority':AUTHORITY['canvas'],'detail':'Exact hash-verified Canvas capture; dates/coverage retained, not made fresh by the website check.'},rows

def announcement_links(rows):
 found=[]
 for row in rows:
  body=row.get('body','')
  for match in re.finditer(r'https?://www\.cs\.ucf\.edu/[^\s<>"\]]+',body):
   raw=match.group(0).rstrip('.,);')
   try:url=canonical(raw)
   except ValueError:continue
   found.append({'url':url,'canvas_url':row.get('url'),'snapshot_path':row['snapshot_path'],'snapshot_sha256':row['snapshot_sha256'],'captured_at':row['captured_utc'],'excerpt':body[max(0,match.start()-160):min(len(body),match.end()+160)],'match':'direct_url','exam_scope_confirmed':False})
 return found

def cross_references(rows,materials):
 direct=announcement_links(rows);by_url={m['url']:m for m in materials};out=[]
 for item in direct:
  m=by_url.get(item['url']);out.append({**item,'material_id':m['id'] if m else None,'material_status':m['status'] if m else 'not_collected','match_verified':m is not None and m['status']=='verified'})
 # Cautious topic pointers are never exact matches or asserted exam scope.
 topics=['inheritance','polymorphism','interfaces','comparable','abstract classes','overloading','arrays','static methods']
 for row in rows:
  for topic in topics:
   hit=re.search(r'\b'+re.escape(topic)+r'\b',row.get('body',''),re.I)
   if not hit:continue
   candidates=[m['id'] for m in materials if topic in (m.get('topic','')+' '+m['title']).lower() and m['status']=='verified'][:12]
   if candidates:out.append({'match':'topic_suggestion','topic':topic,'candidate_ids':candidates,'match_verified':False,'exam_scope_confirmed':False,'canvas_url':row.get('url'),'snapshot_path':row['snapshot_path'],'snapshot_sha256':row['snapshot_sha256'],'captured_at':row['captured_utc'],'excerpt':row['body'][max(0,hit.start()-100):hit.end()+180],'limitation':'Topic mention only; verify exact announcement wording, exclusions and intended materials. No scope inference.'})
 return out

def instructional_sequence(materials):
    groups={}
    for material in materials:
        for context in [material,*material.get('aliases',[])]:
            week=context.get('week');topic=context.get('topic')
            if not week or not topic or '/notes' not in context.get('catalog_url',''):continue
            key=(week,topic);members=groups.setdefault(key,[])
            if material['id'] not in members:members.append(material['id'])
    # Dates from the professor's table label teaching order, never official deadlines.
    def order(key):
        numbers=re.findall(r'\d+',key[0]);return tuple(map(int,numbers[:2])) if numbers else (99,99)
    return [{'week':key[0],'topic':key[1],'material_ids':groups[key],
             'relation':'Earlier teaching rows are context for later rows; actual prerequisites must be verified from the material.',
             'deadline_authority':False} for key in sorted(groups,key=order)]

def coaching_context(record,record_path):
    materials=record['professor_site']['materials'];by_id={m['id']:m for m in materials}
    referenced={m['material_id'] for m in record['cross_references'] if m.get('match_verified')}
    today=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date()
    sequence=instructional_sequence(materials)
    def week_start(group):
        found=re.match(r'(\d+)/(\d+)',group['week'])
        if not found:return None
        try:return today.replace(month=int(found[1]),day=int(found[2]))
        except ValueError:return None
    recent=[g for g in sequence if week_start(g) and week_start(g)<=today][-2:]
    selected=referenced|{ident for g in recent for ident in g['material_ids']}
    # Review notes explain scope; sample/exam solutions remain separately identified,
    # available for private rubric verification, never leaked into target questions.
    selected|={m['id'] for m in materials if m.get('category') in ('syllabus','review_notes','sample_questions')}
    fields=('id','title','url','path','sha256','category','topic','week','page_count','pages_path','pages_sha256','text_path','text_sha256','text_available','checked_at','status')
    return {'schema':1,'course':'COP3330','request_id':record['request_id'],'checked_at':record['checked_at'],'authority':record['authority'],'canvas':record['canvas'],
            'professor_status':record['professor_site']['status'],'full_record':{'path':str(Path(record_path).resolve()),'sha256':sha(Path(record_path).read_bytes())},
            'cross_references':[m for m in record['cross_references'] if m.get('match_verified') or m.get('match')=='topic_suggestion'],
            'recent_teaching_sequence':recent,'selected_instructional_materials':[{k:m[k] for k in fields if k in m} for m in materials if m['id'] in selected],
            'coverage_limits':record['coverage_limits'],'selection_limits':'Compact reading pointers only, not full exam scope or a change to mastery/priority rules. Full verified catalog remains available by hash. No-text PDFs require actual visual reading.'}

def collect(bridge,request_id,receipt_path=None,guard=lambda:None,max_materials=280):
 start=time.monotonic();bridge=Path(bridge);folder=bridge/'Courses/COP3330/Professor';folder.mkdir(parents=True,exist_ok=True,mode=0o700);cache_path=folder/'http-cache.json';cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
 canvas,announcements=canvas_evidence(receipt_path,request_id if receipt_path and (bridge/'Runs'/request_id).exists() else None)
 catalogs=[];candidates={};failures=[]
 for url in [BASE,BASE+'notes/',BASE+'exam/']:
  guard()
  try:
   row=fetch(url,folder,cache);catalogs.append(row);parser=Catalog(url);parser.feed(Path(row['path']).read_text(errors='replace'))
   for link in parser.links:
    try:target=canonical(link['url'])
    except ValueError:continue
    ext=Path(urllib.parse.urlsplit(target).path).suffix.lower()
    if ext not in ('.pdf','.java','.txt','.html','.htm'):continue
    if '/prog/' in target or '/programs/' in target:continue
    value={**link,'url':target,'category':link.get('category','syllabus' if 'syllabus' in link['title'].lower() else 'reference')}
    existing=candidates.get(target)
    if existing:existing.setdefault('aliases',[]).append({k:value.get(k) for k in ('title','topic','week','category','catalog_url')})
    else:candidates[target]=value
  except Exception as e:failures.append({'url':url,'error':str(e)[:200]})
 for item in announcement_links(announcements):
  if '/prog/' not in item['url'] and Path(urllib.parse.urlsplit(item['url']).path).suffix.lower() in ('.pdf','.java','.txt'):
   candidates.setdefault(item['url'],{'url':item['url'],'title':urllib.parse.unquote(Path(urllib.parse.urlsplit(item['url']).path).name),'category':'announcement_reference','catalog_url':item['canvas_url']})
 direct={r['url'] for r in announcement_links(announcements)}
 ordered=sorted(candidates.values(),key=lambda m:(0 if m['url'] in direct else 1 if m['category']=='syllabus' else 2 if '/exam/' in m['url'] else 3,m['url']))
 materials=[]
 for i,candidate in enumerate(ordered):
  guard();material={**candidate,'id':sha(candidate['url'].encode())[:24],'status':'pending','authority':'instructional_reference','deadline_authority':False}
  if i>=max_materials:material['detail']='Bounded run material limit; not downloaded'
  else:
   try:
    row=fetch(candidate['url'],folder,cache);material.update(row,**extract(row,folder),status='verified');atomic(cache_path,cache)
   except Exception as e:material.update(status='failed',detail=str(e)[:220]);failures.append({'url':candidate['url'],'error':str(e)[:200]})
  materials.append(material)
 atomic(cache_path,cache)
 pending=[m for m in materials if m['status']!='verified'];result={'schema':1,'course':'COP3330','request_id':request_id,'checked_at':stamp(),'authority':AUTHORITY,'canvas':canvas,'professor_site':{'url':BASE,'status':'checked' if len(catalogs)==3 and not pending and not failures else 'partial' if catalogs else 'failed','catalogs':catalogs,'discovered':len(materials),'verified_materials':sum(m['status']=='verified' for m in materials),'pending':len(pending),'failures':failures,'materials':materials},'cross_references':cross_references(announcements,materials),'instructional_sequence':instructional_sequence(materials),'coverage_limits':['Eligible linked PDF, Java, HTML and text files only; archives, video and directory-only examples are not recursively collected. No downloaded code or current graded assignment solutions are executed or assessed.','Website schedule is tentative reference; official assigned work, deadlines, grades, submissions and announcements remain Canvas authority.','A direct announcement link verifies a resource pointer, not complete exam scope or learner mastery.'],'elapsed_seconds':round(time.monotonic()-start,3)}
 run=bridge/'Runs'/request_id/'COP3330-course-record.json'
 last_good=bridge/'Courses/COP3330/last-good.json'
 if result['professor_site']['status']=='checked':atomic(last_good,result)
 elif last_good.exists():result['last_good_record']={'path':str(last_good.resolve()),'sha256':sha(last_good.read_bytes()),'meaning':'Previous verified website snapshot; not current for this request.'}
 atomic(run,result);atomic(bridge/'Courses/COP3330/current.json',result)
 atomic(run.with_name('COP3330-coaching-context.json'),coaching_context(result,run))
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--request-id',required=True);p.add_argument('--canvas-receipt');p.add_argument('--max-materials',type=int,default=280);a=p.parse_args();r=collect(ROOT/'School HQ App/Bridge',a.request_id,a.canvas_receipt,max_materials=a.max_materials);print(json.dumps({'status':r['professor_site']['status'],'discovered':r['professor_site']['discovered'],'verified':r['professor_site']['verified_materials'],'pending':r['professor_site']['pending'],'cross_references':len(r['cross_references']),'seconds':r['elapsed_seconds']}))

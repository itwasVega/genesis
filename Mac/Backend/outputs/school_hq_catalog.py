#!/usr/bin/env python3
"""Problem catalog: every practice/exam PDF parsed once, cached by content hash.

* Page text for all course PDFs is extracted locally (Apple PDFKit) and cached; it powers
  page-exact teaching references ("read pp. 4-6 of LinkedLists.pdf").
* Practice, sample-exam, past-exam and exercise PDFs are segmented into individual
  problems by a fast model. Every problem must quote an anchor that really appears
  on its page; anything that does not resolve is discarded. Tasks can therefore
  only cite problems and pages that exist.
* Question sheets are paired with their answer keys so official solutions can be
  used privately for grading (never shown before an attempt).
"""
import argparse,hashlib,json,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STUDY=ROOT/'School HQ Study'
CATALOG=STUDY/'Catalog'
TEXT=CATALOG/'text'
VENV_PY=Path(sys.executable)
from school_hq_connections import courses
COURSES=tuple(courses())
QUESTION=re.compile(r'sample|practice|exercise|active.learning|extra.?questions|revision|review|ex\d+pr|exam|quiz|midterm|worksheet|\brp\d|recitation|question',re.I)
SOLUTION=re.compile(r'solution|answer|\bkey\b|key[_ ]|key\.pdf|rubric|\bsol\b',re.I)
GRADED=re.compile(r'^(?:p\d+(?:-gc)?|pa\d+|.*\bpa\d+\b|.*-pa\d+.*|.*assignment.*|.*program\s*\d.*)\.pdf$|flyer|syllabus|style.guide|recruit|symposium|cisco|latex|markdown|github|reference.cards|community.service',re.I)
ANSWER_TYPES=('code','code_trace','memory_trace','derivation','numeric','short_answer','proof','multiple_choice','table','explanation','mixed')

def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p,default=None):
 try:return json.loads(Path(p).read_text())
 except (OSError,ValueError):return {} if default is None else default
def atomic(p,value):
 from school_hq_coaching import atomic as write;write(p,value)
def norm(text):return re.sub(r'\s+',' ',re.sub(r'[^0-9a-z]+',' ',(text or '').lower())).strip()
def stem(title):return norm(re.sub(SOLUTION,' ',re.sub(r'\.pdf$','',title,flags=re.I)).replace('questions',' ').replace('qs',' '))

# ---------- page text ----------

def page_text(paths):
 """{path: [page strings]} with a content-hash cache. One subprocess for all misses."""
 TEXT.mkdir(parents=True,exist_ok=True);result={};missing={}
 for p in paths:
  try:digest=sha(p)
  except OSError:continue
  cached=TEXT/(digest+'.json')
  if cached.exists():
   value=read(cached,{})
   if 'pages' in value:result[p]=value['pages'];continue
  missing[p]=digest
 if missing:
  python=str(VENV_PY) if VENV_PY.exists() else sys.executable
  for chunk in [list(missing)[i:i+40] for i in range(0,len(missing),40)]:
   try:
    from school_hq_pdf import extract
    data=extract(chunk)
   except (OSError,RuntimeError,subprocess.SubprocessError,ValueError):data={}
   for p in chunk:
    value=data.get(p,{})
    if 'pages' in value:
     atomic(TEXT/(missing[p]+'.json'),{'sha256':missing[p],'pages':value['pages']});result[p]=value['pages']
 # Scanned and handwritten notes have no text layer. Read them with on-device OCR
 # once (Apple Vision), so lectures and exam scans can be taught from and catalogued.
 blank=[p for p,pages in result.items() if not any(len(x.strip())>=200 for x in pages) and not read(TEXT/(sha(p)+'.json'),{}).get('ocr_checked')]
 for p,pages in ocr_pages(blank).items():
  digest=sha(p);old=result.get(p,[])
  merged=[o if len(o.strip())>len(n.strip()) else n for o,n in zip(old+['']*len(pages),pages)] if pages else old
  atomic(TEXT/(digest+'.json'),{'sha256':digest,'pages':merged,'ocr':bool(pages),'ocr_checked':True});result[p]=merged
 return result

def ocr_pages(paths):
 """Apple Vision OCR, bundled so users do not need Xcode."""
 if not paths:return {}
 from school_hq_pdf import extract
 result={}
 for chunk in [paths[i:i+6] for i in range(0,len(paths),6)]:
  try:data=extract(chunk,ocr=True)
  except (OSError,RuntimeError,subprocess.SubprocessError,ValueError):continue
  result.update({p:v['pages'] for p,v in data.items() if 'pages' in v})
 return result

# ---------- documents ----------
def documents(root=ROOT):
 """Course PDFs from the verified library, newest copy per content hash."""
 lib=read(Path(root)/'School HQ App/Bridge/library.json',{}).get('assets',[])
 seen={};docs=[]
 for a in lib:
  p=a.get('path','')
  if not p.lower().endswith('.pdf') or a.get('course') not in COURSES or 'email' in a.get('kind','').lower():continue
  if not Path(p).is_file():continue
  key=a.get('sha256') or p
  if key in seen:continue
  seen[key]=1
  title=a.get('title') or Path(p).name
  role='graded' if GRADED.search(Path(p).name) or GRADED.search(title) else 'solution' if SOLUTION.search(title) else 'questions' if (QUESTION.search(title) or a.get('category') in ('sample_questions','exam_questions','weekly_practice','review_notes')) else 'teaching'
  if a.get('category') in ('sample_solutions','exam_solutions'):role='solution'
  if a.get('category') in ('lecture_notes','in_class_notes'):role='teaching'
  docs.append({'path':p,'title':title,'course':a['course'],'sha256':a.get('sha256'),'role':role,'source_url':a.get('source_url'),'category':a.get('category'),'captured_at':a.get('captured_at')})
 # Pair question sheets with answer keys in the same course by title stem.
 for d in docs:
  if d['role']!='questions':continue
  best=None
  for s in docs:
   if s['role']!='solution' or s['course']!=d['course']:continue
   a,b=stem(d['title']),stem(s['title'])
   if a and (a==b or (len(a)>3 and (a in b or b in a))):best=s;break
  d['solution_path']=best['path'] if best else None
 return docs

# ---------- problem extraction ----------
def extraction_prompt(doc,pages,solution_pages):
 numbered='\n\n'.join('=== PAGE %d ===\n%s'%(i+1,t[:6000]) for i,t in enumerate(pages[:30]))
 sol=('\n\nANSWER KEY (private; use only to fill has_official_solution and solution_pages):\n'+'\n\n'.join('=== KEY PAGE %d ===\n%s'%(i+1,t[:3000]) for i,t in enumerate(solution_pages[:20]))) if solution_pages else ''
 return f'''Catalog every individual problem in this {doc['course']} document so a study app can assign them precisely.
Document title: {doc['title']}
Pages below are the extracted text, numbered from 1 (PDF page index).

For each problem (or clearly separate subpart group) output:
- label: the exact identifier as printed ("Problem 4", "Q2(b)", "B. Recursion question 2"); if unnumbered, a short faithful description
- pages: the PDF page numbers it occupies (integers)
- anchor: 15-80 characters copied EXACTLY from the start of the problem text on its first page (must match the page text verbatim)
- prompt_text: the full problem statement, verbatim as far as the text allows (max 2500 chars; keep code and math)
- subparts: list of subpart labels ([] if none)
- answer_type: one of {list(ANSWER_TYPES)}
- skills: 2-5 short skill phrases a teacher would tag it with (e.g. "linked list deletion", "chain rule", "constructor chaining")
- structure: one short phrase describing the problem's form (e.g. "trace recursive calls and give output", "write complete C function from signature")
- difficulty: 1-5
- has_official_solution: true only if the answer key clearly covers it
- solution_pages: answer-key page numbers covering it ([] if none)
- needs_figure: true if the problem depends on a diagram/table not present in the text

Also output format_profile describing how this professor asks questions: question_types, command_verbs, notation, code_conventions (signatures, starter code, language), typical_subparts, answer_presentation, difficulty_notes. Base it only on these pages.

JSON shape: {{"problems":[...],"format_profile":{{...}}}}
Skip headers, instructions and point tables that are not problems. If the document has no problems, return {{"problems":[],"format_profile":{{}}}}.

DOCUMENT TEXT:
{numbered}{sol}'''

def validate_problems(value,pages,solution_pages):
 if not isinstance(value,dict) or not isinstance(value.get('problems'),list):raise ValueError('problems list required')
 normalized=[norm(p) for p in pages];kept=[];dropped=0
 for p in value['problems'][:120]:
  try:
   label=str(p['label']).strip()[:120];pg=[int(x) for x in p['pages']]
   if not label or not pg or min(pg)<1 or max(pg)>len(pages):raise ValueError('pages')
   anchor=norm(p.get('anchor',''))
   if len(anchor)<10 or anchor[:60] not in normalized[pg[0]-1]:raise ValueError('anchor')
   text=str(p.get('prompt_text','')).strip()
   words=norm(text).split()
   if len(words)<4:raise ValueError('prompt')
   body=' '.join(normalized[i-1] for i in pg)
   hits=sum(1 for w in set(words) if w in body)/max(1,len(set(words)))
   if hits<0.7:raise ValueError('prompt not verbatim')
   at=p.get('answer_type') if p.get('answer_type') in ANSWER_TYPES else 'mixed'
   sp=[int(x) for x in p.get('solution_pages',[]) if 1<=int(x)<=len(solution_pages)] if solution_pages else []
   kept.append({'label':label,'pages':sorted(set(pg)),'anchor':p['anchor'][:120],'prompt_text':text[:2500],'subparts':[str(x)[:20] for x in p.get('subparts',[])][:12],
                'answer_type':at,'skills':[str(x)[:60] for x in p.get('skills',[])][:6],'structure':str(p.get('structure',''))[:160],
                'difficulty':max(1,min(5,int(p.get('difficulty',3)))),'has_official_solution':bool(p.get('has_official_solution')) and bool(sp),'solution_pages':sp,'needs_figure':bool(p.get('needs_figure'))})
  except (KeyError,TypeError,ValueError):dropped+=1
 if value['problems'] and not kept:raise ValueError('No problem anchors matched the page text; copy anchors exactly')
 profile=value.get('format_profile') if isinstance(value.get('format_profile'),dict) else {}
 profile={str(k)[:40]:(v if isinstance(v,(str,list)) else str(v))for k,v in list(profile.items())[:10]}
 return {'problems':kept,'format_profile':profile,'dropped_unresolved':dropped}

def problem_id(doc_sha,problem):
 return doc_sha[:12]+':p'+str(problem['pages'][0])+':'+(re.sub(r'[^a-z0-9]+','-',problem['label'].lower()).strip('-')[:40] or 'item')

def build(root=ROOT,guard=None,progress=None,limit=40,client_factory=None):
 """Extract page text for all course PDFs; segment new question documents."""
 import school_hq_ai as ai
 docs=documents(root)
 texts=page_text([d['path'] for d in docs]+[d['solution_path'] for d in docs if d.get('solution_path')])
 CATALOG.mkdir(parents=True,exist_ok=True)
 todo=[]
 for d in docs:
  if d['role']!='questions' or d['path'] not in texts:continue
  digest=sha(d['path'])
  if (CATALOG/(digest+'.json')).exists():
   # Re-segment a sheet that was first catalogued before OCR could read it.
   if read(CATALOG/(digest+'.json'),{}).get('problems') or not read(TEXT/(digest+'.json'),{}).get('ocr'):continue
  todo.append((d,digest))
 # Exam-style material first, then sets with answer keys, then everything else.
 def rank(item):
  d=item[0];t=d['title']
  return (0 if re.search(r'exam|midterm|sample|ex\d+pr|quiz|revision|review',t,re.I) else 1,0 if d.get('solution_path') else 1,t)
 todo=sorted(todo,key=rank)[:limit]
 def work(item):
  d,digest=item;pages=texts[d['path']];sol=texts.get(d.get('solution_path') or '',[])
  value=ai.run_json('catalog',extraction_prompt(d,pages,sol),lambda v:validate_problems(v,pages,sol),name='catalog-'+digest[:10],timeout=600,guard=guard,client_factory=client_factory)
  for p in value['problems']:p['id']=problem_id(digest,p)
  record={'schema':1,'sha256':digest,'path':d['path'],'title':d['title'],'course':d['course'],'page_count':len(pages),'source_url':d.get('source_url'),
          'solution_path':d.get('solution_path'),'solution_sha256':sha(d['solution_path']) if d.get('solution_path') else None,'built_at':now(),'model':ai.route('catalog')[0],**value}
  atomic(CATALOG/(digest+'.json'),record);return len(value['problems'])
 results=ai.parallel(todo,work,on_done=(lambda n,t:progress(n,t)) if progress else None) if todo else []
 failed=[(i[0]['title'],str(r)[:200]) for i,r in results if isinstance(r,Exception)]
 if failed:
  # A failed document stays uncached and is retried on the next sync.
  atomic(CATALOG/'last-failures.json',{'at':now(),'failures':failed})
 return {'documents':len(docs),'new_cataloged':len(todo)-len(failed),'failed':failed}

def load_catalog(root=ROOT):
 out=[]
 for f in sorted((Path(root)/'School HQ Study/Catalog').glob('*.json')):
  if f.name in ('last-failures.json',):continue
  v=read(f,{})
  if v.get('schema')==1 and Path(v.get('path','')).is_file():out.append(v)
 return out

def teaching_pages(course,query,root=ROOT,limit=2):
 """Best-matching lecture/notes pages for a skill, scored by term overlap."""
 import math
 terms=sorted({t for t in norm(query).split() if len(t)>2 and t not in {'and','the','with','for','from','into','using','notes','note','rule','rules','part','week','lecture','example','examples','problem','problems'}})
 if not terms:return []
 pages_all=[]
 for d in documents(root):
  if d['course']!=course or d['role']!='teaching':continue
  if re.search(r'book|textbook|syllabus|reference.card|latex|markdown|github|style.guide|flyer|cisco',d['title'],re.I):continue
  cached=None
  try:cached=read(Path(root)/'School HQ Study/Catalog/text'/(sha(d['path'])+'.json'),{})
  except OSError:continue
  if len(cached.get('pages',[]))>120:continue
  for i,page in enumerate(cached.get('pages',[])):
   text=norm(page)
   if len(text)>=200:pages_all.append((d,i+1,page,' '+text+' '))
 if not pages_all:return []
 # Rare words carry the topic ("hopital"); common ones ("derivative") barely count.
 # A page must cover most of the topic's weight, so "product rule" never stands in
 # for L'Hopital's Rule just because both say "rule".
 n=len(pages_all);idf={t:math.log((n+1)/(1+sum(1 for *_,x in pages_all if t in x)))+0.05 for t in terms}
 total=sum(idf.values());need=0.6 if len(terms)<=6 else 0.35
 rows=[]
 for d,num,page,text in pages_all:
  covered=sum(idf[t] for t in terms if t in text)
  if covered<need*total:continue
  score=sum(idf[t]*min(text.count(t),6) for t in terms)+4*covered
  rows.append((score,d,num,page))
 rows.sort(key=lambda r:-r[0]);out=[];used=set()
 for score,d,page,text in rows:
  if d['path'] in used:continue
  used.add(d['path']);out.append({'doc':d,'page':page,'excerpt':text[:2500],'score':round(score,1)})
  if len(out)>=limit:break
 return out

def recent_teaching(course,root=ROOT,limit=2):
 """Newest lecture/notes documents for a course (for missed-class catch-up)."""
 docs=[d for d in documents(root) if d['course']==course and d['role']=='teaching' and not re.search(r'book|syllabus|flyer|guide',d['title'],re.I)]
 def order(d):
  t=d['title']
  m=re.search(r'(?:notes?|lecture|l|week|lec)\s*0*(\d{1,2})',t,re.I) or re.search(r'\bL(\d{1,2})\b',t)
  dm=re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s*(\d{1,2})',t,re.I)
  months=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
  if dm:return (2,months.index(dm[1][:3].lower())*40+int(dm[2]),Path(d['path']).stat().st_mtime)
  if m:return (1,int(m[1]),Path(d['path']).stat().st_mtime)
  return (0,0,Path(d['path']).stat().st_mtime)
 docs=[d for d in docs if not re.search(r'intro|syllabus|L01\b|L1intro',d['title'],re.I)]
 docs.sort(key=order,reverse=True);out=[]
 for d in docs[:limit]:
  pages=read(Path(root)/'School HQ Study/Catalog/text'/(sha(d['path'])+'.json'),{}).get('pages',[])
  page=next((i+1 for i,t in enumerate(pages) if len(norm(t))>200),1)
  out.append({'doc':d,'page':page,'excerpt':(pages[page-1] if pages else '')[:2500],'score':0})
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['build','list','text']);a=p.parse_args()
 if a.action=='text':docs=documents();print(json.dumps({'pages_cached':len(page_text([d['path'] for d in docs]))}))
 elif a.action=='build':print(json.dumps(build()))
 else:print(json.dumps([{'title':c['title'],'course':c['course'],'problems':len(c['problems'])} for c in load_catalog()],indent=1))
if __name__=='__main__':main()

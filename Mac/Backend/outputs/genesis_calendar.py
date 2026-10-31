"""Optional private Canvas ICS. Exact feed stays in Keychain, never in receipts.

Read-only bounded HTTPS; local events supplement authenticated Canvas, never
assert submission state. No models, remote publication, or calendar writes.
"""
import sys,json,hashlib,sqlite3,subprocess,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,date,time,timedelta,timezone
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).parent/'vendor/calendar'))
from icalendar import Calendar
from dateutil.rrule import rrulestr
from genesis_coaching import atomic
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent
SERVICE='Genesis.CanvasCalendar.v1';ACCOUNT='private-feed'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('Calendar redirected. Update the feed in Settings.')
def allowed_url(value):
 u=urlsplit(value)
 return u.scheme=='https' and u.hostname==__import__('genesis_connections').canvas_host() and not u.username and not u.password and u.port in (None,443) and u.path.endswith('.ics') and not u.fragment

def moment(value):
 if isinstance(value,datetime):return value if value.tzinfo else value.replace(tzinfo=__import__('genesis_connections').zone())
 if isinstance(value,date):return datetime.combine(value,time(),__import__('genesis_connections').zone())
 raise ValueError('Calendar event has no valid date')
def event_record(e,when,original):
 end=e.decoded('DTEND',None);start=e.decoded('DTSTART',None)
 duration=moment(end)-moment(start) if end and start else e.decoded('DURATION',timedelta(days=1) if isinstance(start,date) and not isinstance(start,datetime) else timedelta(0))
 if duration<timedelta(0):raise ValueError('Calendar event ends before it starts')
 summary=str(e.get('SUMMARY','Untitled event'))[:1000];url=str(e.get('URL','')).split('?')[0].split('#')[0]
 origin=__import__('genesis_connections').canvas_origin()
 if url and not (origin and url.startswith(origin+'/')):url=''
 return {'uid':str(e['UID']),'occurrence':when.isoformat(),'summary':summary,'start':when.isoformat(),'end':(when+duration).isoformat(),'all_day':not isinstance(start,datetime),'original_start':original.isoformat(),'source_timezone':str(getattr(start,'tzinfo','DATE')),'status':str(e.get('STATUS','CONFIRMED')),'last_modified':str(e.get('LAST-MODIFIED','')),'url':url,'course':next((c for c in ('COP3502C','COP3330','MAC2311C','COT3100C','CIS3360') if c in summary.replace(' ','')),None)}

def parse(data,now=None):
 if len(data)>5000000:raise ValueError('Calendar exceeds 5 MB limit')
 if b'BEGIN:VCALENDAR' not in data or b'END:VCALENDAR' not in data:raise ValueError('Not a complete iCalendar feed')
 now=now or datetime.now(timezone.utc);start=moment(now)-timedelta(days=30);end=moment(now)+timedelta(days=90)
 cal=Calendar.from_ical(data);events=cal.walk('VEVENT');records={};overrides={};masters={}
 if len(events)>2000:raise ValueError('Too many calendar components')
 for e in events:
  if e.errors:raise ValueError('Malformed calendar event')
  uid=str(e.get('UID',''))
  if not uid:raise ValueError('Calendar event missing UID')
  if e.get('RECURRENCE-ID'):
   if e['RECURRENCE-ID'].params.get('RANGE'):raise ValueError('Ranged recurrence changes need manual verification')
   key=(uid,moment(e.decoded('RECURRENCE-ID')).isoformat())
   if key in overrides and overrides[key].to_ical()!=e.to_ical():raise ValueError('Conflicting recurrence overrides')
   overrides[key]=e
  else:
   if uid in masters and masters[uid].to_ical()!=e.to_ical():raise ValueError('Conflicting duplicate calendar UID')
   masters[uid]=e
 for uid,e in masters.items():
  if str(e.get('STATUS',''))=='CANCELLED':continue
  original=moment(e.decoded('DTSTART'));occurrences={original}
  if e.get('RRULE'):
   rule=rrulestr(e['RRULE'].to_ical().decode(),dtstart=original)
   occurrences=set()
   for n,dt in enumerate(rule.xafter(start,count=1002,inc=True)):
    if dt>end:break
    if n>=1000:raise ValueError('Calendar recurrence exceeds bounded window')
    occurrences.add(dt)
  def values(name):
   prop=e.get(name,[]);prop=prop if isinstance(prop,list) else [prop]
   return {moment(v.dt) for group in prop for v in group.dts}
  occurrences |= values('RDATE');occurrences -= values('EXDATE')
  for when in occurrences:
   if not start<=when<=end:continue
   override=overrides.pop((uid,when.isoformat()),None)
   if override is not None and str(override.get('STATUS',''))=='CANCELLED':continue
   source=override if override is not None else e;actual=moment(override.decoded('DTSTART')) if override is not None else when
   record=event_record(source,actual,original);record['occurrence']=when.isoformat();records[(uid,when.isoformat())]=record
  if len(records)>1000:raise ValueError('Calendar exceeds 1,000 occurrences')
 for (uid,recurrence),e in overrides.items():
  if str(e.get('STATUS',''))!='CANCELLED':
   when=moment(e.decoded('DTSTART'))
   if start<=when<=end:records[(uid,recurrence)]=event_record(e,when,when)
 return list(sorted(records.values(),key=lambda x:(x['start'],x['uid'])))

def collect(bridge,request_id):
 bridge=Path(bridge);status={'source':'canvas_calendar','required':False,'request_id':request_id,'status':'unavailable','detail':'Not configured. Add the private feed in Settings.'}
 config=bridge/'optional-sources-config.json'
 if not config.exists() or not json.loads(config.read_text()).get('calendar_enabled'):return status
 try:
  result=subprocess.run(['/usr/bin/security','find-generic-password','-s',SERVICE,'-a',ACCOUNT,'-w'],capture_output=True,timeout=10)
  value=result.stdout.decode().strip()
  if result.returncode or not allowed_url(value):raise ValueError('Calendar Keychain entry unavailable or invalid. Reconnect in Settings.')
  cache=bridge/'Calendar';cache.mkdir(exist_ok=True);cache.chmod(0o700);meta=cache/'fetch.json';old=json.loads(meta.read_text()) if meta.exists() else {};headers={'Accept':'text/calendar'}
  for key,header in [('etag','If-None-Match'),('modified','If-Modified-Since')]:
   if old.get(key):headers[header]=old[key]
  try:
   with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(value,headers=headers),timeout=15) as response:
    raw=response.read(5000001);etag=response.headers.get('ETag');modified=response.headers.get('Last-Modified')
  except urllib.error.HTTPError as error:
   if error.code==304 and (cache/'feed.ics').exists():raw=(cache/'feed.ics').read_bytes();etag=old.get('etag');modified=old.get('modified')
   else:raise ValueError('Calendar HTTP '+str(error.code)+'. Reconnect the feed if expired.') from None
  events=parse(raw);digest=hashlib.sha256(raw).hexdigest();now=datetime.now(timezone.utc).isoformat()
  (cache/'feed.ics').write_bytes(raw);(cache/'feed.ics').chmod(0o600)
  db=sqlite3.connect(bridge/'calendar.sqlite3');db.execute('CREATE TABLE IF NOT EXISTS events(uid TEXT, occurrence TEXT, payload TEXT, retrieved_at TEXT, source_hash TEXT, PRIMARY KEY(uid,occurrence))')
  with db:
   db.execute('DELETE FROM events')
   db.executemany('INSERT INTO events VALUES(?,?,?,?,?)',[(e['uid'],e['occurrence'],json.dumps(e),now,digest) for e in events])
  db.close();(bridge/'calendar.sqlite3').chmod(0o600)
  atomic(meta,{'etag':etag,'modified':modified,'hash':digest,'retrieved_at':now})
  status.update(status='checked',checked_at=now,sha256=digest,event_count=len(events),detail='Read-only Canvas calendar checked. Limited feed window; no submission status or personal availability verified.')
 except Exception as error:
  # Never echo urllib exceptions, URL strings or arbitrary feed properties.
  detail=str(error) if isinstance(error,ValueError) and not any(c in str(error) for c in ('https:','http:')) else 'Calendar check failed. Previous events preserved; reconnect or retry.'
  status.update(status='failed',detail=detail[:250])
 return status


def match_assignment(event,assignments):
 """Conservative provenance match; authenticated Canvas remains authoritative."""
 path=urlsplit(event.get('url','')).path
 exact=[a for a in assignments if path and urlsplit(a.get('url','')).path==path]
 if len(exact)==1:return {'match':'stable_url','assignment_id':exact[0]['id'],'authority':'authenticated Canvas'}
 normalize=lambda s:' '.join(str(s).casefold().split())
 soft=[a for a in assignments if event.get('course') and a.get('course')==event['course'] and normalize(a.get('name'))==normalize(event.get('summary')) and a.get('due_date')==event.get('start','')[:10]]
 if len(soft)==1:return {'match':'unique_course_title_date','assignment_id':soft[0]['id'],'authority':'candidate match; verify Canvas details'}
 return {'match':'unmatched','authority':'calendar supplement only'}

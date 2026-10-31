"""Optional calendar supplement. Email is an optional supplement under local-first-v4 (school_hq_mail.py)
and is collected by the worker, not here. Never edits required receipt statuses."""
import json,sqlite3
from pathlib import Path
from school_hq_coaching import atomic
from school_hq_calendar import collect as calendar_collect

def collect(bridge,request_id):
 bridge=Path(bridge)
 result={'request_id':request_id,'policy':'optional-supplements-v2','required':False,'calendar':calendar_collect(bridge,request_id)}
 if result['calendar']['status']=='checked':
  db=sqlite3.connect(bridge/'calendar.sqlite3')
  records=[json.loads(row[0]) for row in db.execute('SELECT payload FROM events ORDER BY occurrence LIMIT 1000')];db.close()
  # Full descriptions and the private feed URL stay out of the planning payload.
  result['calendar']['planning_events']=[{k:e.get(k) for k in ('summary','course','start','end','all_day','status','url')} for e in records]
 atomic(bridge/'optional-sources.json',result);return result

"""Versioned source requirements; no collection, cache reads or credentials.

local-first-v4 (current): Canvas only, through the app-owned WebKit session. Exam facts
come from Canvas announcements, so email is not required. A connected mailbox (any IMAP
provider) is an optional supplement that never blocks a sync. Older policies stay pinned
so historical receipts still verify.
"""
import json
from pathlib import Path

ACTIVE_POLICY_ID='local-first-v4'
ACTIVE_SOURCES=['canvas']
OPTIONAL_SOURCES=['mail']
POLICY_SOURCES={'local-first-v4':['canvas'],'local-first-v3':['canvas','gmail'],'local-first-v2':['canvas','email'],'local-first-v1':['canvas','email','remarkable']}
SOURCE_LABELS={'canvas':'Canvas','mail':'Email','gmail':'Gmail','email':'UCF Mail','remarkable':'reMarkable'}

def required_sources(request):
 ident=request.get('policy_id') or 'local-first-v1'
 if ident not in POLICY_SOURCES:raise ValueError('Unknown source policy')
 return list(POLICY_SOURCES[ident])

def policy_file(root,ident):
 if ident not in POLICY_SOURCES:raise ValueError('Unknown source policy')
 root=Path(root);active=root/'school_hq_local_policy.json'
 if active.is_file() and json.loads(active.read_text()).get('id')==ident:return active
 archived=root/'School HQ App/Policies'/(ident+'.json')
 if not archived.is_file():raise ValueError('Pinned historical source policy is unavailable')
 return archived

def require_collection(source):
 if source not in ACTIVE_SOURCES:
  raise RuntimeError(SOURCE_LABELS.get(source,source)+' collection has been retired. Saved files are preserved; no check runs.')

"""Exercise startup against a clean temporary workspace, never the owner's records."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

MAC=Path(__file__).resolve().parents[1]
python=MAC/'Runtime/bin/python3'
spec=importlib.util.spec_from_file_location('release',MAC/'build_release.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
release.validate_runtime(MAC/'Runtime')
print('PASS: relocated Python independently imports SSL, SQLite, and timezone modules.')
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);shutil.copytree(MAC/'Backend',root/'workspace')
    outputs=root/'workspace/outputs'
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    for script,args in [('school_hq_app_bridge.py',['status']),('school_hq_context.py',['list']),('school_hq_engine.py',['overview'])]:
        result=subprocess.run([str(python),str(outputs/script),*args],cwd=outputs,env=env,capture_output=True,text=True,timeout=30)
        if result.returncode:raise RuntimeError(script+': '+result.stderr[-2500:])
        json.loads(result.stdout)
        print('PASS: fresh-workspace '+script+' '+' '.join(args))
    study=outputs/'School HQ Study';study.mkdir(exist_ok=True)
    (study/'study-progress.json').write_text(json.dumps({'coverage':[{'course':'COP3330','skill':'Loops'}]}))
    result=subprocess.run([str(python),'-c',
        'import school_hq_coaching as c; s=c.initial(c.ROOT); assert s["skills"][0]["name"]=="Loops"; assert s["skills"][0]["status"]=="untested"'],cwd=outputs,env=env,capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError(result.stderr)
    print('PASS: existing learning coverage remains preserved by migration.')

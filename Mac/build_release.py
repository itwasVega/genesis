#!/usr/bin/env python3
"""Build Genesis from clean sources. Never package the developer's live workspace."""
import argparse
import json
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEAM = '8K8P8HVP63'
SOURCES = ['App','Theme','Store','RichText','AnswerInputs','TodayView','TaskView',
           'PracticeView','ProgressLibrary','SettingsView','LocalCanvas','OrbRenderer','Companion','GenesisRuntime','GenesisConfiguration']
FRAMEWORKS = ['SwiftUI','AppKit','PDFKit','UserNotifications','WebKit','Security','Metal','MetalKit','QuartzCore']

def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)

def identities():
    result = run(['/usr/bin/security','find-identity','-v','-p','codesigning'], capture_output=True, text=True)
    return re.findall(r'"(Developer ID Application: [^"]+ \('+TEAM+r'\))"', result.stdout)

def audit(runtime):
    issues = []
    if not runtime or not (runtime/'bin/python3').is_file():
        issues.append('A redistributable Apple-silicon Python runtime with dependencies is not supplied.')
    files = list((ROOT/'Source').glob('*.swift')) + list((ROOT/'Backend/outputs').glob('*.py'))
    personal = []
    courses = []
    client = []
    for path in files:
        for line, text in enumerate(path.read_text().splitlines(),1):
            location = f'{path.relative_to(ROOT)}:{line}'
            if re.search(r'[A-Za-z0-9._%+-]+@(gmail|icloud|knights\.ucf)\.(com|edu)|/Users/[^/]+/',text): personal.append(location)
            if re.search(r"courses/[0-9]{5,}|'canvas_id'\s*:\s*'[0-9]+'",text): courses.append(location)
            if '/Applications/ChatGPT.app/' in text: client.append(location)
    if personal: issues.append('Personal-account constants still need generalization: '+', '.join(personal))
    if courses: issues.append('Canvas course IDs still need per-user configuration: '+', '.join(courses))
    if client: issues.append('AI backend depends on the local ChatGPT-bundled Codex client; onboarding/support for other users is unverified: '+', '.join(client))
    return issues

def compile_app(build):
    build.mkdir(parents=True,exist_ok=True)
    binary = build/'Genesis'
    args = ['/usr/bin/swiftc','-module-cache-path',build/'swift-cache','-target','arm64-apple-macos15.0','-parse-as-library']
    args += [ROOT/'Source'/f'{name}.swift' for name in SOURCES]
    args += ['-o',binary]
    for framework in FRAMEWORKS: args += ['-framework',framework]
    run(args)
    return binary

def validate_runtime(runtime):
    for file in runtime.rglob('*'):
        if file.is_symlink() and not file.resolve().is_relative_to(runtime.resolve()):
            raise ValueError('Runtime contains an external symlink: '+str(file.relative_to(runtime)))
    result=run([runtime/'bin/python3','-I','-c',
        'import sys,ssl,sqlite3,zoneinfo; print(sys.prefix)'],capture_output=True,text=True)
    if Path(result.stdout.strip()).resolve()!=runtime.resolve():
        raise ValueError('Runtime is not self-contained (its Python prefix points elsewhere).')

def sign(app,identity):
    # Sign nested Mach-O code first; --deep is used only for verification.
    magics={b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'}
    for path in sorted(app.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if not path.is_file() or path.is_symlink(): continue
        with path.open('rb') as f: magic=f.read(4)
        if magic in magics: run(['/usr/bin/codesign','--force','--options','runtime','--timestamp','--sign',identity,path])
    run(['/usr/bin/codesign','--force','--options','runtime','--timestamp','--sign',identity,app])
    run(['/usr/bin/codesign','--verify','--deep','--strict',app])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-only',action='store_true',help='Compile the native UI only; no app or distributable is produced.')
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--runtime',type=Path,default=ROOT/'Runtime',help='Relocatable Python install root; must include its dependency/license files.')
    parser.add_argument('--notary-profile',help='Keychain profile created with xcrun notarytool store-credentials')
    args=parser.parse_args()
    build=ROOT/'Build'
    if args.compile_only:
        print(compile_app(build));return
    runtime=args.runtime.resolve() if args.runtime else None
    issues=audit(runtime)
    certs=identities()
    if not certs:issues.append('No Developer ID Application signing identity is visible for team '+TEAM+'.')
    if not args.notary_profile:issues.append('A notarization Keychain profile is not configured for this invocation.')
    print(json.dumps({'ready':not issues,'blockers':issues},indent=2))
    if args.audit:return
    if issues:raise SystemExit('Release stopped before packaging. Resolve the reported blockers.')
    validate_runtime(runtime)
    binary=compile_app(build)
    app=build/'Genesis.app'
    if app.exists():shutil.rmtree(app)
    resources=app/'Contents/Resources';resources.mkdir(parents=True)
    (app/'Contents/MacOS').mkdir()
    shutil.copy2(binary,app/'Contents/MacOS/Genesis')
    info=plistlib.loads((ROOT/'Info.plist').read_bytes());info['CFBundleIdentifier']='com.xander.schoolhq';info['CFBundleVersion']='44'
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    for name in ['Math','GenesisFonts']:
        shutil.copytree(ROOT/'Resources'/name,resources/('Fonts' if name=='GenesisFonts' else name))
    for name in ['AppIcon.icns','GenesisWordmark.png','OrbBloom.png','OrbReference.png','ThirdPartyNotices.txt','PythonDependencyLicenses.txt']:
        shutil.copy2(ROOT/'Resources'/name,resources/name)
    shutil.copy2(ROOT/'Source/CanvasStructured.js',resources/'CanvasStructured.js')
    shutil.copytree(ROOT/'Backend',resources/'Backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    shutil.copytree(runtime,resources/'Python',symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    helpers=app/'Contents/Helpers';helpers.mkdir()
    run(['/usr/bin/swiftc','-module-cache-path',build/'swift-cache','-target','arm64-apple-macos15.0',
         '-parse-as-library',ROOT/'Source/GenesisPDF.swift','-o',helpers/'GenesisPDF',
         '-framework','AppKit','-framework','PDFKit','-framework','Vision'])
    sign(app,certs[0])
    upload=build/'Genesis-notarization.zip'
    run(['/usr/bin/ditto','-c','-k','--keepParent',app,upload])
    result=run(['/usr/bin/xcrun','notarytool','submit',upload,'--keychain-profile',args.notary_profile,
                '--wait','--output-format','json'],capture_output=True,text=True)
    (build/'notarization.json').write_text(result.stdout)
    if json.loads(result.stdout).get('status')!='Accepted':raise SystemExit('Notarization not accepted; inspect notarization.json.')
    run(['/usr/bin/xcrun','stapler','staple',app])
    run(['/usr/bin/xcrun','stapler','validate',app])
    run(['/usr/sbin/spctl','--assess','--type','execute','--verbose',app])
    final=build/'Genesis-for-Mac.zip'
    run(['/usr/bin/ditto','-c','-k','--keepParent',app,final])
    print('Signed and notarized distribution:',final)

if __name__=='__main__':main()

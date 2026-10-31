#!/usr/bin/env python3
"""Create a normal macOS Xcode app with individually signed embedded runtime code."""
import hashlib, plistlib, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
objects={}
def obj(key,**fields):
 ident=hashlib.sha256(key.encode()).hexdigest()[:24].upper();objects[ident]=fields;return ident
def file(path,kind,**extra):return obj('file:'+path,isa='PBXFileReference',path=path,lastKnownFileType=kind,sourceTree='<group>',**extra)
def configs(key,settings,app=False):
 ids=[]
 for name in ('Debug','Release'):
  s={**settings,'SWIFT_OPTIMIZATION_LEVEL':'-Onone' if name=='Debug' else '-O','DEBUG_INFORMATION_FORMAT':'dwarf' if name=='Debug' else 'dwarf-with-dsym'}
  s['CODE_SIGN_IDENTITY']='Apple Development' if name=='Debug' else 'Developer ID Application'
  if app and name=='Debug':s['PRODUCT_BUNDLE_IDENTIFIER']='com.xander.schoolhq.distributiontest'
  ids.append(obj(key+name,isa='XCBuildConfiguration',name=name,buildSettings=s))
 return obj(key,isa='XCConfigurationList',buildConfigurations=ids,defaultConfigurationIsVisible=0,defaultConfigurationName='Release')
def build(ref,sign=False):return obj('build:'+ref,isa='PBXBuildFile',fileRef=ref,**({'settings':{'ATTRIBUTES':['CodeSignOnCopy']}} if sign else {}))
def phase(key,isa,refs,**fields):return obj(key,isa=isa,buildActionMask=2147483647,files=[build(r,fields.pop('sign',False)) for r in refs],runOnlyForDeploymentPostprocessing=0,**fields)
MAGICS={b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'}
# Only static resources. Mach-O files have individual CodeSignOnCopy build entries.
staged=ROOT/'BundleResources'
if staged.exists():shutil.rmtree(staged)
staged.mkdir()
shutil.copytree(ROOT/'Runtime',staged/'Python',symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
code={}
for p in sorted((staged/'Python').rglob('*')):
 if p.is_file() and not p.is_symlink():
  with p.open('rb') as f:magic=f.read(4)
  if magic in MAGICS:
   relative=p.relative_to(staged/'Python')
   code.setdefault(str(relative.parent),[]).append(file('Runtime/'+str(relative),'compiled.mach-o.executable'))
   p.unlink()
# Native app sources; PDF command line helper has a separate target.
sources=[file(str(p.relative_to(ROOT)),'sourcecode.swift') for p in sorted((ROOT/'Source').glob('*.swift')) if p.name!='GenesisPDF.swift']
resources=[file('Backend','folder'),file('BundleResources/Python','folder')]
for name in ['Math','GenesisFonts']:
 destination='Fonts' if name=='GenesisFonts' else name
 shutil.copytree(ROOT/'Resources'/name,staged/destination)
 resources.append(file('BundleResources/'+destination,'folder'))
for name in ['AppIcon.icns','GenesisWordmark.png','OrbBloom.png','OrbReference.png']:
 resources.append(file('Resources/'+name,'file'))
resources.append(file('Source/CanvasStructured.js','sourcecode.javascript'))
for name in ['ThirdPartyNotices.txt','PythonDependencyLicenses.txt']:
 resources.append(file('Resources/'+name,'text'))
app=obj('product',isa='PBXFileReference',explicitFileType='wrapper.application',path='Genesis.app',sourceTree='BUILT_PRODUCTS_DIR',includeInIndex=0)
helper=obj('helper',isa='PBXFileReference',explicitFileType='compiled.mach-o.executable',path='GenesisPDF',sourceTree='BUILT_PRODUCTS_DIR',includeInIndex=0)
common={'SDKROOT':'macosx','MACOSX_DEPLOYMENT_TARGET':'15.0','ARCHS':'arm64','SWIFT_VERSION':'5.0','DEVELOPMENT_TEAM':'8K8P8HVP63','CODE_SIGN_STYLE':'Manual','ENABLE_HARDENED_RUNTIME':'YES','CODE_SIGN_INJECT_BASE_ENTITLEMENTS':'NO','ENABLE_USER_SCRIPT_SANDBOXING':'YES','CLANG_ENABLE_MODULES':'YES'}
helper_source=file('Source/GenesisPDF.swift','sourcecode.swift')
helper_target=obj('helper-target',isa='PBXNativeTarget',name='GenesisPDF',productName='GenesisPDF',productType='com.apple.product-type.tool',productReference=helper,buildConfigurationList=configs('helper-config',{**common,'PRODUCT_NAME':'GenesisPDF','SKIP_INSTALL':'YES'}),buildPhases=[phase('helper-sources','PBXSourcesBuildPhase',[helper_source])],buildRules=[],dependencies=[])
project_id=hashlib.sha256(b'project').hexdigest()[:24].upper()
proxy=obj('proxy',isa='PBXContainerItemProxy',containerPortal=project_id,proxyType=1,remoteGlobalIDString=helper_target,remoteInfo='GenesisPDF')
dependency=obj('dependency',isa='PBXTargetDependency',target=helper_target,targetProxy=proxy)
copy_helper=phase('copy-helper','PBXCopyFilesBuildPhase',[helper],dstSubfolderSpec=1,dstPath='Contents/Helpers',name='Embed PDF helper',sign=True)
phases=[phase('sources','PBXSourcesBuildPhase',sources),phase('resources','PBXResourcesBuildPhase',resources),copy_helper]
for directory,refs in code.items():
 # One phase per runtime directory. Each executable and library is signed by Xcode.
 entries=[build(r,True) for r in refs]
 phases.append(obj('copy:'+directory,isa='PBXCopyFilesBuildPhase',buildActionMask=2147483647,files=entries,runOnlyForDeploymentPostprocessing=0,dstSubfolderSpec=7,dstPath='Python/'+directory,name='Embed signed Python '+directory))
settings={**common,'PRODUCT_NAME':'Genesis','PRODUCT_BUNDLE_IDENTIFIER':'com.xander.schoolhq','INFOPLIST_FILE':'Info.plist','GENERATE_INFOPLIST_FILE':'NO','MARKETING_VERSION':'1.0','CURRENT_PROJECT_VERSION':'45','LD_RUNPATH_SEARCH_PATHS':['$(inherited)','@executable_path/../Frameworks'],'COMBINE_HIDPI_IMAGES':'YES'}
target=obj('app-target',isa='PBXNativeTarget',name='Genesis',productName='Genesis',productType='com.apple.product-type.application',productReference=app,buildConfigurationList=configs('app-config',settings,app=True),buildPhases=phases,buildRules=[],dependencies=[dependency])
products=obj('products',isa='PBXGroup',name='Products',sourceTree='<group>',children=[app,helper])
allfiles=sources+[helper_source]+resources+[x for refs in code.values() for x in refs]+[file('Info.plist','text.plist.xml')]
group=obj('group',isa='PBXGroup',sourceTree='<group>',children=allfiles+[products])
obj('project',isa='PBXProject',attributes={'LastUpgradeCheck':'2700'},buildConfigurationList=configs('project-config',{}),compatibilityVersion='Xcode 14.0',developmentRegion='en',knownRegions=['en','Base'],mainGroup=group,productRefGroup=products,projectDirPath='',projectRoot='',targets=[target,helper_target])
proj=ROOT/'GenesisMac.xcodeproj';proj.mkdir(exist_ok=True)
(proj/'project.pbxproj').write_bytes(plistlib.dumps({'archiveVersion':'1','classes':{},'objectVersion':'56','objects':objects,'rootObject':project_id}))
ref=f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="Genesis.app" BlueprintName="Genesis" ReferencedContainer="container:GenesisMac.xcodeproj"/>'
schemes=proj/'xcshareddata/xcschemes';schemes.mkdir(parents=True,exist_ok=True)
(schemes/'Genesis Mac.xcscheme').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2700" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{ref}</BuildActionEntry></BuildActionEntries></BuildAction>
<LaunchAction selectedDebuggerIdentifier="" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.PosixSpawn" buildConfiguration="Debug" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable><EnvironmentVariables><EnvironmentVariable key="GENESIS_TEST_WORKSPACE" value="{ROOT/'Build/FreshWorkspace'}" isEnabled="YES"/></EnvironmentVariables></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/></Scheme>''')
print(proj)

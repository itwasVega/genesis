#!/usr/bin/env python3
"""Generate a normal Xcode app project without Swift Playgrounds dependencies."""
import hashlib
import plistlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'iOS'
objects = {}

def obj(key, **fields):
    ident = hashlib.sha256(key.encode()).hexdigest()[:24].upper()
    objects[ident] = fields
    return ident

def file(path, kind):
    return obj('file:' + path, isa='PBXFileReference', path=path,
               lastKnownFileType=kind, sourceTree='<group>')

def config_list(key, settings):
    configs = []
    for name in ('Debug', 'Release'):
        values = dict(settings)
        values['SWIFT_OPTIMIZATION_LEVEL'] = '-Onone' if name == 'Debug' else '-O'
        values['DEBUG_INFORMATION_FORMAT'] = 'dwarf' if name == 'Debug' else 'dwarf-with-dsym'
        configs.append(obj(key + name, isa='XCBuildConfiguration', name=name, buildSettings=values))
    return obj(key, isa='XCConfigurationList', buildConfigurations=configs,
               defaultConfigurationIsVisible=0, defaultConfigurationName='Release')

def main():
    source_files = [file(p.name, 'sourcecode.swift') for p in sorted(ROOT.glob('*.swift'))]
    resource_files = [file('Assets.xcassets', 'folder.assetcatalog')]
    resource_files += [file(str(p.relative_to(ROOT)), 'file') for p in sorted((ROOT/'Resources').iterdir()) if p.is_file()]
    resource_files.append(file('PrivacyInfo.xcprivacy', 'text.xml'))
    source_phase = obj('sources', isa='PBXSourcesBuildPhase', buildActionMask=2147483647,
        files=[obj('build:'+f, isa='PBXBuildFile', fileRef=f) for f in source_files], runOnlyForDeploymentPostprocessing=0)
    resource_phase = obj('resources', isa='PBXResourcesBuildPhase', buildActionMask=2147483647,
        files=[obj('build:'+f, isa='PBXBuildFile', fileRef=f) for f in resource_files], runOnlyForDeploymentPostprocessing=0)
    product = obj('product', isa='PBXFileReference', explicitFileType='wrapper.application',
                  path='Genesis.app', sourceTree='BUILT_PRODUCTS_DIR', includeInIndex=0)
    products = obj('products', isa='PBXGroup', name='Products', sourceTree='<group>', children=[product])
    group = obj('main', isa='PBXGroup', sourceTree='<group>', children=source_files + resource_files + [file('Info.plist','text.plist.xml'), products])
    settings = dict(PRODUCT_BUNDLE_IDENTIFIER='com.xander.genesis.pocket', DEVELOPMENT_TEAM='8K8P8HVP63',
                    CODE_SIGN_STYLE='Automatic', PRODUCT_NAME='Genesis', SDKROOT='iphoneos',
                    SUPPORTED_PLATFORMS='iphoneos iphonesimulator', IPHONEOS_DEPLOYMENT_TARGET='18.0',
                    TARGETED_DEVICE_FAMILY='1', SWIFT_VERSION='5.0', INFOPLIST_FILE='Info.plist',
                    GENERATE_INFOPLIST_FILE='NO', MARKETING_VERSION='1.0', CURRENT_PROJECT_VERSION='2',
                    ASSETCATALOG_COMPILER_APPICON_NAME='AppIcon', ENABLE_USER_SCRIPT_SANDBOXING='YES',
                    LD_RUNPATH_SEARCH_PATHS=['$(inherited)', '@executable_path/Frameworks'],
                    CLANG_ENABLE_MODULES='YES', SUPPORTS_MACCATALYST='NO')
    target = obj('target', isa='PBXNativeTarget', name='Genesis', productName='Genesis',
        productType='com.apple.product-type.application', productReference=product,
        buildConfigurationList=config_list('target-config',settings), buildPhases=[source_phase,resource_phase], buildRules=[], dependencies=[])
    project = obj('project', isa='PBXProject', attributes={'LastUpgradeCheck':'2700', 'TargetAttributes':{target:{'DevelopmentTeam':'8K8P8HVP63','ProvisioningStyle':'Automatic'}}},
        buildConfigurationList=config_list('project-config',{}), compatibilityVersion='Xcode 14.0',
        developmentRegion='en', knownRegions=['en','Base'], mainGroup=group, productRefGroup=products,
        projectDirPath='', projectRoot='', targets=[target])
    destination=ROOT/'Genesis.xcodeproj'; destination.mkdir(exist_ok=True)
    (destination/'project.pbxproj').write_bytes(plistlib.dumps(dict(archiveVersion='1', classes={}, objectVersion='56', objects=objects, rootObject=project)))
    schemes=destination/'xcshareddata/xcschemes'; schemes.mkdir(parents=True,exist_ok=True)
    ref=f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="Genesis.app" BlueprintName="Genesis" ReferencedContainer="container:Genesis.xcodeproj"/>'
    (schemes/'Genesis.xcscheme').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2700" version="1.3">
 <BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{ref}</BuildActionEntry></BuildActionEntries></BuildAction>
 <LaunchAction buildConfiguration="Debug" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" allowLocationSimulation="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></LaunchAction>
 <ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></ProfileAction>
 <AnalyzeAction buildConfiguration="Debug"/>
 <ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>
''')
    info=dict(CFBundleDevelopmentRegion='en', CFBundleDisplayName='Genesis', CFBundleExecutable='$(EXECUTABLE_NAME)',
              CFBundleIdentifier='$(PRODUCT_BUNDLE_IDENTIFIER)', CFBundleInfoDictionaryVersion='6.0', CFBundleName='Genesis',
              CFBundlePackageType='APPL', CFBundleShortVersionString='$(MARKETING_VERSION)', CFBundleVersion='$(CURRENT_PROJECT_VERSION)',
              LSRequiresIPhoneOS=True, ITSAppUsesNonExemptEncryption=False, UILaunchScreen={}, UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'],
              LSSupportsOpeningDocumentsInPlace=True,
              CFBundleURLTypes=[dict(CFBundleURLName='com.xander.genesis.pocket',CFBundleURLSchemes=['genesis-pocket'])])
    (ROOT/'Info.plist').write_bytes(plistlib.dumps(info))
    privacy={'NSPrivacyTracking':False,'NSPrivacyTrackingDomains':[], 'NSPrivacyCollectedDataTypes':[],
             'NSPrivacyAccessedAPITypes':[{'NSPrivacyAccessedAPIType':'NSPrivacyAccessedAPICategoryUserDefaults','NSPrivacyAccessedAPITypeReasons':['CA92.1']}]}
    (ROOT/'PrivacyInfo.xcprivacy').write_bytes(plistlib.dumps(privacy))
    print(destination)

if __name__=='__main__': main()

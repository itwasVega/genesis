#!/bin/zsh
set -euo pipefail
genesis_dir="${0:A:h}"
mkdir -p "$genesis_dir/Build"
xcodebuild -project "$genesis_dir/iOS/Genesis.xcodeproj" -scheme Genesis \
  -configuration Release -destination 'generic/platform=iOS' \
  -derivedDataPath "$genesis_dir/Build/iOS" \
  -archivePath "$genesis_dir/Build/Genesis.xcarchive" \
  -allowProvisioningUpdates DEVELOPMENT_TEAM=8K8P8HVP63 CODE_SIGN_STYLE=Automatic archive
xcodebuild -exportArchive -archivePath "$genesis_dir/Build/Genesis.xcarchive" \
  -exportOptionsPlist "$genesis_dir/iOS/ExportOptions.plist" \
  -exportPath "$genesis_dir/Build/Export" -allowProvisioningUpdates
print 'Xcode export/upload completed. Check processing and testing status in App Store Connect.'

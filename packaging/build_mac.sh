#!/bin/bash
# Builds dist/HarnessDiscussion.dmg: an arm64 "Harness Discussion.app" for macOS 13+, signed ad hoc or with the local identity.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked
version=$(uv run python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
if [[ "${GITHUB_REF_TYPE:-}" == tag && "${GITHUB_REF_NAME:-}" != "v$version" ]]; then
    echo "Release tag must match pyproject.toml version" >&2
    exit 1
fi
commit=${RELEASE_COMMIT:-$(git rev-parse HEAD)}
rm -rf build/icon.iconset build/dist/"Harness Discussion.app" build/dmg dist/HarnessDiscussion.dmg
mkdir -p build/icon.iconset dist
uv run python - <<'EOF'
from harness_discussion.icons import icon_image
for size in (16, 32, 128, 256, 512):
    icon_image(size).save(f"build/icon.iconset/icon_{size}x{size}.png")
    icon_image(size * 2).save(f"build/icon.iconset/icon_{size}x{size}@2x.png")
EOF
iconutil -c icns build/icon.iconset -o build/icon.icns
uv run pyinstaller --noconfirm --clean --windowed --name "Harness Discussion" \
    --osx-bundle-identifier com.tzachbon.harnessdiscussion --target-arch arm64 --icon "$PWD/build/icon.icns" \
    --hidden-import harness_discussion.mac.main --collect-submodules harness_discussion.mac --copy-metadata harness-discussion \
    --distpath build/dist --workpath build/work --specpath build packaging/launcher.py
app="build/dist/Harness Discussion.app"
plist="$app/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$version" "$plist"
plutil -replace CFBundleVersion -string "$version" "$plist"
plutil -replace LSUIElement -bool true "$plist"
plutil -replace LSMinimumSystemVersion -string 13.0 "$plist"
plutil -replace HarnessDiscussionBuild -string "$version+$commit" "$plist"
# The local identity from setup_signing_mac.sh keeps the Accessibility grant across rebuilds. CI signs ad hoc.
keychain="$HOME/Library/Keychains/harness-discussion-signing.keychain-db"
if [[ -f "$keychain" ]] && password=$(security find-generic-password -s harness-discussion-signing -a "$USER" -w); then
    security unlock-keychain -p "$password" "$keychain"
    codesign --force --deep --keychain "$keychain" --sign "Harness Discussion Local Signing" "$app"
    security lock-keychain "$keychain"
else
    codesign --force --deep --sign - "$app"
fi
codesign --verify --deep --strict "$app"
"$app/Contents/MacOS/Harness Discussion" --self-test
mkdir -p build/dmg
cp -R "$app" build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -volname "Harness Discussion" -srcfolder build/dmg -fs HFS+ -format UDZO -ov dist/HarnessDiscussion.dmg
ls -l dist/HarnessDiscussion.dmg

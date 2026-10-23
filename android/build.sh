#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
android_sdk="${ANDROID_SDK_ROOT:-/opt/qbeat-android/sdk}"
build_tools="$android_sdk/build-tools/35.0.0"
platform_jar="$android_sdk/platforms/android-35/android.jar"
build_dir="$project_dir/android/build"
signing_dir="${QBEAT_SIGNING_DIR:-/etc/qbeat-signing}"
mkdir -p "$build_dir/classes" "$build_dir/generated" "$build_dir/dex" "$project_dir/static/downloads"
"$build_tools/aapt2" compile --dir "$project_dir/android/res" -o "$build_dir/resources.zip"
"$build_tools/aapt2" link -o "$build_dir/base.apk" -I "$platform_jar" --manifest "$project_dir/android/AndroidManifest.xml" --java "$build_dir/generated" -A "$project_dir/android/assets" "$build_dir/resources.zip"
mapfile -t java_sources < <(find "$project_dir/android/src" "$build_dir/generated" -name '*.java')
javac --release 8 -classpath "$platform_jar" -d "$build_dir/classes" "${java_sources[@]}"
mapfile -t class_files < <(find "$build_dir/classes" -name '*.class')
"$build_tools/d8" --min-api 23 --lib "$platform_jar" --output "$build_dir/dex" "${class_files[@]}"
python3 - "$build_dir" <<'PY'
from pathlib import Path
import sys, zipfile
base=Path(sys.argv[1])
with zipfile.ZipFile(base/'base.apk','a') as z:
    z.write(base/'dex/classes.dex','classes.dex')
PY
"$build_tools/zipalign" -f -p 4 "$build_dir/base.apk" "$build_dir/aligned.apk"
"$build_tools/apksigner" sign --ks "$signing_dir/qbeat-release.jks" --ks-key-alias qbeat --ks-pass "file:$signing_dir/password" --out "$project_dir/static/downloads/qbeat-fire-tv.apk" "$build_dir/aligned.apk"
"$build_tools/apksigner" verify --verbose "$project_dir/static/downloads/qbeat-fire-tv.apk"
sha256sum "$project_dir/static/downloads/qbeat-fire-tv.apk" | cut -d ' ' -f 1 > "$project_dir/static/downloads/qbeat-fire-tv.apk.sha256"
echo "Built static/downloads/qbeat-fire-tv.apk"

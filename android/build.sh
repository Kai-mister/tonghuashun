#!/bin/sh
set -eu
: "${ANDROID_JAR:?Android platform android.jar}" "${BUILD_TOOLS:?SDK build-tools directory}" "${JAVA_HOME:?JDK directory}" "${KEYSTORE:?signing keystore}" "${KS_PASS:?keystore password}"
export PATH="$JAVA_HOME/bin:$PATH" KS_PASS
cd "$(dirname "$0")"
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
mkdir -p "$out/classes" "$out/dex" dist
"$BUILD_TOOLS/aapt2" compile --dir res -o "$out/resources.zip"
"$BUILD_TOOLS/aapt2" link -I "$ANDROID_JAR" --manifest AndroidManifest.xml -o "$out/app.apk" "$out/resources.zip"
javac --release 8 -classpath "$ANDROID_JAR" -d "$out/classes" src/cn/local/simmanager/*.java
jar cf "$out/code.jar" -C "$out/classes" .
"$BUILD_TOOLS/d8" --min-api 26 --lib "$ANDROID_JAR" --output "$out/dex" "$out/code.jar"
(cd "$out/dex" && zip -q "$out/app.apk" classes.dex)
"$BUILD_TOOLS/zipalign" -f 4 "$out/app.apk" "$out/aligned.apk"
"$BUILD_TOOLS/apksigner" sign --ks "$KEYSTORE" --ks-pass env:KS_PASS --out dist/sim-manager.apk "$out/aligned.apk"
"$BUILD_TOOLS/apksigner" verify dist/sim-manager.apk

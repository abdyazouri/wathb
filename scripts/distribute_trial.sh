#!/usr/bin/env bash
# Builds the signed release APK and sends it to the "trial" testers through
# Firebase App Distribution. See docs/TRIAL_DISTRIBUTION.md.
#
#   FIREBASE_APP_ID=1:...:android:... scripts/distribute_trial.sh ["release notes"]
#
# Needs: android/keystore.properties (release key), the Firebase CLI logged in
# (`firebase login`), and FIREBASE_APP_ID in the environment. Raise versionCode in
# android/app/build.gradle.kts before every distribution.
set -euo pipefail

if [[ -z "${FIREBASE_APP_ID:-}" ]]; then
  echo "FIREBASE_APP_ID is not set (Firebase console → Project settings → Your apps → App ID)." >&2
  exit 1
fi
command -v firebase >/dev/null || { echo "Firebase CLI missing: npm install -g firebase-tools" >&2; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
NOTES="${1:-نسخة تجريبية من وَثْب للتجربة الخاصة. ادخل برقم هاتفك وكلمة المرور، وبلّغنا عن أي مشكلة عبر واتساب الدعم.}"

(cd "$ROOT/android" && ./gradlew assembleRelease)

firebase appdistribution:distribute "$APK" \
  --app "$FIREBASE_APP_ID" \
  --groups "trial" \
  --release-notes "$NOTES"

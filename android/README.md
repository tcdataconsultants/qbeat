# Qbeat for Fire TV

Native Java TV activity with a visible YouTube WebView player, native queue/QR sidebar, native PIN entry, and controls that support the Fire TV remote. Built for Fire OS / Android API 23 and later, landscape, no Google Play Services dependency. Vega OS devices require a different app and are not supported by this APK.

Public download: http://89.167.98.40:8090/qbeat.apk

Installation guide: http://89.167.98.40:8090/tv-app

## Build

Requires JDK 17+, Android SDK platform 35, Android build tools 35.0.0, Python 3, and Bash. The server has these under `/opt/qbeat-android/sdk`.

```sh
bash android/build.sh
```

Optional configuration: `ANDROID_SDK_ROOT` and `QBEAT_SIGNING_DIR`.

The release keystore and password are stored outside the repository in `/etc/qbeat-signing`. Both are root-readable only. Back them up securely; future APK updates must use the same signing key. The APK is written to `static/downloads/qbeat-fire-tv.apk`, alongside its SHA-256 checksum. Build outputs and signing files are ignored by Git.

To create a separate signing identity on another machine, use `keytool -genkeypair` with alias `qbeat`, place the keystore at `$QBEAT_SIGNING_DIR/qbeat-release.jks`, and store its password on the first line of `$QBEAT_SIGNING_DIR/password`. Do not overwrite this server's signing identity.

## Architecture

- Backend URL is a build-time constant in `MainActivity.java`.
- Host PIN is exchanged for a session cookie and is not stored. The session cookie is kept in app-private preferences. Sign out deletes it. No host PIN or YouTube API key is bundled in the APK.
- Network requests run on a single background executor. Queue polling happens every three seconds while the activity is visible. Leaving the app stops heartbeats and pauses local playback. Another player can acquire the lease after 15 seconds.
- The native activity exposes only player lifecycle events to a local HTML asset. The YouTube iframe remains visible with its controls. App client identity is provided through `loadDataWithBaseURL` using `https://com.tcdataconsultants.qbeat/`, following YouTube's documented WebView identity pattern. No video extraction or playback outside the official player is used.
- Media playback does not require a WebView user gesture. Device-specific playback restrictions can still apply. Playback errors show their exact code and preserve the queue for retry or a manual skip.
- Cleartext HTTP is allowed only for the existing backend IP on Android 7+. YouTube resources use HTTPS. Android 6 falls back to the manifest cleartext setting. A domain/HTTPS backend should replace the current IP for regular use.
- The native app keeps the display awake while visible. Back exits the video focus or prompts to leave; media play/pause controls the shared queue.

## Verification

```sh
bash android/build.sh                  # compiles Java/Dex/resources and verifies the APK signature
node tests/test_native_player.cjs       # exercises the WebView lifecycle bridge
.venv/bin/python -m unittest discover -s tests -v
```

APK compilation/signature and automated bridge/API tests do not establish physical Firestick compatibility. Test sign-in, D-pad focus, QR scanning, audio/video, pause/resume, song handoff, error recovery, background/foreground, and relaunch on the device before treating this as production-ready. The first build has not been run on a physical Firestick or Android emulator.

References: [Fire TV manifest support](https://developer.amazon.com/docs/fire-tv/add-tv-support-to-an-existing-react-native-project.html), [YouTube embedded player identity](https://developers.google.com/youtube/terms/required-minimum-functionality#api-client-identity-and-credentials).

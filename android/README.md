# Qbeat for Fire TV

Native Java TV activity with a visible YouTube WebView player, native queue/QR sidebar, native PIN entry, and controls that support the Fire TV remote. Built for Fire OS / Android API 23 and later, landscape, no Google Play Services dependency. Vega OS devices require a different app and are not supported by this APK.

## Version 1.1.0

- Landscape artwork is explicitly assigned to the application and launcher activity.
- **More → Fullscreen TV mode** hides Qbeat's chrome and sidebar. The remote's Menu button shows/hides controls; Back returns to the normal layout. This keeps the app fullscreen and the screen awake, but does not disable Fire TV's Home button or lock the device to Qbeat.
- Subtitles default off, with a saved on/off preference under More. The player requests captions off and unloads its captions module when that API is available. Preferences or text embedded in the video itself can still affect what is shown. YouTube branding remains visible under its player rules.
- During the final ten seconds, a **Coming next** strip appears below the player when a next song is queued. It does not cover the YouTube video or skip its ending. The clock follows the player's actual position.
- Guest colours and icons appear with their tracks. The current guest's optional photo is shown alongside their name.

Install over version 1.0.0 to retain the host session. The same signing identity is used for updates. New native controls and launcher artwork require updating the APK; website changes arrive on refresh.

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

APK compilation/signature and automated bridge/API tests do not establish physical Firestick compatibility. The user has confirmed version 1.0.0 plays on their Firestick. Version 1.1.0's new controls and layout still need physical-device verification; no Android emulator was used.

References: [Fire TV manifest support](https://developer.amazon.com/docs/fire-tv/add-tv-support-to-an-existing-react-native-project.html), [YouTube embedded player identity](https://developers.google.com/youtube/terms/required-minimum-functionality#api-client-identity-and-credentials).

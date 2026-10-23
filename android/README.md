# Qbeat for Fire TV

Native Java TV activity with a visible YouTube WebView player, native queue/QR sidebar, native PIN entry, and controls that support the Fire TV remote. Built for Fire OS / Android API 23 and later, landscape, no Google Play Services dependency. Vega OS devices require a different app and are not supported by this APK.

## Version 1.1.0

- Landscape artwork is explicitly assigned to the application and launcher activity.
- **More → Fullscreen TV mode** hides Qbeat's chrome and sidebar. The remote's Menu button shows/hides controls; Back returns to the normal layout. This keeps the app fullscreen and the screen awake, but does not disable Fire TV's Home button or lock the device to Qbeat.
- Subtitles default off, with a saved on/off preference under More. The player requests captions off and unloads its captions module when that API is available. Preferences or text embedded in the video itself can still affect what is shown. YouTube branding remains visible under its player rules.
- During the final ten seconds, a **Coming next** strip appears below the player when a next song is queued. It does not cover the YouTube video or skip its ending. The clock follows the player's actual position.
- Guest colours and icons appear with their tracks. The current guest's optional photo is shown alongside their name.

Install over version 1.0.0 to retain the host session. The same signing identity is used for updates. New native controls and launcher artwork require updating the APK; website changes arrive on refresh.

Public download: https://qbeat.stream/qbeat.apk?v=1.2.2

Installation guide: https://qbeat.stream/tv-app

## Version 1.2.2

Uses https://qbeat.stream on standard HTTPS port 443. The package identity and signing key are unchanged, so install over an existing version to retain the host session, TV pairing identity, and device preferences. Legacy IP endpoints remain served for older installed builds.

## Version 1.2.1

**More → Turn countdown on/off** toggles a saved remaining-time display below the video. It follows the player's actual position, freezes naturally on pause, and hides during introductions, unavailable-duration states, or playback errors. The shared web player and personal phone player also offer a locally saved countdown toggle. It is independent of the final-ten-second Coming next strip.

## Version 1.2.0

- Uses the HTTPS backend on port 8443; the backend IP certificate has automated renewal.
- **More → Music source / accounts** chooses the shared room or a playlist from an explicitly paired account. Link codes are created on the TV and entered on the authenticated personal page. No account password is entered or stored on the TV. The linked-account list is scoped to the TV's host session, and private playback does not mutate the room queue.
- **Compact player** uses a visible 356×200dp WebView, with more room for artist/song labels. Video remains visible while audio plays.
- Display labels use the backend's cleaned `display_title` and `display_artist` fields while the original title remains with the YouTube player. Guest icons appear to the right of names.
- Before loading each video, a two-second native introduction slides across the screen with **Picked by {name}** and a 160dp guest photo or icon. The previous player is paused; the main view is replaced until the introduction completes, and only then is the next video loaded. Introductions can be disabled under More. Navigating away, switching sources, or receiving a changed track cancels an in-progress introduction.
- The QR code switches to the secure personal page in personal TV mode.
- **Karaoke versions** is a search option on the phone. Lyrics and backing vocals come from the selected video; there is no independent vocal adjustment.

YouTube's recommendations and branding remain controlled by its official player. This build does not cover those controls or create a hidden audio-only player. Version 1.2.0's new native UI and animation require physical-device testing after installation; the build/signature, API isolation, and web flows are verified automatically.

## Build

Requires JDK 17+, Android SDK platform 35, Android build tools 35.0.0, Python 3, and Bash. The server has these under `/opt/qbeat-android/sdk`.

```sh
bash android/build.sh
```

Optional configuration: `ANDROID_SDK_ROOT` and `QBEAT_SIGNING_DIR`.

The release keystore and password are stored outside the repository in `/etc/qbeat-signing`. Both are root-readable only. Back them up securely; future APK updates must use the same signing key. The APK is written to `static/downloads/qbeat-fire-tv.apk`, alongside its SHA-256 checksum. Build outputs and signing files are ignored by Git.

To create a separate signing identity on another machine, use `keytool -genkeypair` with alias `qbeat`, place the keystore at `$QBEAT_SIGNING_DIR/qbeat-release.jks`, and store its password on the first line of `$QBEAT_SIGNING_DIR/password`. Do not overwrite this server's signing identity.

## Architecture

- Backend URL is a build-time constant in `MainActivity.java`: `https://qbeat.stream`.
- Host PIN is exchanged for a session cookie and is not stored. The session cookie is kept in app-private preferences. Sign out deletes it. No host PIN or YouTube API key is bundled in the APK.
- Network requests run on a single background executor. Queue polling happens every three seconds while the activity is visible. Leaving the app stops heartbeats and pauses local playback. Another player can acquire the lease after 15 seconds.
- The native activity exposes only player lifecycle events to a local HTML asset. The YouTube iframe remains visible with its controls. App client identity is provided through `loadDataWithBaseURL` using `https://com.tcdataconsultants.qbeat/`, following YouTube's documented WebView identity pattern. No video extraction or playback outside the official player is used.
- Media playback does not require a WebView user gesture. Device-specific playback restrictions can still apply. Playback errors show their exact code and preserve the queue for retry or a manual skip.
- The backend and YouTube resources use HTTPS. The manifest retains a legacy cleartext exception for the original backend IP, but versions 1.2.0–1.2.1 use secure port 8443 and 1.2.2 uses the domain on port 443.
- The native app keeps the display awake while visible. Back exits the video focus or prompts to leave; media play/pause controls the shared queue.

## Verification

```sh
bash android/build.sh                  # compiles Java/Dex/resources and verifies the APK signature
node tests/test_native_player.cjs       # exercises the WebView lifecycle bridge
.venv/bin/python -m unittest discover -s tests -v
```

APK compilation/signature and automated bridge/API tests do not establish physical Firestick compatibility. The user has confirmed earlier versions play on their Firestick. Version 1.2.0's new controls and layout still need physical-device verification; no Android emulator was used.

References: [Fire TV manifest support](https://developer.amazon.com/docs/fire-tv/add-tv-support-to-an-existing-react-native-project.html), [YouTube embedded player identity](https://developers.google.com/youtube/terms/required-minimum-functionality#api-client-identity-and-credentials).

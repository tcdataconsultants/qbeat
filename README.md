# Qbeat

A shared YouTube jukebox. Guests scan a QR code, add a song, and watch the shared queue. A host-controlled browser plays the queue on a TV.

## This server

- Guest page: https://qbeat.stream/
- Host controls: https://qbeat.stream/host
- TV player: https://qbeat.stream/player
- Canonical site: https://qbeat.stream/
- Personal accounts and private playlists: https://qbeat.stream/personal
- Fire TV app and installation guide: https://qbeat.stream/tv-app
- Source: `/srv/qbeat`
- Configuration and host PIN: `/etc/qbeat.env` (root only; never commit)
- SQLite database: `/var/lib/qbeat/queue.db`
- Service: `qbeat.service`
- Logs: `journalctl -u qbeat -n 100`
- Nginx: `/etc/nginx/sites-available/qbeat`

## Using it

1. Open `/player` on the TV browser, sign in with the host PIN, and select **Start player**. If the browser blocks sound, press Play inside the YouTube video.
2. Guests scan the QR on that screen. No account or installation is needed.
3. Guests paste a YouTube video link and select **Search**, then **Add**. With a YouTube Data API key configured, they can also search by artist or song.
4. Use `/host` to pause, resume, skip, remove queued tracks, or close requests.

Keep one TV player open. A second player must wait until the first has disconnected for 15 seconds. Queue updates arrive every three seconds. Tracks waiting and the current track survive restarts; a reconnected player restarts the current track from the beginning.

## Enable artist and song search

Create a Google Cloud project, enable **YouTube Data API v3**, and create an API key restricted to that API. Configure its IP restrictions for the server's outbound IP. Run:

```sh
sudo /srv/qbeat/.venv/bin/python /srv/qbeat/scripts/set-youtube-key.py
```

The prompt hides the key, writes it to `/etc/qbeat.env`, and restarts Qbeat. The key stays on the server. Search results are cached in SQLite for 24 hours and survive restarts; YouTube's API search quota can still be exhausted. Link lookup remains available without an API key. Artist/channel results are ignored when building playable results. Search cards show the video duration (or LIVE/Scheduled). Video lengths are retrieved with one batched videos.list request, cached for 24 hours, and never cause the whole search to fail if unavailable. Transient failures retry once; quota, key access, and connection failures have distinct messages and sanitized server logs. Error handling checks Google’s detailed quota metadata: a daily search limit stays a daily-limit message even when Google labels it rateLimitExceeded. Temporary throttling shows a retry delay and applies a short shared cooldown to new searches; cached searches and links remain available.

## Development

Requires Python 3.12+. Install dependencies into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export SESSION_SECRET="$(openssl rand -hex 32)"
export HOST_PIN=12345678
export DATABASE=/tmp/qbeat-dev/queue.db
export PUBLIC_URL=http://localhost:8091
.venv/bin/gunicorn --bind 127.0.0.1:8091 --workers 1 --threads 8 app:app
```

The production app expects a trusted reverse proxy that overwrites `X-Forwarded-For` and `X-Forwarded-Proto`. Keep the app server on loopback. One worker shares in-memory search caching and request rate limits; SQLite transactions serialize queue changes. A larger deployment should use a shared rate limit/cache service.

Run verification:

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
node tests/test_native_player.cjs
```

## Hosting and device notes

The canonical site is https://qbeat.stream on standard port 443. HTTP and www redirect to the canonical HTTPS host. Its domain certificate covers qbeat.stream and www.qbeat.stream and uses the same automated renewal service as the legacy IP certificate. Domain routing is in `/etc/nginx/sites-available/qbeat-domain` (tracked example: `deploy/nginx-domain.conf`). HTTPS session cookies are marked Secure; the legacy HTTP guest interface remains compatible. Existing browser accounts can sign in again on the new host, and native app 1.2.2 uses the domain directly.

Legacy HTTPS remains enabled on port 8443 with a publicly trusted Let's Encrypt IP certificate. Port 8090 remains available for existing shared-room clients. Personal account endpoints require HTTPS and use a separate Secure, HttpOnly, SameSite cookie with a random session token; only token hashes are stored. Passwords are hashed with Werkzeug's scrypt default. Account sessions last 30 days and sign-out revokes the current token. Password recovery uses a one-time recovery code shown on account creation, with no email service required; reset rotates that code and revokes existing sessions.

The certificate is stored in `/etc/letsencrypt-qbeat`, separate from other applications' certificates. `qbeat-certificate-renew.timer` checks twice daily using `/opt/qbeat-certbot/bin/certbot`; successful renewal calls `/usr/local/sbin/qbeat-reload-tls`. An HTTP-01 challenge location was added to the active `/etc/nginx/sites-enabled/daytripr` server on port 80, serving only `/var/www/qbeat-acme/.well-known/acme-challenge/`. Preserve that location for renewals. A renewal dry run passed when HTTPS was installed. IP certificates are short lived, so keep the timer enabled. The public QR follows `PUBLIC_URL` in `/etc/qbeat.env`.

Use the native Fire TV app or a browser to open the player URL. The user has confirmed earlier native builds play on their Firestick; new 1.2.0 features still need device testing. A laptop connected by HDMI can also run the browser player. Playback uses YouTube's official visible iframe player; ads, regional restrictions, embedding restrictions, and device browser policies still apply. Playback errors show the exact YouTube code and preserve the current track for retry or a host skip. The last 100 shared-room errors are recorded for diagnosis. Guest requests do not start audio on the phone; personal mode explicitly plays there when selected.

Guest additions are limited to three waiting tracks per browser, duplicate active videos are rejected, and the whole queue is capped at 100. This is a simple shared room; it does not yet support separate venues, votes, or moderation approval.

Guests can open **Make it yours** to save a display name, name colour, and icon. An optional selfie is resized to 256×256 JPEG, stripped of image metadata, and stored under `/var/lib/qbeat/avatars`. Uploaded photos are visible to room visitors in the queue and can be removed by the guest from the same browser. Only a guest's session can edit their profile. Back up the avatars directory with the database if you want photos retained. The phone layout uses compact guest controls and 16px inputs to avoid iOS focus zoom.

The native Fire TV app source, build steps, signing arrangements, and device testing limitations are documented in [android/README.md](android/README.md).

## Personal listening and TV accounts

Open **My music** to create an account and private playlists. A playlist can contain up to 200 tracks; an account can have up to 50 playlists. Phone playback uses an independent visible YouTube player and never submits songs to the shared room. Playback pauses when the page is hidden or the video scrolls out of view. Keep the recovery code shown during signup; a forgotten password cannot be reset by email.

On Fire TV app 1.2.0 or later, choose **More → Music source / accounts → Link an account**. On the phone, use **Link to TV** and enter the eight-character code. Codes expire after ten minutes and are single use. The TV lists only accounts explicitly paired with its host session. Select the paired account and one of its playlists to play privately on that TV. Personal TV playback has its own cursor/pause state and leaves the room queue unchanged. Choose **Shared room queue** to return. Remove TV access from the personal page at any time.

Guest icons include 💖 and appear after the guest's name. Qbeat's display labels conservatively infer artist/song from the YouTube title and channel; source titles are retained unchanged. Labels may be imperfect when the upload does not name the artist and song clearly. Shared-room web playback and TV app 1.2.0 show a two-second animated picked-by introduction before loading a new track, using the guest's selfie or icon. The TV setting can turn introductions off.

**Compact player** leaves the YouTube video visible with at least a 200px-by-200px viewport. There is no hidden/audio-only mode, and YouTube branding or all related-video suggestions cannot be disabled. Automatic playlist/queue advancement continues. **Karaoke versions** searches for backing-track videos with lyrics already synchronized in the video; Qbeat does not extract audio, supply lyric timing, or independently adjust vocals in a YouTube recording.

The TV app (1.2.1+), shared browser player, and personal phone player have an optional countdown. It displays remaining time outside the video, follows the player clock, and saves its on/off preference on the device. On TV use **More → Turn countdown on/off**. This is separate from the Coming next notice.

Back up `/var/lib/qbeat/queue.db` using SQLite's backup API and keep `/etc/qbeat.env` securely backed up separately. Never commit either file.

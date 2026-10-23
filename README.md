# Qbeat

A shared YouTube jukebox. Guests scan a QR code, add a song, and watch the shared queue. A host-controlled browser plays the queue on a TV.

## This server

- Guest page: http://89.167.98.40:8090/
- Host controls: http://89.167.98.40:8090/host
- TV player: http://89.167.98.40:8090/player
- Fire TV app and installation guide: http://89.167.98.40:8090/tv-app
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

The prompt hides the key, writes it to `/etc/qbeat.env`, and restarts Qbeat. The key stays on the server. Search results are cached in SQLite for 24 hours and survive restarts; YouTube's API search quota can still be exhausted. Link lookup remains available without an API key. Artist/channel results are ignored when building playable results. Transient failures retry once; quota, key access, and connection failures have distinct messages and sanitized server logs.

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

The initial address uses HTTP. For regular use, attach a domain with HTTPS, set `PUBLIC_URL` to that address and `COOKIE_SECURE=1` in `/etc/qbeat.env`, then restart. The QR code follows `PUBLIC_URL`.

Use a browser on the TV or Firestick to open the player URL. Physical Firestick compatibility has not been verified. A laptop connected by HDMI can also run the same page. Playback uses YouTube's official visible iframe player; ads, regional restrictions, embedding restrictions, and device browser policies still apply. Playback errors show the exact YouTube code and preserve the current track for retry or a host skip. The last 100 errors are recorded for diagnosis. Guest devices don't play audio themselves.

Guest additions are limited to three waiting tracks per browser, duplicate active videos are rejected, and the whole queue is capped at 100. This is a simple shared room; it does not yet support separate venues, votes, or moderation approval.

Guests can open **Make it yours** to save a display name, name colour, and icon. An optional selfie is resized to 256×256 JPEG, stripped of image metadata, and stored under `/var/lib/qbeat/avatars`. Uploaded photos are visible to room visitors in the queue and can be removed by the guest from the same browser. Only a guest's session can edit their profile. Back up the avatars directory with the database if you want photos retained. The phone layout uses compact guest controls and 16px inputs to avoid iOS focus zoom.

The native Fire TV app source, build steps, signing arrangements, and device testing limitations are documented in [android/README.md](android/README.md).

Back up `/var/lib/qbeat/queue.db` using SQLite's backup API and keep `/etc/qbeat.env` securely backed up separately. Never commit either file.

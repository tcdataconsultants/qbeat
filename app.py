import html
import base64
import binascii
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

import qrcode
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import Flask, request, jsonify, session, send_file, send_from_directory
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__, static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)


class QbeatSessionInterface(SecureCookieSessionInterface):
    def get_cookie_secure(self, application):
        return request.is_secure or super().get_cookie_secure(application)


app.session_interface = QbeatSessionInterface()
app.secret_key = os.environ['SESSION_SECRET']
app.config.update(MAX_CONTENT_LENGTH=524288, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1')
DB = os.getenv('DATABASE', '/var/lib/qbeat/queue.db')
PUBLIC_URL = os.getenv('PUBLIC_URL', 'https://qbeat.stream').rstrip('/')
HOST_PIN = os.environ['HOST_PIN']
API_KEY = os.getenv('YOUTUBE_API_KEY', '')
lock = threading.Lock()
hits = defaultdict(deque)
cache = {}
search_locks = [threading.Lock() for _ in range(64)]
COLORS = ('#d6fa77', '#b2a0ed', '#ffb3c6', '#79d9f2', '#ffc978', '#91e5b0', '#f2f0e9', '#ff9d85')
ICONS = ('♫', '🎧', '🎸', '🎤', '🪩', '✨', '🌴', '🦊', '🐱', '🔥', '💃', '🚀', '💖')
AVATAR_DIR = os.path.join(os.path.dirname(DB), 'avatars')


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS songs (
          id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, title TEXT NOT NULL,
          artist TEXT NOT NULL, guest TEXT NOT NULL, guest_id TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS active_video ON songs(video_id)
          WHERE status IN ('queued','playing');
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1),
          paused INTEGER DEFAULT 0, accepting INTEGER DEFAULT 1,
          player TEXT DEFAULT '', heartbeat REAL DEFAULT 0);
        INSERT OR IGNORE INTO settings(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS player_events (
          id INTEGER PRIMARY KEY, song_id INTEGER, code INTEGER NOT NULL,
          browser TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS search_cache (
          query TEXT PRIMARY KEY, results TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS profiles (
          id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#d6fa77',
          icon TEXT NOT NULL DEFAULT '♫', photo TEXT);
        CREATE TABLE IF NOT EXISTS video_details (
          video_id TEXT PRIMARY KEY, seconds INTEGER, label TEXT NOT NULL, is_live INTEGER NOT NULL DEFAULT 0,
          expires REAL NOT NULL);
        ''')


def limited(bucket, limit, seconds):
    now = time.time()
    with lock:
        if len(hits) > 10000:
            for key in list(hits):
                if not hits[key] or hits[key][-1] < now - 3600:
                    del hits[key]
        q = hits[bucket]
        while q and q[0] < now - seconds:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
    return False


def remote_json(url):
    with urlopen(url, timeout=8) as r:
        return json.load(r)


def video_id(value):
    value = str(value).strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        return value
    u = urlparse(value)
    host = (u.hostname or '').lower()
    if host in ('youtu.be', 'www.youtu.be'):
        value = u.path.strip('/').split('/')[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        value = parse_qs(u.query).get('v', [''])[0]
        if u.path.startswith(('/shorts/', '/embed/', '/live/')):
            value = u.path.split('/')[2]
    else:
        return None
    return value if re.fullmatch(r'[A-Za-z0-9_-]{11}', value) else None


def metadata(vid):
    key = 'video:' + vid
    if key in cache and cache[key][0] > time.time():
        return cache[key][1]
    data = remote_json('https://www.youtube.com/oembed?' + urlencode({
        'url': 'https://www.youtube.com/watch?v=' + vid, 'format': 'json'}))
    result = dict(video_id=vid, title=data['title'][:250], artist=data.get('author_name', 'YouTube')[:150])
    cache[key] = (time.time() + 3600, result)
    return result


def error(message, status=400):
    return jsonify(error=message), status


def format_track(song):
    """Conservative display labels; retain the unmodified YouTube source title."""
    item = dict(song)
    raw = html.unescape(str(item.get('title', '')))
    artist = html.unescape(str(item.get('artist', 'YouTube')))
    artist = re.sub(r'\s*-\s*Topic$|VEVO$', '', artist, flags=re.I).strip()
    label = re.sub(r'\s*[\[(](?:official\s+(?:music\s+)?(?:video|audio|visuali[sz]er)|(?:official\s+)?lyric(?:s|\s+video)?|(?:full\s+)?HD|4K|visuali[sz]er)[\])]\s*', ' ', raw, flags=re.I)
    label = re.sub(r'\s*[-–—]?\s*official\s+(?:music\s+)?(?:video|audio)\s*$', '', label, flags=re.I).strip()
    parts = re.split(r'\s+[-–—]\s+', label, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artist, label = parts[0].strip(), parts[1].strip()
    item.update(display_title=label.strip(' "“”') or raw, display_artist=artist or item.get('artist', 'YouTube'))
    return item


def parse_duration(value):
    match = re.fullmatch(r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?', str(value))
    if not match or not any(part is not None for part in match.groups()):
        return None
    days, hours, minutes, seconds = (float(v or 0) for v in match.groups())
    return int(days*86400 + hours*3600 + minutes*60 + seconds)


def duration_label(seconds):
    if seconds is None or seconds <= 0:
        return 'Length unavailable'
    hours, remaining = divmod(seconds, 3600)
    minutes, secs = divmod(remaining, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def enrich_durations(results):
    """One batched video-details request; duration failures never discard songs."""
    if not results:
        return results
    ids = list(dict.fromkeys(item['video_id'] for item in results))
    placeholders = ','.join('?' for _ in ids)
    with db() as c:
        saved = {r['video_id']: dict(r) for r in c.execute('SELECT * FROM video_details WHERE video_id IN ('+placeholders+') AND expires>?', (*ids, time.time()))}
    missing = [vid for vid in ids if vid not in saved]
    if missing and API_KEY:
        fetched = {}
        try:
            details = remote_json('https://www.googleapis.com/youtube/v3/videos?' + urlencode(dict(
                key=API_KEY, part='contentDetails,snippet', id=','.join(missing),
                fields='items(id,contentDetails(duration),snippet(liveBroadcastContent))')))
            for item in details.get('items', []):
                vid = item.get('id') if isinstance(item, dict) else None
                if not isinstance(vid, str) or vid not in missing:
                    continue
                live = (item.get('snippet') or {}).get('liveBroadcastContent')
                seconds = parse_duration((item.get('contentDetails') or {}).get('duration'))
                label = 'LIVE' if live == 'live' else 'Scheduled' if live == 'upcoming' else duration_label(seconds)
                fetched[vid] = dict(seconds=seconds if live not in ('live', 'upcoming') else None,
                                    label=label, is_live=int(live == 'live'), expires=time.time()+86400)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            app.logger.warning('YouTube durations unavailable status=%s', getattr(exc, 'code', type(exc).__name__))
        with db() as c:
            for vid in missing:
                detail = fetched.get(vid, dict(seconds=None, label='Length unavailable', is_live=0, expires=time.time()+120))
                c.execute('INSERT OR REPLACE INTO video_details VALUES(?,?,?,?,?)', (vid, detail['seconds'], detail['label'], detail['is_live'], detail['expires']))
                saved[vid] = detail
            c.execute('DELETE FROM video_details WHERE expires<?', (time.time(),))
    for item in results:
        detail = saved.get(item['video_id'], {})
        item.update(duration_seconds=detail.get('seconds'), duration_label=detail.get('label', 'Length unavailable'), is_live=bool(detail.get('is_live', False)))
    return results


@app.before_request
def guard():
    if 'guest_id' not in session:
        session['guest_id'] = secrets.token_urlsafe(18)
    if request.method in ('POST', 'DELETE'):
        if not request.is_json:
            return error('Send JSON.', 415)
        origin = request.headers.get('Origin')
        if origin and origin not in (PUBLIC_URL, request.host_url.rstrip('/')):
            return error('Request origin rejected.', 403)
    if request.path.startswith('/api/host/') and not session.get('host'):
        return error('Host sign-in required.', 401)
    if request.path.startswith('/api/host/'):
        session.setdefault('tv_id', secrets.token_urlsafe(24))


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
@app.get('/host')
@app.get('/player')
def page():
    return send_from_directory('static', 'index.html')


@app.get('/qr.png')
def qr():
    out = io.BytesIO()
    target = PUBLIC_URL + '/personal' if request.args.get('target') == 'personal' else PUBLIC_URL + '/'
    qrcode.make(target).save(out, format='PNG')
    out.seek(0)
    return send_file(out, mimetype='image/png')


@app.get('/tv-app')
def tv_app_page():
    return send_from_directory('static', 'tv-app.html')


@app.get('/qbeat.apk')
def tv_app_download():
    return send_from_directory('static/downloads', 'qbeat-fire-tv.apk',
                               mimetype='application/vnd.android.package-archive',
                               as_attachment=True, download_name='Qbeat-Fire-TV.apk')


@app.get('/api/state')
def state():
    with db() as c:
        settings = dict(c.execute('SELECT * FROM settings WHERE id=1').fetchone())
        songs = [format_track(dict(r)) for r in c.execute("""SELECT s.id,s.video_id,s.title,s.artist,s.status,
            CASE WHEN p.name IS NOT NULL AND p.name!='' THEN p.name ELSE s.guest END AS guest,
            COALESCE(p.color,'#d6fa77') AS guest_color,COALESCE(p.icon,'♫') AS guest_icon,
            CASE WHEN p.photo IS NOT NULL THEN '/avatars/'||p.photo ELSE NULL END AS guest_photo
            FROM songs s LEFT JOIN profiles p ON p.id=s.guest_id
            WHERE s.status IN ('queued','playing') ORDER BY s.id""")]
        last_error = c.execute('SELECT song_id,code,browser,created FROM player_events ORDER BY id DESC LIMIT 1').fetchone() if session.get('host') else None
    return jsonify(now=next((s for s in songs if s['status'] == 'playing'), None),
                   queue=[s for s in songs if s['status'] == 'queued'],
                   paused=bool(settings['paused']), accepting=bool(settings['accepting']),
                   player_online=time.time() - settings['heartbeat'] < 15,
                   host=bool(session.get('host')), search_enabled=bool(API_KEY), guest_url=PUBLIC_URL + '/',
                   last_player_error=dict(last_error) if last_error else None)


def guest_profile():
    with db() as c:
        row = c.execute('SELECT name,color,icon,photo FROM profiles WHERE id=?', (session['guest_id'],)).fetchone()
    profile = dict(row) if row else dict(name='', color=COLORS[0], icon=ICONS[0], photo=None)
    if profile['photo']:
        profile['photo'] = '/avatars/' + profile['photo']
    return profile


@app.get('/api/profile')
def profile_get():
    return jsonify(profile=guest_profile(), colors=COLORS, icons=ICONS)


@app.post('/api/profile')
def profile_update():
    data = request.get_json() or {}
    name = str(data.get('name', '')).strip()[:30]
    color = data.get('color', COLORS[0])
    icon = data.get('icon', ICONS[0])
    if color not in COLORS or icon not in ICONS:
        return error('Choose one of the available colours and icons.')
    with db() as c:
        c.execute('INSERT INTO profiles(id,name,color,icon) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,color=excluded.color,icon=excluded.icon',
                  (session['guest_id'], name, color, icon))
    return jsonify(profile=guest_profile())


@app.post('/api/profile/photo')
def profile_photo():
    if limited(('photo', session['guest_id']), 8, 60):
        return error('Please wait a minute before changing your photo again.', 429)
    value = (request.get_json() or {}).get('photo')
    filename = None
    if value is not None:
        if not isinstance(value, str) or len(value) > 280000:
            return error('The photo is too large. Choose a smaller image.', 413)
        match = re.fullmatch(r'data:image/(?:jpeg|png|webp);base64,([A-Za-z0-9+/=]+)', value)
        if not match:
            return error('Choose a JPEG, PNG, or WebP photo.')
        try:
            raw = base64.b64decode(match.group(1), validate=True)
            image = Image.open(io.BytesIO(raw))
            if image.width * image.height > 16000000:
                return error('The photo resolution is too large.')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image = ImageOps.fit(image, (256, 256), method=Image.Resampling.LANCZOS)
        except (binascii.Error, UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            return error('We couldn’t read that photo. Try a different image.')
        os.makedirs(AVATAR_DIR, exist_ok=True)
        filename = secrets.token_hex(16) + '.jpg'
        image.save(os.path.join(AVATAR_DIR, filename), 'JPEG', quality=85)
    with db() as c:
        old = c.execute('SELECT photo FROM profiles WHERE id=?', (session['guest_id'],)).fetchone()
        c.execute('INSERT INTO profiles(id,photo) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET photo=excluded.photo', (session['guest_id'], filename))
    if old and old['photo']:
        try:
            os.unlink(os.path.join(AVATAR_DIR, old['photo']))
        except FileNotFoundError:
            pass
    return jsonify(profile=guest_profile())


@app.get('/avatars/<filename>')
def avatar(filename):
    if not re.fullmatch(r'[a-f0-9]{32}\.jpg', filename):
        return error('Photo not found.', 404)
    return send_from_directory(AVATAR_DIR, filename, mimetype='image/jpeg', max_age=3600)


@app.post('/api/login')
def login():
    if limited(('login', request.remote_addr), 10, 300):
        return error('Too many attempts. Try again in five minutes.', 429)
    if not secrets.compare_digest(str((request.get_json() or {}).get('pin', '')), HOST_PIN):
        return error('Incorrect host PIN.', 401)
    session['host'] = True
    return jsonify(ok=True)


@app.post('/api/host/logout')
def logout():
    session.pop('host', None)
    return jsonify(ok=True)


@app.get('/api/search')
def search():
    q = ' '.join(request.args.get('q', '').split())[:160]
    if len(q) < 2:
        return error('Enter an artist, song, or YouTube link.')
    if limited(('search', request.remote_addr), 20, 60):
        return error('Please wait a moment before searching again.', 429)
    try:
        is_link = bool(re.match(r'^(https?://|www\.|youtube\.com/|m\.youtube\.com/|music\.youtube\.com/|youtu\.be/)', q, re.I))
        if is_link:
            link = q if re.match(r'^https?://', q, re.I) else 'https://' + q
            vid = video_id(link)
            if not vid:
                return error('Paste a link to a single YouTube video, or search by song and artist.', 422)
            try:
                return jsonify(results=enrich_durations([metadata(vid)]))
            except HTTPError as e:
                if e.code in (400, 401, 403, 404):
                    return error('That YouTube video is unavailable or private. Try a different link.', 422)
                raise
        if not API_KEY:
            return error('Song search needs a YouTube API key. For now, paste a YouTube video link above.', 503)
        karaoke = request.args.get('karaoke') == '1'
        key = q.casefold() + ('|karaoke' if karaoke else '')
        with search_locks[hash(key) % len(search_locks)]:
            with db() as c:
                saved = c.execute('SELECT results FROM search_cache WHERE query=? AND expires>?', (key, time.time())).fetchone()
            if saved:
                return jsonify(results=enrich_durations(json.loads(saved['results'])), cached=True)
            url = 'https://www.googleapis.com/youtube/v3/search?' + urlencode(dict(
                key=API_KEY, part='snippet', type='video', videoEmbeddable='true',
                videoCategoryId='10', safeSearch='moderate', maxResults=12, q=(q + ' karaoke lyrics') if karaoke else q))
            for attempt in range(2):
                try:
                    data = remote_json(url)
                    break
                except HTTPError as e:
                    if attempt == 0 and e.code in (500, 502, 503, 504):
                        time.sleep(0.2)
                        continue
                    raise
                except (URLError, TimeoutError):
                    if attempt == 0:
                        time.sleep(0.2)
                        continue
                    raise
            results = []
            for item in data.get('items', []):
                if not isinstance(item, dict):
                    continue
                identity = item.get('id') or {}
                snippet = item.get('snippet') or {}
                if not isinstance(identity, dict) or not isinstance(snippet, dict):
                    continue
                vid = identity.get('videoId')
                title = snippet.get('title')
                artist = snippet.get('channelTitle', 'YouTube')
                if not isinstance(vid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid) or not isinstance(title, str):
                    continue
                results.append(dict(video_id=vid, title=html.unescape(title),
                                    artist=html.unescape(artist) if isinstance(artist, str) else 'YouTube'))
            results = enrich_durations(results)
            with db() as c:
                c.execute('INSERT OR REPLACE INTO search_cache(query,results,expires) VALUES(?,?,?)',
                          (key, json.dumps(results), time.time() + 86400))
                c.execute('DELETE FROM search_cache WHERE expires<?', (time.time(),))
            return jsonify(results=results, cached=False)
    except HTTPError as e:
        try:
            details = json.load(e).get('error', {})
            reasons = {v.get('reason', '') for v in details.get('errors', [])}
            reasons.add(details.get('status', ''))
        except (ValueError, AttributeError, TypeError):
            reasons = set()
        safe_reasons = ','.join(sorted(re.sub(r'[^A-Za-z0-9_.-]', '', str(v))[:80] for v in reasons if v))
        app.logger.warning('YouTube search failed status=%s reasons=%s', e.code, safe_reasons or 'unspecified')
        if reasons & {'quotaExceeded', 'dailyLimitExceeded', 'RESOURCE_EXHAUSTED'}:
            return error('YouTube’s daily search allowance has been used. Try a previously searched artist or paste a YouTube video link. New searches return after the quota resets.', 503)
        if reasons & {'rateLimitExceeded', 'userRateLimitExceeded'} or e.code == 429:
            return error('YouTube is receiving too many search requests. Wait a minute and try again, or paste a YouTube link.', 429)
        if e.code in (400, 401, 403):
            return error('YouTube search access was rejected. The host should check the API key, API restrictions, and that YouTube Data API v3 is enabled. You can still paste a video link.', 503)
        return error('YouTube search is temporarily unavailable. Please retry in a moment or paste a YouTube video link.', 502)
    except (URLError, TimeoutError):
        app.logger.warning('YouTube search connection timed out or was unavailable')
        return error('YouTube did not respond in time. Please try again, or paste a YouTube video link.', 504)
    except (ValueError, KeyError, TypeError):
        app.logger.warning('YouTube search returned an invalid response')
        return error('YouTube returned an unreadable search response. Please try again.', 502)


@app.post('/api/queue')
def add():
    if limited(('add', request.remote_addr), 15, 60):
        return error('Too many requests. Please wait a minute.', 429)
    data = request.get_json() or {}
    vid = video_id(data.get('video_id', ''))
    if not vid:
        return error('Choose a valid YouTube video.')
    try:
        song = metadata(vid)
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError):
        return error('This video is unavailable. Try another song.', 422)
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT accepting FROM settings').fetchone()[0]:
                return error('The host has closed song requests.', 403)
            if c.execute("SELECT COUNT(*) FROM songs WHERE status IN ('queued','playing')").fetchone()[0] >= 100:
                return error('The queue is full. Try again after a few songs.')
            if c.execute("SELECT COUNT(*) FROM songs WHERE guest_id=? AND status='queued'", (session['guest_id'],)).fetchone()[0] >= 3:
                return error('You already have three songs waiting. Let someone else pick!')
            c.execute('INSERT INTO songs(video_id,title,artist,guest,guest_id,created) VALUES(?,?,?,?,?,?)',
                      (vid, song['title'], song['artist'], str(data.get('guest', 'Guest')).strip()[:30] or 'Guest', session['guest_id'], time.time()))
        return jsonify(ok=True), 201
    except sqlite3.IntegrityError:
        return error('That song is already playing or in the queue.', 409)


@app.post('/api/host/control')
def control():
    data = request.get_json() or {}
    personal_response = app.tv_control(data)
    if personal_response is not None:
        return personal_response
    action = data.get('action')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if action == 'pause':
            c.execute('UPDATE settings SET paused=1 WHERE id=1')
        elif action == 'resume':
            c.execute('UPDATE settings SET paused=0 WHERE id=1')
        elif action == 'requests':
            c.execute('UPDATE settings SET accepting=? WHERE id=1', (int(bool(data.get('enabled'))),))
        elif action == 'remove':
            c.execute("UPDATE songs SET status='removed' WHERE id=? AND status='queued'", (data.get('id'),))
        elif action == 'skip':
            c.execute("UPDATE songs SET status='skipped' WHERE status='playing'")
            c.execute("UPDATE songs SET status='playing' WHERE id=(SELECT MIN(id) FROM songs WHERE status='queued')")
        else:
            return error('Unknown control.')
    return jsonify(ok=True)


@app.post('/api/host/player')
def player():
    data = request.get_json() or {}
    personal_response = app.tv_player(data)
    if personal_response is not None:
        return personal_response
    client = str(data.get('client', ''))[:80]
    if not client:
        return error('Missing player identity.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        s = c.execute('SELECT * FROM settings WHERE id=1').fetchone()
        if s['player'] != client and time.time() - s['heartbeat'] < 15:
            return error('Another TV player is active. Close it and wait 15 seconds before starting this one.', 409)
        c.execute('UPDATE settings SET player=?,heartbeat=? WHERE id=1', (client, time.time()))
        current = c.execute("SELECT id FROM songs WHERE status='playing'").fetchone()
        if data.get('error_code') is not None:
            code = data['error_code']
            if type(code) is not int or code not in (2, 5, 100, 101, 150, 153):
                return error('Unknown player error code.')
            if current and current['id'] == data.get('song_id'):
                c.execute('INSERT INTO player_events(song_id,code,browser,created) VALUES(?,?,?,?)',
                          (current['id'], code, request.user_agent.string[:300], time.time()))
                c.execute('DELETE FROM player_events WHERE id <= (SELECT MAX(id)-100 FROM player_events)')
                app.logger.warning('YouTube player error code=%s song_id=%s browser=%s', code, current['id'], request.user_agent.string[:300])
        if data.get('ended') is not None and current and current['id'] == data['ended']:
            c.execute("UPDATE songs SET status='played' WHERE id=?", (current['id'],))
            current = None
        if not current and not s['paused']:
            c.execute("UPDATE songs SET status='playing' WHERE id=(SELECT MIN(id) FROM songs WHERE status='queued')")
    return jsonify(ok=True)


@app.get('/health')
def health():
    with db() as c:
        c.execute('SELECT 1 FROM settings')
    return jsonify(ok=True)


init()
from personal import register_personal
register_personal(app, db, lambda vid: metadata(vid), error, limited, format_track)

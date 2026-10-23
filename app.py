import html
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
from flask import Flask, request, jsonify, session, send_file, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__, static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = os.environ['SESSION_SECRET']
app.config.update(MAX_CONTENT_LENGTH=8192, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE') == '1')
DB = os.getenv('DATABASE', '/var/lib/qbeat/queue.db')
PUBLIC_URL = os.getenv('PUBLIC_URL', 'http://89.167.98.40:8090').rstrip('/')
HOST_PIN = os.environ['HOST_PIN']
API_KEY = os.getenv('YOUTUBE_API_KEY', '')
lock = threading.Lock()
hits = defaultdict(deque)
cache = {}


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
    qrcode.make(PUBLIC_URL + '/').save(out, format='PNG')
    out.seek(0)
    return send_file(out, mimetype='image/png')


@app.get('/api/state')
def state():
    with db() as c:
        settings = dict(c.execute('SELECT * FROM settings WHERE id=1').fetchone())
        songs = [dict(r) for r in c.execute("SELECT id,video_id,title,artist,guest,status FROM songs WHERE status IN ('queued','playing') ORDER BY id")]
    return jsonify(now=next((s for s in songs if s['status'] == 'playing'), None),
                   queue=[s for s in songs if s['status'] == 'queued'],
                   paused=bool(settings['paused']), accepting=bool(settings['accepting']),
                   player_online=time.time() - settings['heartbeat'] < 15,
                   host=bool(session.get('host')), search_enabled=bool(API_KEY), guest_url=PUBLIC_URL + '/')


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
    q = request.args.get('q', '').strip()[:160]
    if len(q) < 2:
        return error('Enter an artist, song, or YouTube link.')
    if limited(('search', request.remote_addr), 20, 60):
        return error('Please wait a moment before searching again.', 429)
    try:
        vid = video_id(q)
        if vid:
            return jsonify(results=[metadata(vid)])
        if not API_KEY:
            return error('Song search needs a YouTube API key. For now, paste a YouTube video link above.', 503)
        key = 'search:' + q.lower()
        if key in cache and cache[key][0] > time.time():
            return jsonify(results=cache[key][1])
        data = remote_json('https://www.googleapis.com/youtube/v3/search?' + urlencode(dict(
            key=API_KEY, part='snippet', type='video', videoEmbeddable='true',
            videoCategoryId='10', safeSearch='moderate', maxResults=12, q=q)))
        results = [dict(video_id=v['id']['videoId'], title=html.unescape(v['snippet']['title']),
                        artist=html.unescape(v['snippet']['channelTitle'])) for v in data.get('items', [])]
        if len(cache) > 1000:
            cache.clear()
        cache[key] = (time.time() + 900, results)
        return jsonify(results=results)
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError):
        return error('YouTube could not return this request. Check the link, or try again later. Search may have reached its daily limit.', 502)


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

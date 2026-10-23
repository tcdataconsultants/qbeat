"""Private accounts, playlists, and explicitly paired TV sources."""
import hashlib
import re
import secrets
import sqlite3
import time
from functools import wraps
from flask import Blueprint, request, jsonify, session, g, send_from_directory, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.error import HTTPError, URLError


def register_personal(app, db, metadata, error, limited, format_track):
    bp = Blueprint('personal', __name__)
    secure_url = 'https://89.167.98.40:8443'
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
          password_hash TEXT NOT NULL, recovery_hash TEXT NOT NULL, guest_id TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS personal_sessions (
          token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS playlists (
          id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, name TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS playlist_tracks (
          id INTEGER PRIMARY KEY, playlist_id INTEGER NOT NULL, video_id TEXT NOT NULL,
          title TEXT NOT NULL, artist TEXT NOT NULL, created REAL NOT NULL, UNIQUE(playlist_id,video_id));
        CREATE TABLE IF NOT EXISTS tv_accounts (
          tv_id TEXT NOT NULL, account_id INTEGER NOT NULL, created REAL NOT NULL, PRIMARY KEY(tv_id,account_id));
        CREATE TABLE IF NOT EXISTS tv_pairs (
          code TEXT PRIMARY KEY, tv_id TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tv_sources (
          tv_id TEXT PRIMARY KEY, playlist_id INTEGER NOT NULL, after_track INTEGER NOT NULL DEFAULT 0,
          paused INTEGER NOT NULL DEFAULT 0, client TEXT NOT NULL DEFAULT '', heartbeat REAL NOT NULL DEFAULT 0);
        ''')

    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def account():
        token = request.cookies.get('qbeat_account', '')
        if not token:
            return None
        with db() as c:
            row = c.execute('SELECT a.* FROM accounts a JOIN personal_sessions s ON s.account_id=a.id WHERE s.token_hash=? AND s.expires>?', (digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def auth(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            g.account = account()
            if not g.account:
                return error('Sign in to use your private playlists.', 401)
            return fn(*args, **kwargs)
        return wrapped

    @bp.before_request
    def secure_accounts():
        if (request.path.startswith('/api/personal/') or request.path.startswith('/api/host/tv/')) and not request.is_secure and not app.testing:
            return error('Use the secure Qbeat personal page at ' + secure_url + '/personal.', 426)

    def issue_session(account_id, **extra):
        token = secrets.token_urlsafe(32)
        with db() as c:
            c.execute('DELETE FROM personal_sessions WHERE expires<?', (time.time(),))
            c.execute('INSERT INTO personal_sessions VALUES(?,?,?)', (digest(token), account_id, time.time() + 30*86400))
        response = jsonify(ok=True, **extra)
        response.set_cookie('qbeat_account', token, max_age=30*86400, secure=True, httponly=True, samesite='Lax', path='/')
        return response

    def credentials():
        d = request.get_json() or {}
        return d, str(d.get('username', '')).strip().lower(), str(d.get('password', ''))

    @bp.get('/personal')
    def page():
        if not request.is_secure and not app.testing:
            return redirect(secure_url + '/personal', code=302)
        response = send_from_directory(app.static_folder, 'personal.html')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.get('/api/personal/me')
    def me():
        user = account()
        return jsonify(account=dict(id=user['id'], username=user['username'], display_name=user['display_name']) if user else None)

    @bp.post('/api/personal/signup')
    def signup():
        if limited(('signup', request.remote_addr), 5, 3600):
            return error('Too many sign-up attempts. Try again later.', 429)
        data, username, password = credentials()
        if not re.fullmatch(r'[a-z0-9_]{3,30}', username):
            return error('Use 3–30 letters, numbers, or underscores for your username.')
        if len(password) < 12 or len(password) > 128:
            return error('Use a password of 12–128 characters.')
        display = str(data.get('display_name', username)).strip()[:30] or username
        recovery = secrets.token_urlsafe(24)
        password_hash = generate_password_hash(password)
        try:
            with db() as c:
                cur = c.execute('INSERT INTO accounts(username,display_name,password_hash,recovery_hash,guest_id,created) VALUES(?,?,?,?,?,?)',
                                (username, display, password_hash, digest(recovery), session['guest_id'], time.time()))
                account_id = cur.lastrowid
        except sqlite3.IntegrityError:
            return error('That username is already taken.', 409)
        return issue_session(account_id, recovery_code=recovery)

    @bp.post('/api/personal/signin')
    def signin():
        _, username, password = credentials()
        if limited(('signin', request.remote_addr), 15, 300):
            return error('Too many sign-in attempts. Try again in five minutes.', 429)
        if len(password) > 128:
            return error('Incorrect username or password.', 401)
        with db() as c:
            row = c.execute('SELECT id,password_hash FROM accounts WHERE username=?', (username,)).fetchone()
        if not row or not check_password_hash(row['password_hash'], password):
            return error('Incorrect username or password.', 401)
        return issue_session(row['id'])

    @bp.post('/api/personal/signout')
    def signout():
        token = request.cookies.get('qbeat_account', '')
        with db() as c:
            c.execute('DELETE FROM personal_sessions WHERE token_hash=?', (digest(token),))
        response = jsonify(ok=True)
        response.delete_cookie('qbeat_account', secure=True, httponly=True, samesite='Lax')
        return response

    @bp.post('/api/personal/recover')
    def recover():
        data, username, password = credentials()
        if limited(('recover', request.remote_addr), 5, 3600):
            return error('Too many recovery attempts. Try again later.', 429)
        recovery = str(data.get('recovery_code', '')).strip()[:100]
        if not 12 <= len(password) <= 128:
            return error('Use a new password of 12–128 characters.')
        with db() as c:
            row = c.execute('SELECT id,recovery_hash FROM accounts WHERE username=?', (username,)).fetchone()
        if not row or not secrets.compare_digest(row['recovery_hash'], digest(recovery)):
            return error('Incorrect username or recovery code.', 401)
        replacement = secrets.token_urlsafe(24)
        hashed = generate_password_hash(password)
        with db() as c:
            c.execute('UPDATE accounts SET password_hash=?,recovery_hash=? WHERE id=?', (hashed, digest(replacement), row['id']))
            c.execute('DELETE FROM personal_sessions WHERE account_id=?', (row['id'],))
        return issue_session(row['id'], recovery_code=replacement)

    def owned_playlist(playlist_id):
        with db() as c:
            return c.execute('SELECT id,name FROM playlists WHERE id=? AND account_id=?', (playlist_id, g.account['id'])).fetchone()

    @bp.get('/api/personal/playlists')
    @auth
    def playlists():
        with db() as c:
            rows = c.execute('SELECT p.id,p.name,COUNT(t.id) AS tracks FROM playlists p LEFT JOIN playlist_tracks t ON t.playlist_id=p.id WHERE p.account_id=? GROUP BY p.id ORDER BY p.id DESC', (g.account['id'],)).fetchall()
        return jsonify(playlists=[dict(r) for r in rows])

    @bp.post('/api/personal/playlists')
    @auth
    def create_playlist():
        name = str((request.get_json() or {}).get('name', '')).strip()[:80]
        if not name:
            return error('Give the playlist a name.')
        with db() as c:
            if c.execute('SELECT COUNT(*) FROM playlists WHERE account_id=?', (g.account['id'],)).fetchone()[0] >= 50:
                return error('You can have up to 50 playlists.')
            row = c.execute('INSERT INTO playlists(account_id,name,created) VALUES(?,?,?)', (g.account['id'], name, time.time()))
        return jsonify(id=row.lastrowid, name=name), 201

    @bp.get('/api/personal/playlists/<int:playlist_id>')
    @auth
    def playlist(playlist_id):
        row = owned_playlist(playlist_id)
        if not row:
            return error('Playlist not found.', 404)
        with db() as c:
            rows = c.execute('SELECT id,video_id,title,artist FROM playlist_tracks WHERE playlist_id=? ORDER BY id', (playlist_id,)).fetchall()
        return jsonify(playlist=dict(row), tracks=[format_track(dict(r)) for r in rows])

    @bp.delete('/api/personal/playlists/<int:playlist_id>')
    @auth
    def delete_playlist(playlist_id):
        if not owned_playlist(playlist_id):
            return error('Playlist not found.', 404)
        with db() as c:
            c.execute('DELETE FROM tv_sources WHERE playlist_id=?', (playlist_id,))
            c.execute('DELETE FROM playlist_tracks WHERE playlist_id=?', (playlist_id,))
            c.execute('DELETE FROM playlists WHERE id=?', (playlist_id,))
        return jsonify(ok=True)

    @bp.post('/api/personal/playlists/<int:playlist_id>/tracks')
    @auth
    def add_track(playlist_id):
        if not owned_playlist(playlist_id):
            return error('Playlist not found.', 404)
        if limited(('personal-add', g.account['id']), 30, 60):
            return error('Please wait a minute before adding more tracks.', 429)
        vid = str((request.get_json() or {}).get('video_id', ''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            return error('Choose a valid video.')
        try:
            song = metadata(vid)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError):
            return error('That video is unavailable. Try another song.', 422)
        try:
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not c.execute('SELECT id FROM playlists WHERE id=? AND account_id=?', (playlist_id, g.account['id'])).fetchone():
                    return error('Playlist not found.', 404)
                if c.execute('SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id=?', (playlist_id,)).fetchone()[0] >= 200:
                    return error('This playlist has reached 200 tracks.')
                c.execute('INSERT INTO playlist_tracks(playlist_id,video_id,title,artist,created) VALUES(?,?,?,?,?)', (playlist_id, vid, song['title'], song['artist'], time.time()))
        except sqlite3.IntegrityError:
            return error('That track is already in this playlist.', 409)
        return jsonify(ok=True), 201

    @bp.delete('/api/personal/playlists/<int:playlist_id>/tracks/<int:track_id>')
    @auth
    def remove_track(playlist_id, track_id):
        if not owned_playlist(playlist_id):
            return error('Playlist not found.', 404)
        with db() as c:
            c.execute('DELETE FROM playlist_tracks WHERE id=? AND playlist_id=?', (track_id, playlist_id))
        return jsonify(ok=True)

    @bp.post('/api/personal/link-tv')
    @auth
    def link_tv():
        if limited(('tv-link', g.account['id']), 10, 300):
            return error('Too many pairing attempts. Try again in five minutes.', 429)
        code = str((request.get_json() or {}).get('code', '')).strip().upper()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT tv_id FROM tv_pairs WHERE code=? AND expires>?', (code, time.time())).fetchone()
            if not row:
                return error('That TV code is incorrect or expired.', 404)
            c.execute('INSERT OR REPLACE INTO tv_accounts VALUES(?,?,?)', (row['tv_id'], g.account['id'], time.time()))
            c.execute('DELETE FROM tv_pairs WHERE code=?', (code,))
        return jsonify(ok=True)

    @bp.get('/api/personal/linked-tvs')
    @auth
    def linked_tvs():
        with db() as c:
            rows = c.execute('SELECT tv_id,created FROM tv_accounts WHERE account_id=? ORDER BY created DESC', (g.account['id'],)).fetchall()
        return jsonify(tvs=[dict(id=r['tv_id'], label='TV linked ' + time.strftime('%d %b %Y', time.gmtime(r['created']))) for r in rows])

    @bp.post('/api/personal/unlink-tv')
    @auth
    def unlink_tv():
        tv_id = str((request.get_json() or {}).get('id', ''))
        with db() as c:
            c.execute('DELETE FROM tv_accounts WHERE tv_id=? AND account_id=?', (tv_id, g.account['id']))
            c.execute('DELETE FROM tv_sources WHERE tv_id=? AND playlist_id IN (SELECT id FROM playlists WHERE account_id=?)', (tv_id, g.account['id']))
        return jsonify(ok=True)

    @bp.post('/api/host/tv/pair')
    def pair_code():
        tv_id = session['tv_id']
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        with db() as c:
            c.execute('DELETE FROM tv_pairs WHERE tv_id=? OR expires<?', (tv_id, time.time()))
            c.execute('INSERT INTO tv_pairs VALUES(?,?,?)', (code, tv_id, time.time()+600))
        return jsonify(code=code, expires_in=600, personal_url=secure_url+'/personal')

    @bp.get('/api/host/tv/accounts')
    def tv_accounts():
        with db() as c:
            rows = c.execute('SELECT a.id,a.username,a.display_name FROM accounts a JOIN tv_accounts t ON t.account_id=a.id WHERE t.tv_id=? ORDER BY a.display_name', (session['tv_id'],)).fetchall()
        return jsonify(accounts=[dict(r) for r in rows])

    @bp.get('/api/host/tv/accounts/<int:account_id>/playlists')
    def tv_playlists(account_id):
        with db() as c:
            if not c.execute('SELECT 1 FROM tv_accounts WHERE tv_id=? AND account_id=?', (session['tv_id'], account_id)).fetchone():
                return error('This account is not linked to this TV.', 403)
            rows = c.execute('SELECT p.id,p.name,COUNT(t.id) AS tracks FROM playlists p LEFT JOIN playlist_tracks t ON t.playlist_id=p.id WHERE p.account_id=? GROUP BY p.id ORDER BY p.name', (account_id,)).fetchall()
        return jsonify(playlists=[dict(r) for r in rows])

    @bp.post('/api/host/tv/source')
    def tv_source_change():
        data = request.get_json() or {}
        tv_id = session['tv_id']
        with db() as c:
            if data.get('mode') == 'shared':
                c.execute('DELETE FROM tv_sources WHERE tv_id=?', (tv_id,))
            elif data.get('mode') == 'personal':
                playlist_id = data.get('playlist_id')
                if type(playlist_id) is not int or playlist_id < 1:
                    return error('Choose a valid playlist.')
                if not c.execute('SELECT 1 FROM playlists p JOIN tv_accounts t ON t.account_id=p.account_id WHERE p.id=? AND t.tv_id=?', (playlist_id, tv_id)).fetchone():
                    return error('Link the account to this TV before choosing its playlist.', 403)
                c.execute('INSERT OR REPLACE INTO tv_sources(tv_id,playlist_id) VALUES(?,?)', (tv_id, playlist_id))
            else:
                return error('Choose shared or personal mode.')
        return jsonify(ok=True)

    def selected_source(c):
        return c.execute('SELECT s.*,p.name AS playlist_name,a.id AS account_id,a.display_name,a.guest_id FROM tv_sources s JOIN playlists p ON p.id=s.playlist_id JOIN accounts a ON a.id=p.account_id JOIN tv_accounts t ON t.tv_id=s.tv_id AND t.account_id=a.id WHERE s.tv_id=?', (session.get('tv_id', ''),)).fetchone()

    def source_tracks(c, source):
        return [dict(r) for r in c.execute('SELECT id,video_id,title,artist FROM playlist_tracks WHERE playlist_id=? AND id>? ORDER BY id', (source['playlist_id'], source['after_track']))]

    @bp.get('/api/host/tv/state')
    def tv_state():
        with db() as c:
            source = selected_source(c)
            if not source:
                result = app.view_functions['state']().get_json()
                result['source'] = dict(mode='shared', label='Shared room')
                return jsonify(result)
            tracks = source_tracks(c, source)
            profile = c.execute('SELECT color,icon,photo FROM profiles WHERE id=?', (source['guest_id'],)).fetchone()
            for item in tracks:
                item.update(guest=source['display_name'], guest_color=profile['color'] if profile else '#d6fa77', guest_icon=profile['icon'] if profile else '♫', guest_photo='/avatars/'+profile['photo'] if profile and profile['photo'] else None)
                item.update(format_track(item))
        return jsonify(now=tracks[0] if tracks else None, queue=tracks[1:], paused=bool(source['paused']), accepting=False, host=True,
                       player_online=time.time()-source['heartbeat']<15, search_enabled=False, guest_url=secure_url+'/personal',
                       source=dict(mode='personal', account_id=source['account_id'], playlist_id=source['playlist_id'], label=source['display_name']+' · '+source['playlist_name']))

    def tv_player(data):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            source = selected_source(c)
            if not source:
                return None
            client = str(data.get('client', ''))[:80]
            if not client:
                return error('Missing player identity.')
            if source['client'] != client and time.time()-source['heartbeat']<15:
                return error('Another player is active for this TV. Close it and wait 15 seconds.', 409)
            tracks = source_tracks(c, source)
            if tracks and data.get('ended') == tracks[0]['id']:
                c.execute('UPDATE tv_sources SET after_track=? WHERE tv_id=?', (tracks[0]['id'], source['tv_id']))
            c.execute('UPDATE tv_sources SET client=?,heartbeat=? WHERE tv_id=?', (client, time.time(), source['tv_id']))
        return jsonify(ok=True)

    def tv_control(data):
        action = data.get('action')
        if action not in ('pause', 'resume', 'skip'):
            return None
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            source = selected_source(c)
            if not source:
                return None
            if action in ('pause', 'resume'):
                c.execute('UPDATE tv_sources SET paused=? WHERE tv_id=?', (int(action=='pause'), source['tv_id']))
            else:
                tracks = source_tracks(c, source)
                if tracks:
                    c.execute('UPDATE tv_sources SET after_track=? WHERE tv_id=?', (tracks[0]['id'], source['tv_id']))
        return jsonify(ok=True)

    app.tv_player = tv_player
    app.tv_control = tv_control
    app.register_blueprint(bp)

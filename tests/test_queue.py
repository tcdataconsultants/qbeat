import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

tmp = tempfile.TemporaryDirectory()
os.environ.update(SESSION_SECRET='test-secret', HOST_PIN='12345678', DATABASE=tmp.name + '/test.db')
spec = importlib.util.spec_from_file_location('jukebox', os.path.join(os.path.dirname(__file__), '..', 'app.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class QueueTests(unittest.TestCase):
    def setUp(self):
        with m.db() as c:
            c.execute('DELETE FROM songs')
            c.execute('DELETE FROM player_events')
            c.execute("UPDATE settings SET paused=0,accepting=1,player='',heartbeat=0")
        m.hits.clear()
        self.guest = m.app.test_client()
        self.host = m.app.test_client()
        self.host.post('/api/login', json={'pin': '12345678'})
        self.meta = patch.object(m, 'metadata', side_effect=lambda vid: dict(video_id=vid, title='Track '+vid, artist='Artist'))
        self.meta.start()
        self.addCleanup(self.meta.stop)

    def add(self, vid='abcdefghijk', guest=None):
        return (guest or self.guest).post('/api/queue', json=dict(video_id=vid, guest='<b>Guest</b>'))

    def state(self):
        return self.guest.get('/api/state').json

    def test_guests_cannot_control_playback(self):
        self.assertEqual(self.guest.post('/api/host/control', json={'action':'skip'}).status_code, 401)
        self.assertEqual(self.guest.post('/api/host/player', json={'client':'a'}).status_code, 401)

    def test_duplicate_and_guest_limit(self):
        self.assertEqual(self.add().status_code, 201)
        self.assertEqual(self.add().status_code, 409)
        self.add('bcdefghijkl')
        self.add('cdefghijklm')
        self.assertEqual(self.add('defghijklmn').status_code, 400)
        self.assertEqual(len(self.state()['queue']), 3)

    def test_fifo_and_stale_end_event_does_not_skip(self):
        self.add(); self.add('bcdefghijkl')
        self.host.post('/api/host/player', json={'client':'tv'})
        first = self.state()['now']['id']
        self.host.post('/api/host/player', json={'client':'tv','ended':first})
        second = self.state()['now']['id']
        self.assertNotEqual(first, second)
        self.host.post('/api/host/player', json={'client':'tv','ended':first})
        self.assertEqual(self.state()['now']['id'], second)

    def test_only_one_player(self):
        self.host.post('/api/host/player', json={'client':'tv'})
        self.assertEqual(self.host.post('/api/host/player', json={'client':'second'}).status_code, 409)

    def test_player_error_is_recorded_without_advancing_queue(self):
        self.add(); self.add('bcdefghijkl')
        self.host.post('/api/host/player', json={'client':'tv'})
        song_id=self.state()['now']['id']
        result=self.host.post('/api/host/player', json={'client':'tv','error_code':150,'song_id':song_id})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.state()['now']['id'],song_id)
        self.assertEqual(len(self.state()['queue']),1)
        self.assertIsNone(self.state()['last_player_error'])
        self.assertEqual(self.host.get('/api/state').json['last_player_error']['code'],150)
        with m.db() as c:
            self.assertEqual(c.execute('SELECT status FROM songs WHERE id=?',(song_id,)).fetchone()[0],'playing')

    def test_other_player_cannot_report_error(self):
        self.add()
        self.host.post('/api/host/player', json={'client':'tv'})
        song_id=self.state()['now']['id']
        self.assertEqual(self.host.post('/api/host/player', json={'client':'other','error_code':5,'song_id':song_id}).status_code,409)
        self.assertIsNone(self.host.get('/api/state').json['last_player_error'])

    def test_pause_and_requests(self):
        self.host.post('/api/host/control', json={'action':'requests','enabled':False})
        self.assertEqual(self.add().status_code, 403)
        self.host.post('/api/host/control', json={'action':'requests','enabled':True})
        self.add()
        self.host.post('/api/host/control', json={'action':'pause'})
        self.host.post('/api/host/player', json={'client':'tv'})
        self.assertIsNone(self.state()['now'])
        self.host.post('/api/host/control', json={'action':'resume'})
        self.host.post('/api/host/player', json={'client':'tv'})
        self.assertIsNotNone(self.state()['now'])

    def test_invalid_links_and_cross_site_requests(self):
        self.assertIsNone(m.video_id('https://evil.example/watch?v=abcdefghijk'))
        self.assertEqual(m.video_id('https://youtu.be/abcdefghijk?si=123'), 'abcdefghijk')
        self.assertEqual(self.guest.post('/api/queue', json={'video_id':'abcdefghijk'}, headers={'Origin':'https://evil.example'}).status_code, 403)

    def test_routes_qr_and_no_key_message(self):
        for path in ('/', '/host', '/player', '/health', '/qr.png'):
            with self.guest.get(path) as response:
                self.assertEqual(response.status_code, 200)
        with patch.object(m, 'API_KEY', ''):
            self.assertEqual(self.guest.get('/api/search?q=artist').status_code, 503)


if __name__ == '__main__':
    unittest.main()

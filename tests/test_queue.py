import importlib.util
import os
import tempfile
import unittest
import io
import json
import base64
from urllib.error import HTTPError, URLError
from PIL import Image
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
            c.execute('DELETE FROM search_cache')
            c.execute('DELETE FROM profiles')
            c.execute('DELETE FROM video_details')
            c.execute("UPDATE settings SET paused=0,accepting=1,player='',heartbeat=0")
        m.hits.clear()
        m.search_retry_until = 0
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

    def test_search_cache_and_eleven_character_artist(self):
        payload={'items':[{'id':{'videoId':'abcdefghijk'},'snippet':{'title':'A &amp; B','channelTitle':'Artist'}}]}
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',return_value=payload) as remote:
            first=self.guest.get('/api/search?q=LedZeppelin')
            self.assertEqual(first.status_code,200)
            self.assertEqual(first.json['results'][0]['title'],'A & B')
            second=self.guest.get('/api/search?q=ledzeppelin')
            self.assertTrue(second.json['cached'])
            self.assertEqual(remote.call_count,2)
            self.assertIn('q=LedZeppelin',remote.call_args_list[0].args[0])
            m.metadata.assert_not_called()

    def test_batched_video_lengths_cache_and_live_labels(self):
        details={'items':[
            {'id':'abcdefghijk','contentDetails':{'duration':'PT4M12S'},'snippet':{'liveBroadcastContent':'none'}},
            {'id':'bcdefghijkl','contentDetails':{'duration':'PT1H2M3S'},'snippet':{}},
            {'id':'cdefghijklm','contentDetails':{'duration':'PT0S'},'snippet':{'liveBroadcastContent':'live'}}]}
        songs=[dict(video_id=vid,title='Song',artist='Artist') for vid in ('abcdefghijk','bcdefghijkl','cdefghijklm')]
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',return_value=details) as remote:
            result=m.enrich_durations(songs)
            self.assertEqual([r['duration_label'] for r in result],['4:12','1:02:03','LIVE'])
            self.assertEqual(result[0]['duration_seconds'],252)
            self.assertIsNone(result[2]['duration_seconds'])
            self.assertEqual(remote.call_count,1)
            m.enrich_durations(songs)
            self.assertEqual(remote.call_count,1)
        self.assertEqual(m.parse_duration('P1DT2H3M4S'),93784)
        self.assertIsNone(m.parse_duration('unknown'))

    def test_duration_api_failure_does_not_break_search(self):
        song={'items':[{'id':{'videoId':'abcdefghijk'},'snippet':{'title':'Song','channelTitle':'Artist'}}]}
        failed=HTTPError('https://example.invalid',403,'Forbidden',{},io.BytesIO(b'{}'))
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',side_effect=[song,failed]):
            result=self.guest.get('/api/search?q=artist')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['results'][0]['duration_label'],'Length unavailable')

    def test_search_distinguishes_quota_and_configuration_errors(self):
        for reason,phrase in [('quotaExceeded','daily search allowance'),('accessNotConfigured','API key')]:
            upstream=HTTPError('https://example.invalid',403,'Forbidden',{},io.BytesIO(json.dumps({'error':{'errors':[{'reason':reason}]}}).encode()))
            with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',side_effect=upstream):
                result=self.guest.get('/api/search?q=artist')
                self.assertEqual(result.status_code,503)
                self.assertIn(phrase,result.json['error'])

    def test_temporary_rate_limit_has_retry_time_and_cooldown(self):
        body={'error':{'status':'RESOURCE_EXHAUSTED','errors':[{'reason':'rateLimitExceeded'}]}}
        upstream=HTTPError('https://example.invalid',429,'Too many requests',{'Retry-After':'15'},io.BytesIO(json.dumps(body).encode()))
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',side_effect=upstream) as remote:
            result=self.guest.get('/api/search?q=first')
            self.assertEqual(result.status_code,429)
            self.assertIn('wait 15 seconds',result.json['error'])
            self.assertNotIn('daily',result.json['error'])
            self.assertEqual(result.headers['Retry-After'],'15')
            self.assertEqual(self.guest.get('/api/search?q=second').status_code,429)
            self.assertEqual(remote.call_count,1)
            with m.db() as c:
                c.execute('INSERT INTO search_cache VALUES(?,?,?)',('saved','[]',m.time.time()+300))
            self.assertEqual(self.guest.get('/api/search?q=saved').status_code,200)

    def test_daily_limit_metadata_overrides_generic_rate_reason(self):
        body={'error':{'status':'RESOURCE_EXHAUSTED','errors':[{'reason':'rateLimitExceeded'}],
                       'details':[{'metadata':{'quota_limit':'defaultSearchListPerDayPerProject','quota_unit':'1/d/{project}'}}]}}
        upstream=HTTPError('https://example.invalid',429,'Too many requests',{},io.BytesIO(json.dumps(body).encode()))
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',side_effect=upstream):
            result=self.guest.get('/api/search?q=artist')
            self.assertEqual(result.status_code,503)
            self.assertIn('daily search allowance',result.json['error'])
            self.assertEqual(m.search_retry_until,0)

    def test_artist_channel_results_do_not_break_video_search(self):
        payload={'items':[
            {'id':{'kind':'youtube#channel','channelId':'artist-channel'},'snippet':{'title':'Artist'}},
            {'id':{'kind':'youtube#playlist','playlistId':'playlist'},'snippet':{'title':'Playlist'}},
            {'id':{'kind':'youtube#video','videoId':'abcdefghijk'},'snippet':{'title':'Playable song','channelTitle':'Artist'}},
            {'id':None,'snippet':{}},None]}
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',return_value=payload):
            result=self.guest.get('/api/search?q=Slayyyter')
            self.assertEqual(result.status_code,200)
            self.assertEqual([v['title'] for v in result.json['results']],['Playable song'])

    def test_karaoke_search_is_separate_from_normal_search(self):
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',return_value={'items':[]}) as remote:
            self.guest.get('/api/search?q=Song')
            self.guest.get('/api/search?q=Song&karaoke=1')
            self.assertEqual(remote.call_count,2)
            self.assertIn('q=Song+karaoke+lyrics',remote.call_args[0][0])
            self.guest.get('/api/search?q=song&karaoke=1')
            self.assertEqual(remote.call_count,2)

    def test_search_retries_transient_errors_and_cache_survives_init(self):
        with patch.object(m,'API_KEY','test-key'),patch.object(m,'remote_json',side_effect=[URLError('timeout'),{'items':[]}]) as remote:
            self.assertEqual(self.guest.get('/api/search?q=test').status_code,200)
            self.assertEqual(remote.call_count,2)
            m.init()
            self.assertTrue(self.guest.get('/api/search?q=TEST').json['cached'])

    def test_profile_styles_follow_guest_and_are_isolated(self):
        self.add()
        self.assertEqual(self.guest.post('/api/profile',json={'name':'Alex','color':'#79d9f2','icon':'🎧'}).status_code,200)
        song=self.state()['queue'][0]
        self.assertEqual((song['guest'],song['guest_color'],song['guest_icon']),('Alex','#79d9f2','🎧'))
        self.assertEqual(self.host.get('/api/profile').json['profile']['name'],'')
        self.assertEqual(self.guest.post('/api/profile',json={'color':'red;display:none','icon':'🎧'}).status_code,400)

    def test_selfie_is_sanitized_removable_and_invalid_images_rejected(self):
        out=io.BytesIO();Image.new('RGB',(40,60),'red').save(out,'PNG')
        raw='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
        result=self.guest.post('/api/profile/photo',json={'photo':raw})
        self.assertEqual(result.status_code,200)
        path=result.json['profile']['photo']
        response=self.guest.get(path)
        self.assertEqual(response.mimetype,'image/jpeg')
        self.assertEqual(Image.open(io.BytesIO(response.data)).size,(256,256));response.close()
        self.assertEqual(self.guest.post('/api/profile/photo',json={'photo':'data:image/png;base64,bm90YW5pbWFnZQ=='}).status_code,400)
        result=self.guest.post('/api/profile/photo',json={'photo':None})
        self.assertIsNone(result.json['profile']['photo'])
        self.assertEqual(self.guest.get(path).status_code,404)


if __name__ == '__main__':
    unittest.main()

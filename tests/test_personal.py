import unittest
from unittest.mock import patch
from test_queue import m

HTTPS = 'https://localhost'


class PersonalTests(unittest.TestCase):
    def setUp(self):
        with m.db() as c:
            for table in ('personal_sessions','playlist_tracks','playlists','tv_sources','tv_pairs','tv_accounts','accounts','songs'):
                c.execute('DELETE FROM '+table)
            c.execute("UPDATE settings SET paused=0,accepting=1,player='',heartbeat=0")
        m.hits.clear()
        self.alice=m.app.test_client()
        self.bob=m.app.test_client()
        self.tv=m.app.test_client()
        self.tv.post('/api/login',json={'pin':'12345678'},base_url=HTTPS)
        self.meta=patch.object(m,'metadata',side_effect=lambda vid:dict(video_id=vid,title='Artist - Song (Official Video)',artist='ArtistVEVO'))
        self.meta.start();self.addCleanup(self.meta.stop)

    def signup(self,client,name):
        result=client.post('/api/personal/signup',json={'username':name,'display_name':name.title(),'password':'a sufficiently long password'},base_url=HTTPS)
        self.assertEqual(result.status_code,200,result.json)
        self.assertIn('Secure',result.headers['Set-Cookie'])
        return result.json

    def playlist(self,client,name='My mix'):
        result=client.post('/api/personal/playlists',json={'name':name},base_url=HTTPS)
        self.assertEqual(result.status_code,201,result.json)
        return result.json['id']

    def add(self,client,pid,vid='abcdefghijk'):
        result=client.post(f'/api/personal/playlists/{pid}/tracks',json={'video_id':vid},base_url=HTTPS)
        self.assertEqual(result.status_code,201,result.json)

    def test_accounts_require_tls_and_signout_revokes_session(self):
        self.assertEqual(self.alice.post('/api/personal/signup',json={}).status_code,426)
        self.signup(self.alice,'alice')
        self.assertEqual(self.alice.get('/api/personal/me',base_url=HTTPS).json['account']['username'],'alice')
        with m.db() as c:
            row=c.execute('SELECT password_hash FROM accounts').fetchone()
            self.assertNotIn('sufficiently',row['password_hash'])
        self.alice.post('/api/personal/signout',json={},base_url=HTTPS)
        self.assertIsNone(self.alice.get('/api/personal/me',base_url=HTTPS).json['account'])
        self.assertEqual(self.alice.get('/api/personal/playlists',base_url=HTTPS).status_code,401)

    def test_playlists_are_private_and_never_add_to_room(self):
        self.signup(self.alice,'alice');self.signup(self.bob,'bob')
        pid=self.playlist(self.alice);self.add(self.alice,pid)
        self.assertEqual(self.bob.get(f'/api/personal/playlists/{pid}',base_url=HTTPS).status_code,404)
        self.assertEqual(self.bob.post(f'/api/personal/playlists/{pid}/tracks',json={'video_id':'bcdefghijkl'},base_url=HTTPS).status_code,404)
        self.assertEqual(self.bob.delete(f'/api/personal/playlists/{pid}',json={},base_url=HTTPS).status_code,404)
        self.assertEqual(self.alice.get('/api/state').json['queue'],[])
        song=self.alice.get(f'/api/personal/playlists/{pid}',base_url=HTTPS).json['tracks'][0]
        self.assertEqual((song['display_artist'],song['display_title']),('Artist','Song'))
        self.assertEqual(song['title'],'Artist - Song (Official Video)')

    def test_recovery_rotates_code_and_revokes_other_sessions(self):
        signup=self.signup(self.alice,'alice')
        self.bob.post('/api/personal/signin',json={'username':'alice','password':'a sufficiently long password'},base_url=HTTPS)
        recovery=self.alice.post('/api/personal/recover',json={'username':'alice','password':'a new sufficiently long password','recovery_code':signup['recovery_code']},base_url=HTTPS)
        self.assertEqual(recovery.status_code,200)
        self.assertNotEqual(recovery.json['recovery_code'],signup['recovery_code'])
        self.assertIsNone(self.bob.get('/api/personal/me',base_url=HTTPS).json['account'])
        self.assertEqual(self.bob.post('/api/personal/signin',json={'username':'alice','password':'a sufficiently long password'},base_url=HTTPS).status_code,401)

    def test_tv_requires_pairing_and_private_playback_is_isolated(self):
        self.signup(self.alice,'alice');pid=self.playlist(self.alice)
        self.add(self.alice,pid);self.add(self.alice,pid,'bcdefghijkl')
        self.assertEqual(self.tv.get('/api/host/tv/accounts',base_url=HTTPS).json['accounts'],[])
        self.assertEqual(self.tv.post('/api/host/tv/source',json={'mode':'personal','playlist_id':pid},base_url=HTTPS).status_code,403)
        code=self.tv.post('/api/host/tv/pair',json={},base_url=HTTPS).json['code']
        self.assertEqual(self.alice.post('/api/personal/link-tv',json={'code':code},base_url=HTTPS).status_code,200)
        self.assertEqual(self.alice.post('/api/personal/link-tv',json={'code':code},base_url=HTTPS).status_code,404)
        self.assertEqual(len(self.tv.get('/api/host/tv/accounts',base_url=HTTPS).json['accounts']),1)
        self.assertEqual(self.tv.post('/api/host/tv/source',json={'mode':'personal','playlist_id':pid},base_url=HTTPS).status_code,200)
        self.tv.post('/api/host/player',json={'client':'tv'},base_url=HTTPS)
        state=self.tv.get('/api/host/tv/state',base_url=HTTPS).json
        first=state['now']['id']
        self.assertEqual(state['source']['mode'],'personal')
        self.tv.post('/api/host/player',json={'client':'tv','ended':first},base_url=HTTPS)
        second=self.tv.get('/api/host/tv/state',base_url=HTTPS).json['now']['id']
        self.assertNotEqual(first,second)
        self.tv.post('/api/host/player',json={'client':'tv','ended':first},base_url=HTTPS)
        self.assertEqual(self.tv.get('/api/host/tv/state',base_url=HTTPS).json['now']['id'],second)
        self.tv.post('/api/host/control',json={'action':'pause'},base_url=HTTPS)
        self.assertTrue(self.tv.get('/api/host/tv/state',base_url=HTTPS).json['paused'])
        self.assertFalse(self.tv.get('/api/state').json['paused'])
        self.assertEqual(self.tv.get('/api/state').json['queue'],[])
        linked=self.alice.get('/api/personal/linked-tvs',base_url=HTTPS).json['tvs'][0]
        self.alice.post('/api/personal/unlink-tv',json={'id':linked['id']},base_url=HTTPS)
        self.assertEqual(self.tv.get('/api/host/tv/state',base_url=HTTPS).json['source']['mode'],'shared')

    def test_different_tv_cannot_see_linked_accounts(self):
        self.signup(self.alice,'alice')
        code=self.tv.post('/api/host/tv/pair',json={},base_url=HTTPS).json['code']
        self.alice.post('/api/personal/link-tv',json={'code':code},base_url=HTTPS)
        other=m.app.test_client();other.post('/api/login',json={'pin':'12345678'},base_url=HTTPS)
        self.assertEqual(other.get('/api/host/tv/accounts',base_url=HTTPS).json['accounts'],[])


if __name__=='__main__':unittest.main()

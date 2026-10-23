const $ = id => document.getElementById(id);
const mode = location.pathname === '/player' ? 'player' : location.pathname === '/host' ? 'host' : 'guest';
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, toastTimer, searchSerial = 0, player, ready = false, started = false, busy = false, loadedId = null;
let blocked = false;
const client = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,'0')).join('');
const thumb = vid => 'https://i.ytimg.com/vi/' + encodeURIComponent(vid) + '/mqdefault.jpg';
document.body.classList.toggle('player-mode', mode === 'player');
try { $('guest-name').value = localStorage.getItem('qbeat-name') || ''; } catch (_) {}

async function api(path, data) {
  const r = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const result = await r.json();
  if (!r.ok) throw new Error(result.error || 'Something went wrong. Please try again.');
  return result;
}
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000); }
function row(song, index, result = false) {
  return `<div class="track">${result ? '' : `<span class="number">${String(index+1).padStart(2,'0')}</span>`}<img src="${thumb(song.video_id)}" alt="" loading="lazy"><div class="info"><h3>${esc(song.title)}</h3><p>${esc(song.artist)}${result ? '' : ' · Picked by ' + esc(song.guest)}</p></div>${result ? `<button data-add="${esc(song.video_id)}" ${state && !state.accepting ? 'disabled' : ''}>+ Add</button>` : state?.host && mode === 'host' ? `<button class="text-button" data-remove="${song.id}" aria-label="Remove ${esc(song.title)}">Remove</button>` : ''}</div>`;
}
function render() {
  const needsLogin = mode !== 'guest' && !state.host;
  $('login').hidden = !needsLogin; $('app').hidden = needsLogin;
  $('guest-content').hidden = mode !== 'guest'; $('host-content').hidden = mode !== 'host'; $('player-content').hidden = mode !== 'player';
  if (mode === 'host') { $('headline').innerHTML = 'Your room.<br><span>Your soundtrack.</span>'; $('intro-copy').textContent = 'A little curation goes a long way. Keep the music moving.'; }
  if (mode === 'player') $('headline').innerHTML = 'The room is <span>listening.</span>';
  $('queue-count').textContent = state.queue.length;
  $('queue').innerHTML = state.queue.length ? state.queue.map((s,i) => row(s,i)).join('') : '<div class="empty">No songs waiting. There’s room for your next great pick.</div>';
  $('now-title').textContent = state.now?.title || 'The room is yours.';
  $('now-artist').textContent = state.now ? `${state.now.artist} · Picked by ${state.now.guest}` : 'Add the first song to get things going.';
  $('now-art').hidden = !state.now;
  if (state.now) $('now-art').src = thumb(state.now.video_id);
  $('player-status').textContent = state.player_online ? (state.paused ? '● Player paused' : '● Player connected') : '○ Player offline';
  $('search-hint').textContent = !state.accepting ? 'Requests are closed for now. Enjoy the music.' : state.search_enabled ? 'Search YouTube or paste a video link. Up to 3 waiting picks per guest.' : 'Link mode is ready: paste a YouTube video link. Song and artist search will open once the host connects YouTube search.';
  $('search').placeholder = state.search_enabled ? 'Search a song, artist, or paste a YouTube link' : 'Paste a YouTube video link';
  $('pause').textContent = $('player-pause').textContent = state.paused ? 'Resume ▶' : 'Pause Ⅱ';
  $('requests').textContent = state.accepting ? 'Close requests' : 'Open requests';
  $('guest-link').href = state.guest_url;
  $('connection').hidden = state.player_online || needsLogin || mode === 'player';
  $('connection').textContent = 'The TV player isn’t connected yet. You can still add songs; they’ll wait in the queue.';
}
async function refresh() { state = await api('state'); render(); }
$('login-form').onsubmit = async e => { e.preventDefault(); try { await api('login', {pin:$('pin').value}); $('pin').value=''; await refresh(); } catch(e) { $('login-error').textContent=e.message; } };
$('search-form').onsubmit = async e => {
  e.preventDefault(); const serial = ++searchSerial;
  $('welcome').hidden = true; $('results').innerHTML=''; $('search-status').textContent='Looking on YouTube…';
  try { const data = await api('search?q='+encodeURIComponent($('search').value)); if(serial !== searchSerial) return; $('results').innerHTML = data.results.map((s,i)=>row(s,i,true)).join(''); $('search-status').textContent = data.results.length ? `${data.results.length} ${data.results.length === 1 ? 'track' : 'tracks'} found on YouTube` : 'No tracks found. Try another artist or song.'; } catch(e) { if(serial === searchSerial) $('search-status').textContent=e.message; }
};
$('results').onclick = async e => {
  const button=e.target.closest('[data-add]'); if(!button) return;
  button.disabled=true;
  try { const guest=$('guest-name').value; try {localStorage.setItem('qbeat-name',guest);} catch(_) {} await api('queue',{video_id:button.dataset.add,guest}); toast('Your pick is in the queue. Nice one.'); button.textContent='Queued ✓'; await refresh(); } catch(e) { toast(e.message); button.disabled=false; }
};
async function control(action, extra={}) { try { await api('host/control',{action,...extra}); await refresh(); } catch(e) { toast(e.message); } }
$('pause').onclick = $('player-pause').onclick = () => control(state.paused ? 'resume' : 'pause');
$('skip').onclick = $('player-skip').onclick = () => control('skip');
$('requests').onclick = () => control('requests',{enabled:!state.accepting});
$('queue').onclick = e => { const b=e.target.closest('[data-remove]'); if(b) control('remove',{id:Number(b.dataset.remove)}); };
$('logout').onclick = async () => { await api('host/logout',{}); await refresh(); };
$('copy-link').onclick = async () => {
  try { if(navigator.clipboard) {await navigator.clipboard.writeText(state.guest_url); toast('Invite link copied.');} else {prompt('Copy this guest link:',state.guest_url);} } catch(_) {prompt('Copy this guest link:',state.guest_url);}
};
$('fullscreen').onclick = () => {if(document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.().catch(()=>toast('Fullscreen is unavailable in this browser.'));};

function stopLocal(message) {
  started=false; loadedId=null;
  if(ready) player.stopVideo();
  $('start-player').textContent='Reconnect player ▶'; $('start-player').disabled=false;
  $('player-message').textContent=message;
}
async function finishTrack(endedId = loadedId) {
  if(!started || endedId === null || loadedId !== endedId) return;
  if(busy) {setTimeout(() => finishTrack(endedId),100);return;}
  busy=true;
  try { await api('host/player',{client,ended:endedId}); loadedId=null; await refresh(); syncPlayer(); }
  catch(e) {stopLocal(e.message);} finally {busy=false;}
}
function syncPlayer() {
  if(!ready || !started || !state) return;
  if(!state.now) { if(loadedId !== null) player.stopVideo(); loadedId=null; return; }
  if(loadedId !== state.now.id) {
    loadedId=state.now.id; blocked=false;
    if(state.paused) player.cueVideoById(state.now.video_id); else player.loadVideoById(state.now.video_id);
  } else if(state.paused && player.getPlayerState() === 1) player.pauseVideo();
  else if(!state.paused && !blocked && [2,5].includes(player.getPlayerState())) player.playVideo();
}
window.onYouTubeIframeAPIReady = () => {
  player = new YT.Player('youtube', {width:'100%',height:'100%',playerVars:{playsinline:1,origin:location.origin},events:{
    onReady:()=>{ ready=true; $('player-message').textContent='Player ready. If sound is blocked, press Play in the video.'; tick(); },
    onStateChange:e=>{if(e.data === YT.PlayerState.ENDED) finishTrack(); if(e.data === YT.PlayerState.PLAYING){blocked=false; $('player-message').textContent='Connected. The next song plays automatically.';}},
    onAutoplayBlocked:()=>{blocked=true;$('player-message').textContent='Press Play inside the YouTube video to enable sound.'; $('start-player').disabled=false; $('start-player').textContent='Enable sound ▶';},
    onError:e=>{
      if([100,101,150,2,5].includes(e.data)) {toast('This video can’t play here. Moving to the next pick.'); finishTrack();}
      else {blocked=true;$('player-message').textContent=`YouTube playback error ${e.data}. Try reloading this page or another browser.`;}
    }
  }});
};
$('start-player').onclick = async () => {
  if(ready && started) {blocked=false;player.playVideo();return;}
  $('start-player').disabled=true;
  try {
    await api('host/player',{client}); started=true; $('player-welcome').hidden=true;
    $('start-player').textContent='Player connected ✓';
    if(!player && !document.querySelector('script[data-youtube]')) {const s=document.createElement('script');s.src='https://www.youtube.com/iframe_api';s.dataset.youtube='1';s.onerror=()=>stopLocal('Unable to load YouTube. Check this device’s connection and reload.');document.head.appendChild(s);}
    if(ready) await tick();
  } catch(e) {stopLocal(e.message);}
};
async function tick() {
  if(busy) return; busy=true;
  try {
    if(mode === 'player' && started) await api('host/player',{client});
    await refresh(); syncPlayer();
  } catch(e) {
    if(mode === 'player' && started) stopLocal(e.message);
    $('connection').hidden=false; $('connection').textContent='Connection interrupted. Retrying… ' + e.message;
  } finally {busy=false;}
}
tick(); setInterval(tick,3000);

const $ = id => document.getElementById(id);
const mode = location.pathname === '/player' ? 'player' : location.pathname === '/host' ? 'host' : 'guest';
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state, toastTimer, searchSerial = 0, player, ready = false, started = false, busy = false, loadedId = null;
let blocked = false;
let captionsEnabled = false;
let introTimer, introId=null;
let countdownEnabled=false;
try{countdownEnabled=localStorage.getItem('qbeat-countdown')==='1';}catch(_){}
let profile = {name:'',color:'#d6fa77',icon:'♫',photo:null};
const client = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,'0')).join('');
const thumb = vid => 'https://i.ytimg.com/vi/' + encodeURIComponent(vid) + '/mqdefault.jpg';
document.body.classList.toggle('player-mode', mode === 'player');
document.body.classList.toggle('guest-mode', mode === 'guest');
try { $('guest-name').value = localStorage.getItem('qbeat-name') || ''; } catch (_) {}

async function api(path, data) {
  const r = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const result = await r.json();
  if (!r.ok) throw new Error(result.error || 'Something went wrong. Please try again.');
  return result;
}
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000); }
function row(song, index, result = false) {
  const color=/^#[a-f0-9]{6}$/i.test(song.guest_color||'')?song.guest_color:'#d6fa77';
  const avatar=song.guest_photo&&/^\/avatars\/[a-f0-9]{32}\.jpg$/.test(song.guest_photo)?`<img class="guest-avatar tiny" src="${song.guest_photo}" alt="" loading="lazy">`:`<span class="guest-avatar tiny">${esc(song.guest_icon||'♫')}</span>`;
  const length=result?`<span class="track-duration" aria-label="Video length">${esc(song.duration_label||'Length unavailable')}</span>`:'';
  return `<div class="track">${result ? '' : `<span class="number">${String(index+1).padStart(2,'0')}</span>`}<img src="${thumb(song.video_id)}" alt="" loading="lazy"><div class="info"><h3>${esc(result?song.title:(song.display_title||song.title))}</h3><p>${esc(result?song.artist:(song.display_artist||song.artist))}</p>${length}${result?'':`<p class="picked-by"><span>Picked by <strong style="color:${color}">${esc(song.guest)}</strong></span>${avatar}</p>`}</div>${result ? `<button data-add="${esc(song.video_id)}" ${state && !state.accepting ? 'disabled' : ''}>+ Add</button>` : state?.host && mode === 'host' ? `<button class="text-button" data-remove="${song.id}" aria-label="Remove ${esc(song.title)}">Remove</button>` : ''}</div>`;
}
function render() {
  const needsLogin = mode !== 'guest' && !state.host;
  $('login').hidden = !needsLogin; $('app').hidden = needsLogin;
  $('guest-content').hidden = mode !== 'guest'; $('host-content').hidden = mode !== 'host'; $('player-content').hidden = mode !== 'player';
  if (mode === 'host') { $('headline').innerHTML = 'Your room.<br><span>Your soundtrack.</span>'; $('intro-copy').textContent = 'A little curation goes a long way. Keep the music moving.'; }
  if (mode === 'player') $('headline').innerHTML = 'The room is <span>listening.</span>';
  $('queue-count').textContent = state.queue.length;
  $('queue').innerHTML = state.queue.length ? state.queue.map((s,i) => row(s,i)).join('') : '<div class="empty">No songs waiting. There’s room for your next great pick.</div>';
  $('now-title').textContent = state.now?.display_title || state.now?.title || 'The room is yours.';
  document.body.classList.toggle('has-track', !!state.now);
  const nowColor=/^#[a-f0-9]{6}$/i.test(state.now?.guest_color||'')?state.now.guest_color:'#d6fa77';
  $('now-artist').innerHTML = state.now ? `${esc(state.now.display_artist||state.now.artist)} · Picked by <strong style="color:${nowColor}">${esc(state.now.guest)}</strong> ${esc(state.now.guest_icon||'♫')}` : 'Add the first song to get things going.';
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
  try { const data = await api('search?q='+encodeURIComponent($('search').value)+($('karaoke-search').checked?'&karaoke=1':'')); if(serial !== searchSerial) return; $('results').innerHTML = data.results.map((s,i)=>row(s,i,true)).join(''); $('search-status').textContent = data.results.length ? `${data.results.length} ${data.results.length === 1 ? 'track' : 'tracks'} found on YouTube` : 'No tracks found. Try another artist or song.'; } catch(e) { if(serial === searchSerial) $('search-status').textContent=e.message; }
};
$('results').onclick = async e => {
  const button=e.target.closest('[data-add]'); if(!button) return;
  button.disabled=true;
  try { const guest=$('guest-name').value; if(mode==='guest')await saveProfile(false);try {localStorage.setItem('qbeat-name',guest);} catch(_) {} await api('queue',{video_id:button.dataset.add,guest}); toast('Your pick is in the queue. Nice one.'); button.textContent='Queued ✓'; await refresh(); } catch(e) { toast(e.message); button.disabled=false; }
};
function renderProfile() {
  $('profile-label').textContent=profile.name||'Make it yours';$('profile-label').style.color=profile.color;
  $('profile-avatar').innerHTML=profile.photo?`<img src="${esc(profile.photo)}" alt="Your guest photo">`:esc(profile.icon);
  $('profile-avatar').style.color=profile.color;$('remove-photo').hidden=!profile.photo;
}
async function saveProfile(showMessage=true) {
  const color=document.querySelector('input[name="profile-color"]:checked')?.value||profile.color;
  const icon=document.querySelector('input[name="profile-icon"]:checked')?.value||profile.icon;
  const data=await api('profile',{name:$('guest-name').value,color,icon});profile=data.profile;renderProfile();
  if(showMessage){$('profile-status').textContent='Saved for this phone.';$('guest-profile').open=false;toast('Your style is saved.');}
}
async function initProfile() {
  try {
    const data=await api('profile');profile=data.profile;
    if(profile.name)$('guest-name').value=profile.name;
    $('profile-colors').innerHTML=data.colors.map((color,i)=>`<label class="color-choice"><input type="radio" name="profile-color" value="${color}" ${color===profile.color?'checked':''}><span style="background:${color}" title="Colour ${i+1}"><span class="sr-only">Colour ${i+1}</span></span></label>`).join('');
    $('profile-icons').innerHTML=data.icons.map(icon=>`<label class="icon-choice"><input type="radio" name="profile-icon" value="${esc(icon)}" ${icon===profile.icon?'checked':''}><span>${esc(icon)}</span></label>`).join('');
    renderProfile();
  } catch(e){$('profile-status').textContent=e.message;}
}
$('profile-form').onsubmit=async e=>{e.preventDefault();try{await saveProfile();await refresh();}catch(e){$('profile-status').textContent=e.message;}};
$('profile-photo').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  $('profile-status').textContent='Preparing your photo…';
  try {
    if(file.size>20000000)throw new Error('Choose a photo smaller than 20 MB.');
    const url=URL.createObjectURL(file),image=new Image();
    try{await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('This photo format could not be read. Try a JPEG or PNG.'));image.src=url;});}finally{URL.revokeObjectURL(url);}
    const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const size=Math.min(image.naturalWidth,image.naturalHeight);
    canvas.getContext('2d').drawImage(image,(image.naturalWidth-size)/2,(image.naturalHeight-size)/2,size,size,0,0,256,256);
    const data=await api('profile/photo',{photo:canvas.toDataURL('image/jpeg',0.85)});profile=data.profile;renderProfile();$('profile-status').textContent='Selfie added. Save your style when ready.';await refresh();
  }catch(e){$('profile-status').textContent=e.message;}finally{$('profile-photo').value='';}
};
$('remove-photo').onclick=async()=>{try{profile=(await api('profile/photo',{photo:null})).profile;renderProfile();$('profile-status').textContent='Photo removed.';await refresh();}catch(e){$('profile-status').textContent=e.message;}};
if(mode==='guest')initProfile();
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
$('tv-mode').onclick = () => {
  const enabled=document.body.classList.toggle('tv-stage');
  $('tv-mode').textContent=enabled?'Exit TV mode':'TV mode ⛶';
  if(enabled) document.documentElement.requestFullscreen?.().catch(()=>{});
};
$('compact-player').onclick=()=>{const enabled=document.body.classList.toggle('compact-view');$('compact-player').setAttribute('aria-pressed',enabled);$('compact-player').textContent=enabled?'Standard player':'Compact player';};
function countdownButton(){$('countdown-toggle').textContent='Countdown: '+(countdownEnabled?'on':'off');$('countdown-toggle').setAttribute('aria-pressed',countdownEnabled);}
countdownButton();
$('countdown-toggle').onclick=()=>{countdownEnabled=!countdownEnabled;try{localStorage.setItem('qbeat-countdown',countdownEnabled?'1':'0');}catch(_){}countdownButton();updateCountdown();};
function updateCountdown(){const node=$('video-countdown');if(!countdownEnabled||mode!=='player'||!ready||!started||blocked||introId!==null||!state?.now||loadedId!==state.now.id||!player.getDuration||!player.getCurrentTime){node.hidden=true;return;}const remaining=player.getDuration()-player.getCurrentTime();if(!Number.isFinite(remaining)||remaining<=0){node.hidden=true;return;}const total=Math.ceil(remaining),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60;node.textContent='Time left  '+(h?h+':'+String(m).padStart(2,'0'):m)+':'+String(s).padStart(2,'0');node.hidden=false;}
setInterval(updateCountdown,500);
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.body.classList.remove('tv-stage');});
function applyCaptions() {
  if(!ready || !player.getOptions) return;
  const loaded=player.getOptions().includes('captions');
  if(!captionsEnabled && loaded && player.unloadModule) player.unloadModule('captions');
  else if(captionsEnabled && !loaded && player.loadModule) player.loadModule('captions');
}
$('captions').onclick=()=>{captionsEnabled=!captionsEnabled;applyCaptions();$('captions').textContent='Subtitles: '+(captionsEnabled?'on':'off');$('captions').setAttribute('aria-pressed',captionsEnabled);};
function updateComingNext() {
  const strip=$('coming-next');
  if(mode!=='player' || !ready || !started || blocked || introId!==null || !state?.now || loadedId!==state.now.id || !state.queue.length || !player.getDuration || !player.getCurrentTime) {strip.hidden=true;return;}
  const duration=player.getDuration(), elapsed=player.getCurrentTime(), remaining=duration-elapsed;
  const visible=Number.isFinite(remaining) && duration>0 && remaining>0 && remaining<=10;
  strip.hidden=!visible;
  if(visible) strip.textContent=`COMING NEXT · ${state.queue[0].display_title||state.queue[0].title} · in ${Math.ceil(remaining)}s`;
}
setInterval(updateComingNext,500);

function stopLocal(message) {
  started=false; loadedId=null;
  clearTimeout(introTimer);introId=null;$('track-intro').hidden=true;document.querySelector('.video-box').hidden=false;
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
  if(!state.now) { clearTimeout(introTimer);introId=null;$('track-intro').hidden=true;document.querySelector('.video-box').hidden=false;if(loadedId !== null) player.stopVideo(); loadedId=null; return; }
  if(loadedId !== state.now.id) {
    loadedId=state.now.id; blocked=false;clearTimeout(introTimer);introId=loadedId;
    player.pauseVideo();document.querySelector('.video-box').hidden=true;$('track-intro').hidden=false;
    $('intro-name').textContent='Picked by '+state.now.guest+' '+(state.now.guest_icon||'♫');
    $('intro-name').style.color=/^#[a-f0-9]{6}$/i.test(state.now.guest_color||'')?state.now.guest_color:'#d6fa77';
    $('intro-track').textContent=(state.now.display_artist||state.now.artist)+' · '+(state.now.display_title||state.now.title);
    $('intro-avatar').innerHTML=state.now.guest_photo&&/^\/avatars\/[a-f0-9]{32}\.jpg$/.test(state.now.guest_photo)?`<img src="${state.now.guest_photo}" alt="">`:esc(state.now.guest_icon||'♫');
    const slide=$('intro-slide');slide.style.animation='none';void slide.offsetWidth;slide.style.animation='';
    const expected=loadedId;
    introTimer=setTimeout(()=>{if(!started||state.now?.id!==expected)return;introId=null;$('track-intro').hidden=true;document.querySelector('.video-box').hidden=false;if(state.paused)player.cueVideoById(state.now.video_id);else player.loadVideoById(state.now.video_id);},2000);
  } else if(introId!==null) {return;
  } else if(state.paused && player.getPlayerState() === 1) player.pauseVideo();
  else if(!state.paused && !blocked && [2,5].includes(player.getPlayerState())) player.playVideo();
}
window.onYouTubeIframeAPIReady = () => {
  player = new YT.Player('youtube', {width:'100%',height:'100%',playerVars:{playsinline:1,origin:location.origin,cc_load_policy:0,iv_load_policy:3,rel:0},events:{
    onReady:()=>{ ready=true; $('player-message').textContent='Player ready. If sound is blocked, press Play in the video.'; tick(); },
    onStateChange:e=>{if(e.data === YT.PlayerState.ENDED&&introId===null) finishTrack(); if(e.data === YT.PlayerState.PLAYING&&introId===null){blocked=false;applyCaptions(); $('player-message').textContent='Connected. The next song plays automatically.';}},
    onApiChange:applyCaptions,
    onAutoplayBlocked:()=>{blocked=true;$('player-message').textContent='Press Play inside the YouTube video to enable sound.'; $('start-player').disabled=false; $('start-player').textContent='Enable sound ▶';},
    onError:e=>{
      if(introId!==null)return;
      blocked=true;
      const messages={2:'YouTube rejected this video request.',5:'This device could not play the video.',100:'This video is private or unavailable.',101:'YouTube has blocked this video in the embedded player.',150:'YouTube has blocked this video in the embedded player.',153:'YouTube could not identify this player. The browser may be blocking its referrer.'};
      $('player-message').textContent=`YouTube error ${e.data}: ${messages[e.data] || 'Playback failed.'} The queue is preserved. Retry or skip this track.`;
      $('start-player').disabled=false; $('start-player').textContent='Retry track ▶';
      api('host/player',{client,error_code:e.data,song_id:loadedId}).catch(()=>{});
    }
  }});
};
$('start-player').onclick = async () => {
  if(ready && started) {blocked=false;loadedId=null;syncPlayer();player.playVideo();return;}
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

// Verify the native WebView's JavaScript bridge without a device or YouTube.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync('android/assets/player.html','utf8');
const source=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const calls=[];let options;
const context={
  document:{getElementById:()=>({style:{}})},
  location:{origin:'https://com.tcdataconsultants.qbeat'},
  setInterval:()=>{},
  Qbeat:new Proxy({},{get:(_,name)=>(...args)=>calls.push([name,...args])}),
  YT:{Player:function(id,config){
    options=config;
    return {loadVideoById:id=>calls.push(['load',id]),cueVideoById:id=>calls.push(['cue',id]),getPlayerState:()=>1,getOptions:()=>['captions'],unloadModule:m=>calls.push(['unload',m]),loadModule:m=>calls.push(['module',m]),getDuration:()=>120,getCurrentTime:()=>112,playVideo:()=>calls.push(['play']),pauseVideo:()=>calls.push(['pause']),stopVideo:()=>calls.push(['stop'])};
  }}
};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext("loadTrack('abcdefghijk',false)",context);
assert.equal(calls.length,0);
context.onYouTubeIframeAPIReady();options.events.onReady();
assert.deepEqual(calls,[['ready'],['load','abcdefghijk']]);
options.events.onError({data:150});assert.deepEqual(calls.at(-1),['error',150]);
assert.equal(calls.some(c=>c[0]==='ended'),false);
options.events.onStateChange({data:0});assert.deepEqual(calls.at(-1),['ended','abcdefghijk']);
vm.runInContext("loadTrack('bcdefghijkl',true)",context);assert.deepEqual(calls.at(-1),['cue','bcdefghijkl']);
vm.runInContext('idle()',context);options.events.onStateChange({data:0});assert.deepEqual(calls.at(-1),['stop']);
assert.equal(options.playerVars.origin,context.location.origin);
assert.equal(options.playerVars.controls,1);
assert.equal(options.playerVars.cc_load_policy,0);
vm.runInContext("loadTrack('abcdefghijk',false);setCaptions(false)",context);assert.deepEqual(calls.at(-1),['unload','captions']);
context.reportProgress();assert.deepEqual(calls.at(-1),['progress','abcdefghijk',112,120]);
vm.runInContext('idle()',context);const before=calls.length;context.reportProgress();assert.equal(calls.length,before);
console.log('PASS: native player initialization, deferred loading, pause, end identity, error bridge, and idle state');

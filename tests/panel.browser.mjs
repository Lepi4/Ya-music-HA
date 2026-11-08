import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const live = process.argv.includes('--live');
const haUrl = process.env.YM_HA_URL || 'http://homeassistant.local:8123';
const sshTarget = process.env.YM_HA_SSH || 'homeassistant';
const source = live
  ? await (await fetch(`${haUrl}/api/yandex_music_chaos/static/panel.js?v=0.3.1`)).text()
  : await readFile(new URL('../custom_components/yandex_music_chaos/www/panel.js', import.meta.url), 'utf8');
const calls = [];
const errors = [];
const players = [
  {entity_id:'media_player.one',name:'Station One',source:true,is_yandex_station:true,state:'idle',volume:0.5},
  {entity_id:'media_player.two',name:'Station Two',is_yandex_station:true,state:'playing',volume:0.27,title:'Current song',artist:'Artist'},
  {entity_id:'media_player.tv',name:'Unselected TV',state:'playing',volume:1,title:'TV show'},
];
const track = {id:'1',title:'Test song',artists:'Artist',duration:180};
const selectedSources = new Map();
const sourceList = ['Station','media_player.shield','media_player.shield_3'];

function remoteGet(path) {
  // The Supervisor credential stays on HA; never send it to this browser or log it.
  const script = `import os,urllib.request,urllib.error\nr=urllib.request.Request('http://supervisor/core/api/'+${JSON.stringify(path)},headers={'Authorization':'Bearer '+os.environ['SUPERVISOR_TOKEN']})\ntry:\n with urllib.request.urlopen(r,timeout=45) as f: print(f.read().decode())\nexcept urllib.error.HTTPError as e:\n print(e.read().decode()); raise SystemExit(e.code)\n`;
  return new Promise((resolve,reject) => {
    const child=spawn('ssh',['-o','BatchMode=yes',sshTarget,'python3 -']);
    let output='',stderr='';
    child.stdout.on('data',x=>output+=x);
    child.stderr.on('data',x=>stderr+=x);
    child.on('close',code=>{
      if(code) reject(new Error(`HA request ${path}: ${code} ${stderr} ${output.slice(0,200)}`));
      else {try {resolve(JSON.parse(output));} catch(e){reject(e);}}
    });
    child.stdin.end(script);
  });
}

const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',error=>errors.push(error.message));
  await page.exposeFunction('testCallApi', async (method,path,body) => {
    calls.push({method,path,body});
    assert.ok(!path.startsWith('/'), `callApi must receive a relative API path: ${path}`);
    if(live && method==='GET') return remoteGet(path);
    if(method==='POST') {
      if(path.endsWith('/select_source')) selectedSources.set(body.entity_id[0],body.source);
      return {ok:true}; // Never play/stop/change volume/source on real devices in this UI test.
    }
    if(path.startsWith('states/')) return {attributes:{media_content_id:'12345',source:selectedSources.get(path.slice(7))||'Station',source_list:sourceList}};
    if(path.endsWith('/config')) return {target_entities:players.slice(0,2).map(p=>p.entity_id)};
    if(path.endsWith('/status')) return {authorized:true,account:{login:'Test'},players,playback:{queue:[],index:-1}};
    if(path.endsWith('/players')) return {players,playback:{queue:[],index:-1}};
    if(path.endsWith('/playlists')) return {playlists:[{uid:'1',kind:'1',title:'Playlist',count:1}]};
    if(path.endsWith('/recommendations')) return {shelves:[{title:'An arbitrary title supplied by Yandex',items:[{type:'playlist',uid:'1',kind:'2',title:'Recommended playlist',count:2},{type:'album',id:'9',title:'Recommended album'}]}]};
    if(path.endsWith('/podcasts')) return {title:'Podcast catalog title from Yandex',items:[{type:'album',id:'12',title:'Podcast show'}]};
    if(path.includes('/audiobooks?')) return {title:'Аудиокниги',shelves:[{id:'catalog',title:'Books from API',items:[{type:'album',id:'31',media_kind:'audiobook',title:'Actual book',artist:'Book author'}]}],next_page:null};
    return {tracks:[track,{id:'2',title:'Another entry',artists:'Other artist',duration:120}]};
  });
  // Simulates the HA sidebar and a light HA theme, inside an embedded panel.
  await page.setContent('<style>body{margin:0;color:black;--primary-text-color:black}#ha-sidebar{position:absolute;width:220px;height:100vh;background:#eee}#panel{position:absolute;inset:0 0 0 220px}</style><aside id="ha-sidebar">HA</aside><div id="panel"></div>');
  await page.addScriptTag({type:'module',content:source});
  await page.evaluate(()=>{
    const el=document.createElement('yandex-music-chaos-panel');
    el.hass={callApi:window.testCallApi};
    document.querySelector('#panel').append(el);
  });
  await page.locator('#ym-recommendations .ym-card').first().waitFor({timeout:60000});
  await page.locator('.ym-track').first().waitFor({timeout:60000});
  assert.equal(await page.locator('#ym-error:not(.hidden)').count(),0);
  assert.ok(await page.locator('.ym-track').count()>0);
  assert.ok(await page.locator('.ym-station').count()>1);
  assert.equal(await page.locator('.ym-sidebar input, .ym-sidebar [data-station]').count(),0);
  const shownStations = await page.locator('.ym-station').count();
  const metrics = await page.evaluate(()=>{
    const el=document.querySelector('yandex-music-chaos-panel'),root=el.shadowRoot;
    const rect=node=>{const r=node.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}};
    return {shell:rect(root.querySelector('.ym-shell')),player:rect(root.querySelector('.ym-player-area')),main:rect(root.querySelector('.ym-main')),color:getComputedStyle(root.querySelector('h1')).color,version:root.querySelector('.ym-version').textContent};
  });
  assert.equal(metrics.shell.height,900);
  assert.equal(metrics.player.y,0);
  assert.ok(Math.abs(metrics.main.y-metrics.player.bottom)<1);
  assert.ok(metrics.main.bottom>900);
  assert.notEqual(metrics.color,'rgb(0, 0, 0)');
  assert.equal(metrics.version,'0.3.1');
  // Wheel events must scroll the actual workspace, including over its sticky player.
  for(const surface of ['.ym-main','.ym-player-area','.ym-sidebar','.ym-card-row']) {
    await page.evaluate(()=>document.querySelector('yandex-music-chaos-panel').querySelector('.ym-workspace').scrollTop=0);
    const bounds=await page.locator(surface).first().boundingBox();
    await page.mouse.move(bounds.x+40,Math.min(bounds.y+30,850));
    await page.mouse.wheel(0,450);
    await page.waitForTimeout(100);
    assert.ok(await page.evaluate(()=>document.querySelector('yandex-music-chaos-panel').querySelector('.ym-workspace').scrollTop)>0, `Wheel did not scroll over ${surface}`);
  }
  await page.evaluate(()=>document.querySelector('yandex-music-chaos-panel').querySelector('.ym-workspace').scrollTop=0);
  await mkdir(new URL('../artifacts/',import.meta.url),{recursive:true});
  await page.screenshot({path:fileURLToPath(new URL(`../artifacts/panel-${live?'live':'test'}-desktop.png`,import.meta.url)),fullPage:true});

  // Opening a recommendation must produce a usable track list, without starting sound.
  const playlistCard=page.locator('#ym-recommendations [data-playlist-uid]').first();
  const playlistTitle=await playlistCard.getAttribute('data-title');
  await playlistCard.click();
  await page.locator('.ym-list-toolbar').waitFor({timeout:60000});
  assert.ok(await page.locator('.ym-track').count()>0);
  assert.equal(await page.locator('#ym-heading').textContent(),playlistTitle);
  await page.locator('[data-section="home"]').click();
  await page.locator('#ym-recommendations [data-album]').first().waitFor();
  const albumCard=page.locator('#ym-recommendations [data-album]').first();
  const albumTitle=await albumCard.getAttribute('data-title');
  await albumCard.click();
  await page.locator('.ym-list-toolbar').waitFor({timeout:60000});
  assert.ok(await page.locator('.ym-track').count()>0);
  assert.equal(await page.locator('#ym-heading').textContent(),albumTitle);
  await page.locator('[data-section="home"]').click();
  await page.locator('#ym-recommendations .ym-card').first().waitFor();
  await page.locator('[data-section="podcasts"]').click();
  await page.locator('.ym-card-grid [data-album]').first().waitFor({timeout:60000});
  assert.ok(await page.locator('.ym-card').count()>0);
  await page.locator('[data-section="search"]').click();
  await page.locator('.ym-search-welcome').waitFor();
  await page.locator('[data-search-query="Сказки"]').click();
  await page.locator('#ym-content .ym-track, #ym-content .ym-card').first().waitFor({timeout:60000});
  await page.locator('[data-section="home"]').click();
  await page.locator('#ym-recommendations .ym-card').first().waitFor();
  await page.locator('[data-action="input-source"]').click();
  await page.locator('[data-input-source]').first().waitFor({timeout:60000});
  await page.keyboard.press('Escape');
  await page.locator('[data-section="audiobooks"]').click();
  await page.locator('#ym-content [data-album]').first().waitFor({timeout:60000});
  const bookTitle=await page.locator('#ym-content [data-album]').first().getAttribute('data-title');
  await page.locator('#ym-content [data-album]').first().click();
  await page.locator('.ym-list-toolbar').waitFor({timeout:60000});
  assert.equal(await page.locator('#ym-heading').textContent(),bookTitle);
  assert.ok(await page.locator('.ym-track').count()>0);
  await page.locator('[data-section="home"]').click();
  await page.locator('#ym-recommendations h2').first().waitFor();

  if(!live){
    await page.locator('[data-section="search"]').click();
    await page.locator('.ym-search-welcome').waitFor();
    assert.ok((await page.locator('[data-section="search"]').getAttribute('class')).includes('active'));
    await page.locator('#ym-search').fill('a global query');
    await page.locator('#ym-search').press('Enter');
    await page.locator('.ym-track').first().waitFor();
    assert.ok(calls.some(c=>c.path.includes('/search?q=a%20global%20query')));
    await page.locator('[data-section="likes"]').click();
    await page.locator('.ym-list-toolbar').waitFor();
    const globalCalls=calls.filter(c=>c.path.includes('/search?')).length;
    await page.locator('#ym-search').fill('Other artist');
    await page.locator('#ym-search').press('Enter');
    assert.equal(await page.locator('.ym-track').count(),1);
    assert.equal(await page.locator('.ym-track-main strong').textContent(),'Another entry');
    assert.equal(calls.filter(c=>c.path.includes('/search?')).length,globalCalls);
    await page.locator('#ym-search').fill('');
    assert.equal(await page.locator('.ym-track').count(),2);
    await page.locator('[data-section="home"]').click();
    await page.locator('#ym-recommendations h2').waitFor();
    await page.locator('[data-action="input-source"]').click();
    await page.locator('[data-input-source="media_player.shield"]').waitFor();
    await page.locator('[data-input-source="media_player.shield"]').click();
    await page.waitForTimeout(100);
    const sourceChange=calls.findLast(c=>c.path.endsWith('/select_source'));
    assert.deepEqual(sourceChange.body,{entity_id:['media_player.two'],source:'media_player.shield'});
    assert.ok((await page.locator('#ym-input-source-name').textContent()).includes('media_player.shield'));
    assert.equal(await page.locator('#ym-now-title').textContent(),'Current song');
    assert.equal(await page.locator('.ym-station').count(),2);
    assert.equal(await page.locator('[data-station="media_player.tv"]').count(),0);
    assert.equal(await page.locator('#ym-recommendations h2').textContent(),'An arbitrary title supplied by Yandex');
    await page.locator('[data-station="media_player.one"]').click();
    assert.equal(await page.locator('#ym-now-title').textContent(),'Ничего не играет');
    assert.equal(await page.locator('#ym-volume').inputValue(),'0.5');
    await page.locator('[data-cmd="toggle"]').click();
    await page.waitForTimeout(80);
    assert.deepEqual(calls.findLast(c=>c.path.endsWith('/media_play_pause')).body.entity_id,['media_player.one']);
    await page.locator('[data-station="media_player.two"]').click();
    assert.equal(await page.locator('#ym-volume').inputValue(),'0.27');
    assert.ok((await page.locator('[data-station="media_player.two"]').getAttribute('class')).includes('playing'));
    await page.locator('#ym-volume').evaluate(el=>{el.value='0.31';el.dispatchEvent(new Event('change',{bubbles:true}));});
    await page.waitForTimeout(100);
    const cmd=calls.findLast(c=>c.path.endsWith('/volume_set'));
    assert.deepEqual(cmd.body.entity_id,['media_player.two']);
    assert.equal(cmd.body.volume_level,0.31);
    // Push a state change as HA does, without waiting for polling.
    await page.evaluate(()=>{
      const el=document.querySelector('yandex-music-chaos-panel');
      el.hass={...el.hass,states:{'media_player.two':{state:'paused',attributes:{volume_level:0.43,media_title:'Changed song',media_content_id:'12345',source:'Station',source_list:['Station','media_player.shield','media_player.shield_3']}}}};
    });
    assert.equal(await page.locator('#ym-now-title').textContent(),'Changed song');
    // A focused slider is intentionally left alone until it loses focus.
    await page.locator('#ym-search').focus();
    await page.evaluate(()=>document.querySelector('yandex-music-chaos-panel').syncPlayerStates());
    assert.equal(await page.locator('#ym-volume').inputValue(),'0.43');
    await page.locator('[data-action="sources"]').click();
    assert.equal(await page.locator('[data-source]').count(),2);
    await page.locator('[data-source="media_player.two"]').uncheck();
    await page.locator('[data-source="media_player.one"]').check();
    await page.locator('[data-action="send-current"]').click();
    await page.waitForTimeout(150);
    const transfer=calls.findLast(c=>c.path.endsWith('/play_media'));
    assert.deepEqual(transfer.body.entity_id,['media_player.one']);
    assert.equal(transfer.body.media_content_id,'12345');
    assert.equal(transfer.body.media_content_type,'track');
    assert.equal(await page.locator('#ym-player-name').textContent(),'Station One');
    // Reconnect must resume polling; repeated module imports must not throw.
    await page.evaluate(()=>{const el=document.querySelector('yandex-music-chaos-panel');el.remove();document.querySelector('#panel').append(el);if(!el._pollTimer)throw Error('Polling not resumed');});
  }
  await page.addScriptTag({type:'module',content:source+'\n// second import'});
  // An earlier, slower request must never replace a newer navigation result.
  await page.evaluate(async()=>{
    const el=document.querySelector('yandex-music-chaos-panel');
    el._catalogCache.clear();
    const original=el.api.bind(el);
    el.api=async path=>{
      if(path==='/likes'){await new Promise(r=>setTimeout(r,80));return {tracks:[{id:'slow',title:'Slow old result'}]};}
      if(path==='/wave')return {tracks:[{id:'fast',title:'New wave result'}]};
      return original(path);
    };
    await Promise.all([el.loadSection('likes'),el.loadSection('wave')]);
    el.api=original;
  });
  assert.equal(await page.locator('#ym-heading').textContent(),'Моя волна');
  assert.equal(await page.locator('.ym-track-main strong').textContent(),'New wave result');
  for(const size of [{width:320,height:740},{width:390,height:844},{width:768,height:1024},{width:844,height:390}]) {
    await page.setViewportSize(size);
    await page.evaluate(()=>document.querySelector('#panel').style.left='0');
    const mobileVolume=await page.locator('#ym-volume').boundingBox();
    assert.ok(mobileVolume?.width>50);
    assert.ok(mobileVolume.y+mobileVolume.height<size.height);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const playSize=await page.locator('[data-cmd="toggle"]').boundingBox();
    assert.ok(playSize.width>=44 && playSize.height>=44);
    await page.locator('[data-action="sources"]').click();
    const dialog=await page.locator('#ym-sources-dialog').boundingBox();
    assert.ok(dialog.x>=0 && dialog.x+dialog.width<=size.width+1);
    await page.keyboard.press('Escape');
    await page.locator('[data-action="input-source"]').click();
    const inputDialog=await page.locator('#ym-input-source-dialog').boundingBox();
    assert.ok(inputDialog.x>=0 && inputDialog.x+inputDialog.width<=size.width+1);
    await page.keyboard.press('Escape');
  }
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:fileURLToPath(new URL(`../artifacts/panel-${live?'live':'test'}-mobile.png`,import.meta.url)),fullPage:true});
  // HA can mount custom panels inside a container without an explicit height.
  // The panel must fill the remaining viewport instead of ending at content height.
  await page.evaluate(()=>{
    const parent=document.querySelector('#panel');
    parent.style.cssText='position:relative;margin-top:42px;height:auto;';
    dispatchEvent(new Event('resize'));
  });
  await page.waitForTimeout(40);
  const naturalHeight=await page.locator('yandex-music-chaos-panel').boundingBox();
  assert.equal(naturalHeight.y+naturalHeight.height,844);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({live,requests:calls.length,stations:shownStations,mobileSizes:4,metrics,errors}));
} finally {await browser.close();}

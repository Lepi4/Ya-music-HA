// Render the real panel with public catalog data and demonstration player states.
// Credentials, private playlists and device names never enter the screenshots.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

export async function captureDocs(browser, source, readApi) {
  const [recommendations, stations] = await Promise.all([
    readApi('yandex_music_chaos/v1/recommendations'),
    readApi('yandex_music_chaos/v1/wave/stations'),
  ]);
  const classical = stations.stations.find(s=>s.seed==='genre:classicalmusic');
  const song = {id:'12345',title:'Лунный свет',artists:'Клод Дебюсси',duration:294,cover:classical?.cover};
  const players = [
    {entity_id:'media_player.demo_living_room',is_yandex_station:true,name:'Станция · Гостиная',state:'playing',title:song.title,artist:song.artists,media_id:song.id,duration:song.duration,position:83,volume:0.38,image:song.cover},
    {entity_id:'media_player.demo_kitchen',is_yandex_station:true,name:'Станция · Кухня',state:'paused',title:'Моя волна',artist:'Яндекс Музыка',volume:0.24},
    {entity_id:'media_player.demo_bedroom',is_yandex_station:true,name:'Станция · Спальня',state:'idle',volume:0.20},
  ].map(player=>({...player,input_source:'Станция',source_list:['Станция','media_player.shield']}));
  const playlists = recommendations.shelves.flatMap(s=>s.items).filter(i=>i.type==='playlist').slice(0,4);
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.exposeFunction('docsApi',async(method,path)=>{
      assert.equal(method,'GET','Documentation must never send commands to devices');
      if(path.startsWith('states/'))return {attributes:{source:'Станция',source_list:['Станция','media_player.shield']}};
      if(path.endsWith('/config'))return {target_entities:players.map(p=>p.entity_id)};
      if(path.endsWith('/status'))return {authorized:true,account:{login:'Демонстрационный аккаунт',plus:true},players,playback:{queue:[],index:-1}};
      if(path.endsWith('/players'))return {players,playback:{queue:[],index:-1,radio:{}}};
      if(path.endsWith('/recommendations'))return recommendations;
      if(path.endsWith('/playlists'))return {playlists};
      if(path.endsWith('/likes'))return {tracks:[song]};
      if(path.endsWith('/wave/stations'))return stations;
      if(path.endsWith('/wave/settings'))return {mood_energy:'all',moods:[{value:'all',name:'Любое'},{value:'calm',name:'Спокойное'},{value:'active',name:'Бодрое'}]};
      throw Error(`Unexpected documentation endpoint ${path}`);
    });
    await page.setContent('<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}#panel{height:100dvh}</style><div id="panel"></div>');
    await page.addScriptTag({type:'module',content:source});
    await page.evaluate(()=>{const el=document.createElement('yandex-music-chaos-panel');el.hass={callApi:window.docsApi};document.querySelector('#panel').append(el);});
    await page.locator('#ym-recommendations .ym-card').first().waitFor();
    const directory=new URL('../docs/screenshots/',import.meta.url);
    await mkdir(directory,{recursive:true});
    const shot=async name=>{
      // Wait for visible cover artwork, without fetching off-screen lazy images.
      await page.locator('img:visible').evaluateAll(images=>Promise.all(images.map(img=>img.decode().catch(()=>{}))));
      await page.screenshot({path:fileURLToPath(new URL(name,directory))});
    };
    await shot('home-desktop.png');
    await page.locator('[data-section="wave"]').click();
    await page.locator('[data-wave-group="genre:allrock"]').waitFor({state:'attached'});
    await page.locator('#ym-search').fill('блэк');
    await page.locator('#ym-search').scrollIntoViewIfNeeded();
    await shot('wave-desktop.png');
    await page.locator('#ym-search').fill('');
    await page.evaluate(()=>{
      const el=document.querySelector('yandex-music-chaos-panel');
      el.querySelectorAll('#ym-wave-stations details').forEach(group=>{group.open=false;});
      el.querySelector('.ym-workspace').scrollTop=el.querySelector('.ym-workspace').scrollHeight;
    });
    await shot('wave-categories-desktop.png');
    await page.setViewportSize({width:390,height:980});
    await page.locator('[data-section="home"]').click();
    await page.locator('#ym-recommendations .ym-card').first().waitFor();
    await shot('player-mobile.png');
    await page.locator('[data-section="wave"]').click();
    await page.locator('[data-wave-group="genre:ethnic"]').waitFor({state:'attached'});
    await page.locator('#ym-search').fill('народная');
    await page.locator('#ym-search').scrollIntoViewIfNeeded();
    await shot('wave-mobile.png');
    assert.deepEqual(errors,[]);
    return ['home-desktop.png','wave-desktop.png','wave-categories-desktop.png','player-mobile.png','wave-mobile.png'];
  } finally {await page.close();}
}

/* Integration smoke: execute the exact reference SPA against simulated FastAPI
   envelopes in a browser-like DOM. This is not a screenshot comparison. */
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

const src = readFileSync(new URL('../public/studio-edition.html', import.meta.url), 'utf8');
const bridge = readFileSync(new URL('../public/studio-live-bridge.js', import.meta.url), 'utf8');
const script = readFileSync(new URL('../public/studio-edition-app.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../public/studio-edition.css', import.meta.url), 'utf8');
assert(src.includes('<link rel="stylesheet" href="/studio-edition.css">'));
assert(src.includes('<script src="/studio-edition-app.js"></script>'));
assert(script.includes('window.KadrBridge.refresh'), 'live bootstrap must be present');

const episode = '10000000-0000-4000-8000-000000000001';
const project = '10000000-0000-4000-8000-000000000002';
const job = '10000000-0000-4000-8000-000000000003';
const failedJob = '10000000-0000-4000-8000-000000000004';
const dom = new JSDOM(src, {
  runScripts: 'outside-only', pretendToBeVisual: true,
  url: 'http://127.0.0.1:8766/studio-edition.html?screen=finishing&episode='+episode+'&job='+failedJob,
});
const { window } = dom;
const style = window.document.createElement('style');
style.textContent = css;
window.document.head.appendChild(style);
assert.equal(window.getComputedStyle(window.document.querySelector('.sidebar')).display, 'flex');
window.scrollTo = () => {};
window.structuredClone = structuredClone;
window.HTMLMediaElement.prototype.load = () => {};
window.HTMLMediaElement.prototype.pause = () => {};
window.HTMLMediaElement.prototype.play = async () => {};
const profile = {
  version: 1, revision: 0, episode_id: episode,
  video: { layout: 'portrait', zoom: 100, blur: 24, brightness: 100, vignette: 15 },
  subtitles: { enabled: true, text: '', x: 50, y: 74, font_size: 32, color: '#f6d779',
    outline: 3, background: false, align: 'center', uppercase: true, safe_guides: true },
  audio: { enabled: true, volume: .15, mode: 'single', track: null,
    fade_in: .8, fade_out: 1.3, ducking: false, part_tracks: {} },
  // Simulate an old episode-scoped cue from another completed montage.
  // Production editor must instead show captions for the selected job.
  part_overrides: { '1': {cues:[{start:0,end:2,text:'ЧУЖАЯ РЕПЛИКА'}]} },
};
const sources = [{id:'a',name:'sample.mp4',size:1500000}];
const library = {
  projects: [{id:project,title:'Проверка визуала',created_at:'2026-10-09T00:00:00Z'}],
  episodes: [{id:episode,project_id:project,number:1,title:'Серия 1',source_id:'a',
    settings:{layout:'portrait',caption_style:'classic',analysis_provider:'local'},
    jobs:[{id:failedJob,status:'failed',created_at:'2026-10-09T01:00:00Z'}, {id:job,status:'completed',created_at:'2026-10-09T00:00:00Z'}]}],
};
const jobs = [
 {id:failedJob,episode_id:episode,source_id:'a',source_name:'sample.mp4',
  created_at:'2026-10-09T01:00:00Z',status:'failed',stage:'analyzing',
  progress:.6,caption_style:'classic',layout:'portrait',outputs:[],files:[]},
 {id:job,episode_id:episode,source_id:'a',source_name:'sample.mp4',
  created_at:'2026-10-09T00:00:00Z',status:'completed',stage:'completed',
  progress:1,caption_style:'classic',layout:'portrait',
  outputs:['part_001.mp4','part_001.srt'],files:[{name:'part_001.mp4',
    url:'/api/jobs/'+job+'/files/part_001.mp4',subtitle_url:'/api/jobs/'+job+'/files/part_001.srt',duration:4}]}
];
const plan = {source:{duration:4},parts:[{index:1,duration:4,
  cuts:[{start:0,end:4}],subtitles:[{start:.1,end:3.5,text:'РЕАЛЬНАЯ РЕПЛИКА'},
    {start:3.8,end:4,text:'ДРУГАЯ РЕПЛИКА'}]}]};
let saveCalls = 0;
let savedProfileBody;
window.fetch = async (input,options={}) => {
  const p = String(input);
  let value;
  if(p==='/api/library')value=library;
  else if(p==='/api/sources')value=sources;
  else if(p==='/api/jobs')value=jobs;
  else if(p==='/api/music')value={enabled:true,volume:.15,tracks:[],mode:'single',track:null};
  else if(p==='/api/health')value={ready:true,missing:[],busy:false};
  else if(p==='/api/deepseek')value={configured:false,remaining_usd:null,model:'deepseek-chat',budget_usd:null};
  else if(p.endsWith('/plan'))value=plan;
  else if(p.endsWith('/finishing')){
    if(options.method==='PUT'){saveCalls++;savedProfileBody=JSON.parse(options.body);value={...savedProfileBody,revision:saveCalls};}
    else value=profile;
  }
  else if(p.includes('/captions'))value={job_id:job,part_index:1,cues:plan.parts[0].subtitles,revision:0};
  else throw new Error('Unexpected endpoint '+p);
  return {ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>value};
};
window.eval(bridge);
window.eval(script);
let ready = false;
for(let i=0;i<60;i++){
  if(window.document.querySelector('.fc-workspace')){ready=true;break;}
  await new Promise(resolve=>setTimeout(resolve,50));
}
assert(ready,window.document.querySelector('#main')?.textContent?.slice(0,500)||'not rendered');
assert(window.document.querySelector('.sidebar'));
assert(window.document.querySelector('.topbar'));
assert(window.document.querySelector('#fcCanvas'));
assert(window.document.querySelector('#fcVideo')?.getAttribute('src')?.includes(job));
assert(window.document.body.textContent.includes('РЕАЛЬНАЯ РЕПЛИКА'));
assert(!window.document.querySelector('.empty')?.textContent.includes('нет готового монтажа'),'failed newer job should not hide completed Shorts');
// Editing: the selected caption must stay visible while playback is paused,
// even when the playhead is outside the caption interval (e.g. at 00:00).
const videoForCaptions = window.document.querySelector('#fcVideo');
const captionOverlay = window.document.querySelector('#fcCaption');
let playbackPaused = true;
Object.defineProperty(videoForCaptions, 'paused', { configurable: true, get: () => playbackPaused });
assert.equal(captionOverlay.style.visibility, 'visible', 'paused editor must display selected caption at 00:00');
assert.equal(captionOverlay.textContent, 'РЕАЛЬНАЯ РЕПЛИКА');
assert(!window.document.body.textContent.includes('ЧУЖАЯ РЕПЛИКА'), 'another job captions leaked into editor');
playbackPaused = false;
videoForCaptions.dispatchEvent(new window.Event('play'));
videoForCaptions.currentTime = 1;
videoForCaptions.dispatchEvent(new window.Event('timeupdate'));
assert.equal(captionOverlay.style.visibility, 'visible', 'subtitle must show during spoken text');
videoForCaptions.currentTime = 3.7;
videoForCaptions.dispatchEvent(new window.Event('timeupdate'));
assert.equal(captionOverlay.style.visibility, 'hidden', 'subtitle must disappear after its end while playing');
videoForCaptions.currentTime = 0;
videoForCaptions.dispatchEvent(new window.Event('timeupdate'));
assert.equal(captionOverlay.style.visibility, 'hidden', 'subtitle must not appear before its start while playing');
playbackPaused = true;
videoForCaptions.dispatchEvent(new window.Event('pause'));
assert.equal(captionOverlay.style.visibility, 'visible', 'pausing restores selected caption for editing');
videoForCaptions.currentTime = 3.9;
videoForCaptions.dispatchEvent(new window.Event('timeupdate'));
assert.equal(captionOverlay.textContent, 'РЕАЛЬНАЯ РЕПЛИКА',
  'paused editor shows selected caption, not the unrelated cue under the playhead');
playbackPaused = false;
videoForCaptions.dispatchEvent(new window.Event('play'));
assert.equal(captionOverlay.textContent, 'ДРУГАЯ РЕПЛИКА',
  'playback switches back to the cue at the actual video time');
playbackPaused = true;
videoForCaptions.dispatchEvent(new window.Event('pause'));

const editorNav = window.document.querySelector('button[data-action="nav"][data-screen="editor"]');
assert(editorNav, 'settings navigation should exist');
editorNav.click();
assert(window.document.querySelector('#dBalance')?.textContent.includes('неизвестен'), 'null DeepSeek budget must not break rendering');
const finishingNav = window.document.querySelector('button[data-action="nav"][data-screen="finishing"]');
finishingNav.click();
for(let i=0;i<60 && !window.document.querySelector('#fcCanvas');i++) await new Promise(done=>setTimeout(done,30));
assert(window.document.querySelector('#fcCanvas'), 'editor must return after visiting settings with null balance');
for(const [tab,contains] of [['audio','Звуковое сопровождение'],['frame','Композиция кадра'],['captions','Слова в кадре']]){
  window.document.querySelector('[data-ftab="'+tab+'"]').click();
  assert(window.document.querySelector('.fc-workspace'),tab+' workspace missing');
  assert(window.document.body.textContent.includes(contains),tab+' panel not displayed');
}
window.document.querySelector('#fcSave').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert(saveCalls > 0,'save action must use real API bridge');
assert.equal(savedProfileBody.revision,0,'save must preserve revision for optimistic concurrency');
const projectsNav = window.document.querySelector('button[data-action="nav"][data-screen="projects"]');
assert(projectsNav, 'projects navigation missing');
projectsNav.click();
const overview = window.document.querySelector('.overview-stats')?.textContent || '';
assert(overview.includes('Готовых серий'), 'project summary not rendered');
const stat = [...window.document.querySelectorAll('.stat-card')].find(el=>el.textContent.includes('Готовых серий'));
assert(stat?.querySelector('strong')?.textContent.trim()==='1',
  'older completed Shorts must count as ready even if latest attempt failed');
assert(window.document.body.textContent.includes('РЕАЛЬНЫЕ ПРОЕКТЫ'), 'demo label remained in live UI');
const readyButton = window.document.querySelector('button[data-action="filter"][data-filter="ready"]');
if(readyButton){readyButton.click();assert(window.document.body.textContent.includes('Проверка визуала'), 'ready filter lost project after failed retry');}

dom.window.close();
console.log('Exact Studio Edition DOM smoke: live API, reference layout, tabs, save passed');

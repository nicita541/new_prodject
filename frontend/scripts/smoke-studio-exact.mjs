/* Integration smoke: execute the exact reference SPA against simulated FastAPI
   envelopes in a browser-like DOM. This is not a screenshot comparison. */
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

const src = readFileSync(new URL('../public/studio-edition.html', import.meta.url), 'utf8');
const bridge = readFileSync(new URL('../public/studio-live-bridge.js', import.meta.url), 'utf8');
const script = src.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert(script?.includes('window.KadrBridge.refresh'), 'live bootstrap must be present');

const episode = '10000000-0000-4000-8000-000000000001';
const project = '10000000-0000-4000-8000-000000000002';
const job = '10000000-0000-4000-8000-000000000003';
const dom = new JSDOM(src, {
  runScripts: 'outside-only', pretendToBeVisual: true,
  url: 'http://127.0.0.1:8766/studio-edition.html?screen=finishing&episode='+episode+'&job='+job,
});
const { window } = dom;
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
  part_overrides: {},
};
const sources = [{id:'a',name:'sample.mp4',size:1500000}];
const library = {
  projects: [{id:project,title:'Проверка визуала',created_at:'2026-10-09T00:00:00Z'}],
  episodes: [{id:episode,project_id:project,number:1,title:'Серия 1',source_id:'a',
    settings:{layout:'portrait',caption_style:'classic',analysis_provider:'local'},
    jobs:[{id:job,status:'completed',created_at:'2026-10-09T00:00:00Z'}]}],
};
const jobs = [{id:job,episode_id:episode,source_id:'a',source_name:'sample.mp4',
  created_at:'2026-10-09T00:00:00Z',status:'completed',stage:'completed',
  progress:1,caption_style:'classic',layout:'portrait',
  outputs:['part_001.mp4','part_001.srt'],files:[{name:'part_001.mp4',
    url:'/api/jobs/'+job+'/files/part_001.mp4',subtitle_url:'/api/jobs/'+job+'/files/part_001.srt',duration:4}]}];
const plan = {source:{duration:4},parts:[{index:1,duration:4,
  cuts:[{start:0,end:4}],subtitles:[{start:.1,end:3.5,text:'РЕАЛЬНАЯ РЕПЛИКА'}]}]};
let saveCalls = 0;
window.fetch = async (input,options={}) => {
  const p = String(input);
  let value;
  if(p==='/api/library')value=library;
  else if(p==='/api/sources')value=sources;
  else if(p==='/api/jobs')value=jobs;
  else if(p==='/api/music')value={enabled:true,volume:.15,tracks:[],mode:'single',track:null};
  else if(p==='/api/health')value={ready:true,missing:[],busy:false};
  else if(p==='/api/deepseek')value={configured:false};
  else if(p.endsWith('/plan'))value=plan;
  else if(p.endsWith('/finishing')){
    if(options.method==='PUT'){saveCalls++;value={...JSON.parse(options.body),revision:saveCalls};}
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
for(const [tab,contains] of [['audio','Звуковое сопровождение'],['frame','Композиция кадра'],['captions','Слова в кадре']]){
  window.document.querySelector('[data-ftab="'+tab+'"]').click();
  assert(window.document.querySelector('.fc-workspace'),tab+' workspace missing');
  assert(window.document.body.textContent.includes(contains),tab+' panel not displayed');
}
window.document.querySelector('#fcSave').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert(saveCalls > 0,'save action must use real API bridge');
dom.window.close();
console.log('Exact Studio Edition DOM smoke: live API, reference layout, tabs, save passed');

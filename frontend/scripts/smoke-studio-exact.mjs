/* Integration smoke: execute the production Studio against simulated FastAPI
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
const objectiveFunction = new Function(script.slice(script.indexOf('  function storyObjective(d) {'),script.indexOf('  function publicJob(j) {')) + '; return storyObjective;')();
assert.deepEqual(objectiveFunction({story_objective:{version:1,objective:'standalone_shorts',settings:{max_clips:2,preferred_max_duration:80}}}),{version:1,objective:'standalone_shorts',settings:{max_clips:2,preferred_min_duration:45,preferred_max_duration:80,max_duration:120}},'saving an existing objective must preserve custom settings');


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
window.HTMLElement.prototype.scrollIntoView = () => {};
window.structuredClone = structuredClone;
window.HTMLMediaElement.prototype.load = () => {};
window.HTMLMediaElement.prototype.pause = () => {};
window.HTMLMediaElement.prototype.play = async () => {};
// jsdom has no native top layer; real-browser verification covers geometry
// and native focus trapping. The smoke exercises our open/close lifecycle.
window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
window.HTMLDialogElement.prototype.close = function () { this.open = false; };
const profile = {
  version: 1, revision: 0, episode_id: episode,
  video: { layout: 'portrait', zoom: 100, blur: 24, brightness: 100, vignette: 15 },
  subtitles: { enabled: true, text: '', x: 50, y: 74, font_size: 32, color: '#f6d779',
    outline: 3, background: false, align: 'center', uppercase: true, safe_guides: true },
  audio: { enabled: true, volume: .15, mode: 'single', track: null,
    fade_in: .8, fade_out: 1.3, ducking: false, part_tracks: {} },
  // Simulate an old episode-scoped cue from another completed montage.
  // Production editor must instead show captions for the selected job.
  part_overrides: { '7': {cues:[{start:0,end:2,text:'ЧУЖАЯ РЕПЛИКА'}]} },
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
const plan = {review_draft:{reason:'Проверочный черновик'},source:{duration:40,width:640,height:360},parts:[{index:7,duration:4,
  cuts:[{start:10,end:12},{start:20,end:22}],subtitles:[{start:.1,end:3.5,text:'РЕАЛЬНАЯ РЕПЛИКА'},
    {start:3.8,end:4,text:'ДРУГАЯ РЕПЛИКА'}]}]};
let automation = {enabled:true,managed:true};
let analysisPackets=[];
const automationWrites = [];
let saveCalls = 0;
let exportCalls = 0;
let exportedParts = [];
const exports = new Map();
let savedProfileBody;
let savedCaptionBodies;
let releasePreviewStatus;
let holdPreviewStatus = false;
let holdExportStatus = false;
let releaseExportStatus;
let holdJobRefresh = false;
let releaseJobRefresh;
const correctedJob = '10000000-0000-4000-8000-000000000005';
const feedbackMessages = [];
let feedbackBody;
let supportedProcessingModes = ['full', 'incremental', 'plan_only'];
let launchBodies = [];
let settingsWrites = 0;
let lastEpisodeSettings;
const providerSwitches = [];
const checkSwitches = [];
const previewId = 'pv_' + '1'.repeat(32);
const recoverableExport = 'ex_' + 'e'.repeat(32);
const cancellablePreview = 'pv_' + 'a'.repeat(32);
const legacyInterrupted = 'ex_' + 'f'.repeat(32);
const finishingControls = [];
const finishingTasks = [
  {export_id:recoverableExport,source_job_id:job,status:'interrupted',resumable:true,cancellable:false,files:[]},
  {preview_id:cancellablePreview,source_job_id:job,status:'queued',resumable:true,cancellable:true,files:[]},
  {export_id:legacyInterrupted,source_job_id:job,status:'interrupted',resumable:false,cancellable:false,files:[]},
];
window.fetch = async (input,options={}) => {
  const p = String(input);
  let value;
  if(p==='/api/library')value=library;
  else if(p===`/api/jobs/${job}/finishing-tasks`)value=finishingTasks;
  else if(p.endsWith('/finishing-tasks'))value=[];
  else if((p===`/api/exports/${recoverableExport}/resume` || p===`/api/jobs/${job}/previews/${cancellablePreview}/cancel`) && options.method==='POST'){
    finishingControls.push(p);
    const task=finishingTasks.find(item=>(item.export_id||item.preview_id)===(p.includes('/previews/')?cancellablePreview:recoverableExport));
    task.status=p.endsWith('/resume')?'queued':'cancelled';task.cancellable=p.endsWith('/resume');
    value={...task};
  }
  else if(p===`/api/jobs/${failedJob}/analysis-checks` && options.method==='POST'){
    const body=JSON.parse(options.body);checkSwitches.push(body);
    const current=jobs.find(item=>item.id===failedJob);
    Object.assign(current,{economy_mode:body.economy_mode});
    library.episodes[0].settings.economy_mode=body.economy_mode;
    value=current;
  }
  else if(p===`/api/jobs/${failedJob}/analysis-provider` && options.method==='POST'){
    const body=JSON.parse(options.body);providerSwitches.push(body);
    const current=jobs.find(item=>item.id===failedJob);
    Object.assign(current,{analysis_provider:body.provider,status:'running',provider_wait:null,error:null,
                          message:'Продолжаем с сохранённых этапов'});
    library.episodes[0].settings.analysis_provider=body.provider;
    value=current;
  }
  else if(p===`/api/jobs/${failedJob}/antigravity`)value={automation,runner:{status:'error',packet:'a'.repeat(64)},packets:analysisPackets,job_directory:'F:/new_prodject/data/jobs/'+failedJob};
  else if(p.startsWith(`/api/jobs/${failedJob}/antigravity/automation?`)){
    const query=new URLSearchParams(p.split('?')[1]);
    automation={enabled:query.get('enabled')==='true',managed:query.get('managed')==='true'};
    automationWrites.push({...automation});value=automation;
  }
  else if(p.endsWith('/feedback')){
    if(options.method==='POST'){
      feedbackBody=JSON.parse(options.body);
      const corrected={...structuredClone(jobs.find(item=>item.id===job)),id:correctedJob,
        created_at:'2026-10-08T00:00:00Z',status:'running',stage:'planning',
        feedback_parent_job_id:job,outputs:[],files:[]};
      jobs.push(corrected);
      feedbackMessages.push({text:feedbackBody.text,part_index:feedbackBody.part_index,
        operation_id:feedbackBody.operation_id,job_id:correctedJob,job_status:'running',
        status:'understanding',reply:'Проверяю исходные реплики.'});
      value=corrected;
    }else value={messages:feedbackMessages};
  }
  else if(p==='/api/jobs/'+correctedJob)value=jobs.find(item=>item.id===correctedJob);
  else if(p==='/api/jobs/'+failedJob)value=jobs.find(item=>item.id===failedJob);
  else if(p==='/api/sources')value=sources;
  else if(p.startsWith('/api/jobs?'))value=jobs;
  else if(p==='/api/jobs/'+job){
    if(holdJobRefresh)await new Promise(resolve=>releaseJobRefresh=resolve);
    value=jobs.find(item=>item.id===job);
  }
  else if(p==='/api/jobs/'+job+'/exports' && options.method==='POST'){
    const body=JSON.parse(options.body);exportCalls++;exportedParts=body.part_indices;
    const id='ex_'+String(exportCalls).padStart(32,'0');
    const files=body.part_indices.map(index=>({name:`part_${String(index).padStart(3,'0')}.mp4`,part_index:index,
      url:`/api/exports/${id}/files/part_${String(index).padStart(3,'0')}.mp4`,duration:4}));
    exports.set(id,{export_id:id,status:'completed',progress:1,files});
    value={export_id:id,status:'queued'};
  }
  else if(p.startsWith('/api/exports/')){
    value=holdExportStatus ? await new Promise(resolve=>releaseExportStatus=resolve) : exports.get(p.split('/')[3]);
    if(value.status==='completed'){
      jobs.find(item=>item.id===job).files=value.files;
      jobs.find(item=>item.id===job).finishing_applied=true;
    }
  }
  else if(p==='/api/jobs/'+job+'/previews' && options.method==='POST')value={preview_id:previewId,status:'queued'};
  else if(p==='/api/jobs/'+job+'/previews/'+previewId){
    if(holdPreviewStatus)await new Promise(resolve=>releasePreviewStatus=resolve);
    value={preview_id:previewId,status:'completed',files:[],url:'/api/jobs/'+job+'/previews/'+previewId+'.mp4'};
  }
  else if(p==='/api/music')value={enabled:true,volume:.15,tracks:[],mode:'single',track:null};
  else if(p==='/api/health')value={ready:true,missing:[],busy:false,processing_modes:supportedProcessingModes};
  else if(p===`/api/episodes/${episode}/settings` && options.method==='PUT'){
    settingsWrites++;
    lastEpisodeSettings=JSON.parse(options.body);
    const data=JSON.parse(options.body);
    Object.assign(library.episodes[0],{source_id:data.source_id,settings:data});
    value=library.episodes[0];
  }
  else if(p===`/api/episodes/${episode}/jobs` && options.method==='POST'){
    const data=JSON.parse(options.body);launchBodies.push(data);
    value={...structuredClone(jobs.find(item=>item.id===job)),id:'10000000-0000-4000-8000-000000000006',
      processing_mode:data.processing_mode,status:'completed',stage:'completed',outputs:[],files:[],
      created_at:'2026-10-10T00:00:00Z'};
    jobs.push(value);
  }
  else if(p==='/api/deepseek')value={configured:false,remaining_usd:null,model:'deepseek-chat',budget_usd:null};
  else if(p.endsWith('/plan'))value=plan;
  else if(p.endsWith('/finishing/state')){
    const data=JSON.parse(options.body);
    saveCalls++;savedProfileBody=data.profile;savedCaptionBodies=data.captions;
    value={profile:{...data.profile,episode_id:episode,revision:saveCalls},
      captions:data.captions.map(item=>({...item,job_id:job,revision:item.revision+1}))};
  }
  else if(p.endsWith('/finishing')){
    if(options.method==='PUT'){saveCalls++;savedProfileBody=JSON.parse(options.body);value={...savedProfileBody,revision:saveCalls};}
    else value=profile;
  }
  else if(p.includes('/captions'))value={job_id:job,part_index:7,cues:plan.parts[0].subtitles,revision:0,target_id:'7'.repeat(64)};
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
assert.deepEqual([...window.document.querySelectorAll('.sidebar .navbtn')].map(button=>button.dataset.screen),
  ['projects','trash'], 'only library and trash belong in global navigation');
assert(!window.document.querySelector('[data-screen="api"]'), 'API console navigation must be removed');
assert(!window.document.querySelector('#fcDownloadPresets'), 'developer JSON controls must be removed');
assert(window.document.querySelector('.topbar'));
assert(window.document.querySelector('#fcCanvas'));
assert.equal(typeof window.document.querySelector('#fcVideo').ontimeupdate, 'function', 'finishing controls must finish binding');
for(let i=0;i<40&&!window.document.querySelector(`[data-task-id="${recoverableExport}"]`);i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(window.document.querySelector(`[data-finishing-control="resume"][data-task-id="${recoverableExport}"]`), 'restart must expose server-owned interrupted export');
assert(!window.document.querySelector(`[data-finishing-control="resume"][data-task-id="${legacyInterrupted}"]`), 'unknown legacy parameters must not offer resume');
window.document.querySelector(`[data-finishing-control="cancel"][data-task-id="${cancellablePreview}"]`).click();
for(let i=0;i<40&&!finishingControls.length;i++)await new Promise(resolve=>setTimeout(resolve,10));
await new Promise(resolve=>setTimeout(resolve,30));
assert.equal(finishingControls[0],`/api/jobs/${job}/previews/${cancellablePreview}/cancel`);
window.document.querySelector(`[data-finishing-control="resume"][data-task-id="${recoverableExport}"]`).click();
for(let i=0;i<40&&finishingControls.length<2;i++)await new Promise(resolve=>setTimeout(resolve,10));
await new Promise(resolve=>setTimeout(resolve,30));
assert.equal(finishingControls[1],`/api/exports/${recoverableExport}/resume`);
assert.equal(exportCalls,0,'resume must not create another export command');
assert.equal(saveCalls,0,'resume must not save current editor parameters');
finishingTasks.find(item=>item.export_id===recoverableExport).status='completed';
window.document.querySelector('[data-finishing-refresh]').click();
await new Promise(resolve=>setTimeout(resolve,30));
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

const enabledControl = window.document.querySelector('#fcCaptionEnabled');
assert(enabledControl, 'real Studio must offer an explicit subtitle visibility toggle');
enabledControl.checked = false;
enabledControl.dispatchEvent(new window.Event('change', {bubbles:true}));
assert.equal(window.document.querySelector('#fcCaption').style.visibility,'hidden',
  'disabling captions should hide the editor overlay');
enabledControl.checked = true;
enabledControl.dispatchEvent(new window.Event('change', {bubbles:true}));
assert.equal(window.document.querySelector('#fcCaption').style.visibility,'visible',
  'captions must be recoverable without resetting all finishing settings');
videoForCaptions.dataset.renderedPreview='true';
videoForCaptions.dispatchEvent(new window.Event('timeupdate'));
assert.equal(captionOverlay.style.visibility,'hidden',
  'server-rendered preview must not receive a duplicate browser caption');
videoForCaptions.dataset.renderedPreview='';
videoForCaptions.dispatchEvent(new window.Event('pause'));
const editorNav = window.document.querySelector('button[data-action="nav"][data-screen="editor"]');
assert(editorNav, 'settings navigation should exist');
editorNav.click();
assert(window.document.querySelector('#analysisSelect'), 'settings must render with unavailable legacy billing fields');
assert(!window.document.querySelector('#dBalance'), 'retired balance controls must not reappear');
const finishingNav = window.document.querySelector('button[data-action="nav"][data-screen="finishing"]');
finishingNav.click();
for(let i=0;i<60 && !window.document.querySelector('#fcCanvas');i++) await new Promise(done=>setTimeout(done,30));
assert(window.document.querySelector('#fcCanvas'), 'editor must return after visiting settings with null balance');
for(const [tab,contains] of [['audio','Звуковое сопровождение'],['frame','Композиция кадра'],['captions','Слова в кадре']]){
  window.document.querySelector('[data-ftab="'+tab+'"]').click();
  assert(window.document.querySelector('.fc-workspace'),tab+' workspace missing');
  assert(window.document.body.textContent.includes(contains),tab+' panel not displayed');
}
// Change the caption in the real editor: the combined save must contain
// the job-scoped text, not stale episode-level cues.
const editedField=window.document.querySelector('#fcCaptionText');
editedField.value='ИЗМЕНЁННАЯ РЕПЛИКА';
editedField.dispatchEvent(new window.Event('input',{bubbles:true}));
// Hold real bridge requests: success must never appear while processing or
// while finished files are still being refreshed.
holdExportStatus=true;
window.document.querySelector('#toast').textContent='Все Shorts обновлены — старое сообщение';
window.document.querySelector('#fcSave').click();
assert(window.document.querySelector('#toast').textContent.includes('началось'));
assert(window.document.querySelector('#fcProgressText').textContent.includes('началось'));
for(let i=0;i<100&&!releaseExportStatus;i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(releaseExportStatus,'export polling must begin');
assert(!window.document.querySelector('#modalHost').textContent.includes('Готовые Shorts'));
releaseExportStatus({status:'running',phase:'rendering',progress:1,part_index:7,completed_parts:0,total_parts:1,files:[]});
await new Promise(resolve=>setTimeout(resolve,30));
assert(window.document.querySelector('#fcProgressText').textContent.includes('Применяем'));
assert(!window.document.querySelector('#fcProgressText').textContent.includes('обновлены'));
assert(window.document.querySelector('#fcSave').textContent.includes('99%'),'running 100% is not success');
releaseExportStatus=null;
holdJobRefresh=true;
for(let i=0;i<180&&!releaseExportStatus;i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(releaseExportStatus);
holdExportStatus=false;
releaseExportStatus(exports.get('ex_'+String(exportCalls).padStart(32,'0')));
for(let i=0;i<100&&!releaseJobRefresh;i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(releaseJobRefresh);
assert(window.document.querySelector('#fcProgressText').textContent.includes('Завершаем'));
assert(!window.document.querySelector('#modalHost').textContent.includes('Готовые Shorts'));
holdJobRefresh=false;releaseJobRefresh();
await new Promise(resolve=>setTimeout(resolve,80));
assert(window.document.querySelector('#fcProgressText').textContent.includes('Shorts обновлены'));
assert(saveCalls > 0,'save action must use real API bridge');
assert.equal(savedCaptionBodies.length,1,'changed job captions must be batched');
assert.equal(savedCaptionBodies[0].cues[0].text,'ИЗМЕНЁННАЯ РЕПЛИКА');
assert.equal(savedCaptionBodies[0].revision,0);
assert.equal(savedCaptionBodies[0].target_id,'7'.repeat(64),'editor must echo the loaded candidate ownership');
assert.equal(savedCaptionBodies[0].part_index,7,'nonsequential part index must be preserved');
assert.equal(savedProfileBody.revision,0,'save must preserve revision for optimistic concurrency');
assert(Array.isArray(savedCaptionBodies),'save must bundle captions in one validated request');
assert(!('episode_id' in savedProfileBody), 'profile path data must not contain response-only fields');
assert.equal(exportCalls,1,'applying appearance must render, not just save JSON');
assert.deepEqual(exportedParts,[7],'apply must preserve actual part IDs');
assert(jobs.find(item=>item.id===job).files[0].url.startsWith('/api/exports/'),'review must adopt the completed file');
window.document.querySelector('#modalHost .buttons button[data-action="modal-confirm"]')?.click();
// Per-part "no music" is a real, usable control; it should never request
// /api/music/tracks/none/stream or invent a sample track.
window.document.querySelector('[data-ftab="audio"]').click();
const musicMode=window.document.querySelector('#fcMusicMode');
musicMode.value='per_part';
musicMode.dispatchEvent(new window.Event('change',{bubbles:true}));
const musicChoice=window.document.querySelector('#fcTrack');
assert(musicChoice.querySelector('option[value="none"]'),'per-part no-music option must exist');
musicChoice.value='none';
musicChoice.dispatchEvent(new window.Event('change',{bubbles:true}));
const selectedAudio=window.document.querySelector('#fcAudio');
assert(!selectedAudio.hasAttribute('src'),'per-part no-music must not request a fake track URL');
assert(window.document.querySelector('#fcSoundTag')?.textContent.includes('выключена'),
  'no-music selection should be visible in the editor');
assert(!window.document.querySelector('.fc-wave'), 'invented waveform must not appear');
// Publication settings use the source cuts, not a previously baked 9:16 card.
window.document.querySelector('[data-ftab="frame"]').click();
window.document.querySelector('[data-flayout="social"]').click();
assert(window.document.querySelector('#fcCanvas').classList.contains('social-mode'));
let socialVideo=window.document.querySelector('#fcVideo');
assert.equal(socialVideo.dataset.sourcePreview,'true');
assert(socialVideo.getAttribute('src').endsWith('/source'));
socialVideo.onloadedmetadata();
assert.equal(socialVideo.currentTime,10);
assert.equal(window.document.querySelector('#fcDuration').textContent,'0:04');
const seek=window.document.querySelector('#fcSeek');
seek.value=75;seek.dispatchEvent(new window.Event('input'));
assert.equal(socialVideo.currentTime,21,'75% of output must map to second source cut');
socialVideo.ontimeupdate();
assert.equal(window.document.querySelector('#fcTime').textContent,'0:03');
const variantControl=window.document.querySelector('#fcCardVariant');
variantControl.value='post';variantControl.dispatchEvent(new window.Event('change'));
assert(window.document.querySelector('#fcCanvas').classList.contains('post-card'));
for(const [id,value] of [['fcChannel','Канал <b>100%</b>'],['fcHandle','@my_channel'],['fcPostCaption','Подпись: [x]; 100%']]){
  const field=window.document.getElementById(id);field.value=value;
  field.dispatchEvent(new window.Event('input',{bubbles:true}));
}
assert.equal(window.document.querySelector('#fcSocialChannel').textContent,'Канал <b>100%</b>');
assert(!window.document.querySelector('#fcSocialChannel b'), 'channel must remain literal text');
assert.equal(window.document.querySelector('#fcSocialHandle').textContent,'@my_channel');
window.document.querySelector('[data-favatar="star"]').click();
assert(window.document.querySelector('#fcSocialAvatar').getAttribute('src').includes('/star.png'),'selected icon must appear in preview');
window.document.querySelector('#fcSave').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert.equal(exportCalls,2,'the new card must be rendered when applied');
assert.equal(savedProfileBody.video.card_variant,'post');
assert.equal(savedProfileBody.video.channel_handle,'@my_channel');
assert.equal(savedProfileBody.video.post_caption,'Подпись: [x]; 100%');
assert.equal(savedProfileBody.video.avatar_style,'star','icon must survive save/export');
socialVideo=window.document.querySelector('#fcVideo');
socialVideo.dataset.renderedPreview='true';
window.document.querySelector('#fcGuideToggle').click();
assert(!window.document.querySelector('#fcCanvas').classList.contains('social-mode'),
  'a baked server preview must not receive a second card');
window.document.querySelector('#fcPreviewReset').click();
assert(window.document.querySelector('#fcCanvas').classList.contains('social-mode'));
const projectsNav = window.document.querySelector('button[data-action="nav"][data-screen="projects"]');
assert(projectsNav, 'projects navigation missing');
projectsNav.click();
const overview = window.document.querySelector('.overview-stats')?.textContent || '';
assert(overview.includes('Готовых серий'), 'project summary not rendered');
const stat = [...window.document.querySelectorAll('.stat-card')].find(el=>el.textContent.includes('Готовых серий'));
assert(stat?.querySelector('strong')?.textContent.trim()==='1',
  'older completed Shorts must count as ready even if latest attempt failed');
assert(!window.document.body.textContent.includes('РЕАЛЬНЫЕ ПРОЕКТЫ'), 'developer reassurance copy must not appear in product');
assert(!window.document.querySelector('main').textContent.includes('/api/'), 'project library must not display developer routes');
const readyButton = window.document.querySelector('button[data-action="filter"][data-filter="ready"]');
if(readyButton){readyButton.click();assert(window.document.body.textContent.includes('Проверка визуала'), 'ready filter lost project after failed retry');}

// Follow the product flow from a selected project. A failed newer attempt
// must not hide a ready montage or break the contextual editor navigation.
window.document.querySelector('.project-card [data-action="go-project"]').click();
assert(window.document.querySelector('.episodes-list'), 'project must open its own episodes');
const shortsButton=window.document.querySelector('.episode-actions [data-action="open-review"]');
assert(shortsButton, 'older ready Shorts must remain accessible after a failed retry');
shortsButton.click();
assert(window.document.querySelector('.rv2-head'), 'episode must open the Shorts review');
assert(window.document.querySelector('#breadcrumbs').textContent.includes('Серия 1'), 'review must retain episode breadcrumbs');
await new Promise(resolve=>setTimeout(resolve,60));
assert(window.document.querySelector('#feedbackText'), 'review assistant must be available from playback');
assert.equal(window.document.querySelector('.rv2-maincol').children.length,2,
  'only playback and timeline may occupy the permanent workspace');
assert.equal(window.document.querySelector('#reviewParts').open,false);
assert.equal(window.document.querySelector('#reviewAssistant').open,false);
const originalPlayer=window.document.querySelector('#reviewSourceVideo');
const shortPlayer=window.document.querySelector('#reviewShortVideo');
assert(originalPlayer && shortPlayer,'both videos must remain visible together');
assert(!window.document.querySelector('.rv2-screen').textContent.includes('Черновик для просмотра'),
  'the draft banner must not consume playback space');
originalPlayer.currentTime=12;
shortPlayer.currentTime=3;
const assistantToggle=window.document.querySelector('[data-action="review-panel"][data-id="reviewAssistant"]');
assistantToggle.click();
assert.equal(window.document.querySelector('#reviewAssistant').open,true);
assert.equal(window.document.activeElement.id,'feedbackText');
const feedbackInput=window.document.querySelector('#feedbackText');
feedbackInput.value='Здесь оборвана фраза <img src=x onerror=alert(1)>';
feedbackInput.dispatchEvent(new window.Event('input'));
window.document.querySelector('#reviewAssistant [data-action="review-panel-close"]').click();
assert.equal(window.document.querySelector('#reviewAssistant').open,false);
assert.equal(window.document.activeElement,assistantToggle);
assistantToggle.click();
assert.equal(window.document.querySelector('#feedbackText'),feedbackInput);
assert(feedbackInput.value.includes('оборвана фраза'),'closing must retain unsent feedback');
window.document.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
assert.equal(window.document.querySelector('#reviewAssistant').open,false);
const partsToggle=window.document.querySelector('[data-action="review-panel"][data-id="reviewParts"]');
partsToggle.click();
assert.equal(window.document.querySelector('#reviewParts').open,true);
assert.equal(partsToggle.getAttribute('aria-expanded'),'true');
window.document.querySelector('#reviewParts').click();
assert.equal(window.document.querySelector('#reviewParts').open,false,'backdrop must close the drawer');
assert.equal(window.document.querySelector('#reviewSourceVideo'),originalPlayer);
assert.equal(window.document.querySelector('#reviewShortVideo'),shortPlayer);
assert.equal(originalPlayer.currentTime,12);
assert.equal(shortPlayer.currentTime,3);
assistantToggle.click();
window.document.querySelector('[data-action="feedback-send"]').click();
await new Promise(resolve=>setTimeout(resolve,180));
assert.equal(feedbackBody.part_index,7, 'feedback must bind to actual plan part ID');
assert.equal(typeof feedbackBody.source_time,'number');
assert.match(feedbackBody.operation_id,/^[0-9a-f-]{36}$/);
assert.equal(window.document.querySelector('#reviewSourceVideo'),originalPlayer,
  'submitting/polling feedback must preserve the playback element');
assert(!window.document.querySelector('#feedbackMessages img'), 'feedback text must never become executable HTML');
assert.equal(window.document.querySelector('[data-action="feedback-send"]').disabled,true);
const corrected=jobs.find(item=>item.id===correctedJob);
corrected.status='completed';corrected.files=structuredClone(jobs.find(item=>item.id===job).files);
feedbackMessages[0].status=feedbackMessages[0].job_status='completed';
feedbackMessages[0].reply='Новая версия готова. Предыдущий монтаж сохранён.';
window.document.querySelector('#reviewAssistant [data-action="review-panel-close"]').click();
window.document.querySelector('[data-action="review-panel"][data-id="reviewParts"]').click();
window.document.querySelector('[data-action="choose-part"]').click();
await new Promise(resolve=>setTimeout(resolve,80));
assert(window.document.querySelector('#reviewSourceVideo') && window.document.querySelector('#reviewShortVideo'),
  'choosing a part must keep source and output together');
assert.equal(window.document.querySelector('#reviewAssistant').open,false);
assert.equal(window.document.querySelector('#reviewParts').open,false);
window.document.querySelector('[data-action="review-panel"][data-id="reviewAssistant"]').click();
assert(window.document.querySelector('[data-action="feedback-open"]').textContent.includes('исправленный'));
window.document.querySelector('[data-action="feedback-open"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
assert.equal(window.document.querySelector('#reviewAttempt').value,correctedJob);
const previousAttempt=window.document.querySelector('#reviewAttempt');
previousAttempt.value=job;previousAttempt.dispatchEvent(new window.Event('change'));
assert.equal(window.document.querySelector('#reviewAttempt').value,job,
  'original montage must remain selectable after correction');
window.document.querySelector('[data-action="review-mode"][data-id="short"]').click();
assert(window.document.querySelector('#reviewShortVideo'));
assert(!window.document.querySelector('#reviewSourceVideo'));
window.document.querySelector('[data-action="review-next"]').click();
assert(!window.document.querySelector('#reviewSourceVideo'),'part navigation must preserve the chosen viewing mode');
window.document.querySelector('[data-action="review-mode"][data-id="source"]').click();
assert(window.document.querySelector('#reviewSourceVideo'));
assert(!window.document.querySelector('#reviewShortVideo'));
assert.equal(window.document.querySelector('[data-action="review-mode"][data-id="source"]').getAttribute('aria-pressed'),'true');
window.document.querySelector('[data-action="review-mode"][data-id="compare"]').click();
assert(window.document.querySelector('#reviewSourceVideo') && window.document.querySelector('#reviewShortVideo'));
window.document.querySelector('.rv2-clip.removed').click();
assert(window.document.querySelector('.rv2-clip.removed.active'));
assert(window.document.querySelector('#reviewSourceVideo') && window.document.querySelector('#reviewShortVideo'),
  'inspecting a removed scene must keep the rendered part visible');
window.document.querySelector('[data-action="review-next"]').click();
assert(window.document.querySelector('#reviewSourceVideo') && window.document.querySelector('#reviewShortVideo'),
  'transport part navigation must keep both players');
window.document.querySelector('.episode-navigation [data-screen="processing"]').click();
assert(window.document.querySelector('#stageRows'), 'montage must be accessible from its episode');
assert(window.document.querySelector('[data-action="retry-job"][data-id="'+failedJob+'"]'),
  'contextual montage must show latest failed attempt after previous ready Shorts');
assert(!window.document.querySelector('main').textContent.includes('/api/'), 'processing must not display developer routes');
window.document.querySelector('.episode-navigation [data-screen="finishing"]').click();
assert(window.document.querySelector('#fcCanvas'), 'finishing must remain accessible after processing');
window.document.querySelector('.episode-navigation [data-screen="editor"]').click();
assert(window.document.querySelector('#analysisSelect'), 'episode settings must remain accessible after finishing');
assert(!window.document.querySelector('#sourceSelect'), 'video import must not require a library selector');
assert(window.document.querySelector('[data-action="upload-video"]'));
const processingMenu = window.document.querySelector('#processingMenu');
assert(processingMenu.closest('.launch-split'), 'mode menu must be attached to the launch button');
assert.equal(window.document.querySelectorAll('[data-action="processing-mode"]').length, 3);
assert.equal(window.document.querySelector('[data-action="launch"]').dataset.processingMode, 'incremental');
assert.equal(processingMenu.open, false);
processingMenu.querySelector('summary').click();
assert.equal(processingMenu.open, true);
window.document.querySelector('[data-action="processing-mode"][data-id="plan_only"]').click();
assert.equal(processingMenu.open, false);
assert(window.document.querySelector('#processingModeHint').textContent.includes('Без моделей и экспорта'));
assert(window.document.querySelector('[data-action="launch"]').textContent.includes('Пересобрать план'));
window.document.querySelector('[data-action="processing-mode"][data-id="incremental"]').click();
assert(!window.document.querySelector('#editorCard').open, 'card fields must start in a closed dialog');
window.document.querySelector('#editCardButton').click();
assert(window.document.querySelector('#editorCard').open);
assert.equal(window.document.querySelector('#socialChannel').value,savedProfileBody.video.channel_name,
  'saved finishing appearance must rebase the previously opened episode settings');
const phoneCard=window.document.querySelector('.phone-social-card');
assert.equal(window.getComputedStyle(phoneCard).backgroundColor,'rgb(27, 48, 66)',
  'post preview must use the renderer messenger color');
assert.equal(window.getComputedStyle(phoneCard).borderRadius,'3.52cqw',
  'post preview must not retain legacy seven-pixel corners');
assert(window.document.querySelector('#editorPhone').style.getPropertyValue('--social-height'),
  'phone preview geometry must be computed from the source aspect ratio');
const compact=window.document.querySelector('#socialVariant');
compact.value='compact';compact.dispatchEvent(new window.Event('change'));
assert.equal(window.document.querySelector('#socialHandleField').hidden,false,
  'compact card must retain its channel handle like the renderer');
const draftName=window.document.querySelector('#socialChannel');
draftName.value='Несохранённый черновик';draftName.dispatchEvent(new window.Event('input'));
window.document.querySelector('#editorCard [data-action="editor-panel-close"]').click();
assert(!window.document.querySelector('#editorCard').open);
assert.equal(window.document.activeElement.id, 'editCardButton');
window.document.querySelector('[data-action="editor-panel"][data-id="editorMusic"]').click();
assert(window.document.querySelector('#editorMusic').open);
window.document.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape'}));
assert(!window.document.querySelector('#editorMusic').open);
window.document.querySelector('.episode-navigation [data-screen="finishing"]').click();
window.document.querySelector('[data-ftab="frame"]').click();
const nextName=window.document.querySelector('#fcChannel');
nextName.value='Новое сохранённое имя';nextName.dispatchEvent(new window.Event('input'));
window.document.querySelector('#fcSave').click();
await new Promise(resolve=>setTimeout(resolve,150));
window.document.querySelector('#modalHost .buttons button[data-action="modal-confirm"]')?.click();
window.document.querySelector('.episode-navigation [data-screen="editor"]').click();
assert.equal(window.document.querySelector('#socialChannel').value,'Несохранённый черновик',
  'rebasing must preserve an intentional unsaved settings field');
window.document.querySelector('.episode-navigation [data-screen="finishing"]').click();
window.document.querySelector('[data-flayout="portrait"]').click();
assert.equal(window.document.querySelector('#fcVideo').dataset.sourcePreview,'true',
  'removing a baked card must preview source cuts, not the already styled MP4');
assert(window.document.querySelector('#fcVideo').getAttribute('src').endsWith('/source'));
window.document.querySelector('[data-ftab="captions"]').click();
let baked=window.document.querySelector('#fcVideo');
baked.dataset.renderedPreview='true';window.document.querySelector('#fcGuideToggle').click();
let subtitleSize=window.document.querySelector('#fcSize');
subtitleSize.value='44';subtitleSize.dispatchEvent(new window.Event('input',{bubbles:true}));
assert.notEqual(baked.dataset.renderedPreview,'true','subtitle edits must invalidate a baked preview');
assert.equal(window.document.querySelector('#fcCaption').style.visibility,'visible');
holdPreviewStatus=true;window.document.querySelector('#fcPreviewRequest').click();
for(let i=0;i<50&&!releasePreviewStatus;i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(releasePreviewStatus,'preview request must reach status polling');
subtitleSize.value='38';subtitleSize.dispatchEvent(new window.Event('input',{bubbles:true}));
holdPreviewStatus=false;releasePreviewStatus();
await new Promise(resolve=>setTimeout(resolve,100));
assert.notEqual(window.document.querySelector('#fcVideo').dataset.renderedPreview,'true',
  'a pending preview rendered with old settings must not overwrite newer edits');

// Opening an existing hash bookmark must retain its requested episode/job.
const bookmark=new JSDOM(src,{runScripts:'outside-only',pretendToBeVisual:true,
  url:'http://127.0.0.1:8766/#episode/'+episode+'/review/'+job});
bookmark.window.scrollTo=()=>{};bookmark.window.structuredClone=structuredClone;
bookmark.window.HTMLMediaElement.prototype.load=()=>{};
bookmark.window.HTMLMediaElement.prototype.pause=()=>{};
bookmark.window.HTMLMediaElement.prototype.play=async()=>{};
bookmark.window.fetch=window.fetch;
bookmark.window.eval(bridge);bookmark.window.eval(script);
for(let i=0;i<50&&!bookmark.window.document.querySelector('.rv2-head');i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(bookmark.window.document.querySelector('.rv2-head'),'hash bookmark must open the Shorts review');
assert.equal(bookmark.window.location.hash,'');
assert.equal(new URLSearchParams(bookmark.window.location.search).get('job'),job);
bookmark.window.close();

// Applying all supported parts must not fall over at the old fifty-part cap.
const template=structuredClone(plan.parts[0]);
plan.parts.splice(0,plan.parts.length,...Array.from({length:51},(_,i)=>({...structuredClone(template),index:i+1})));
window.document.querySelector('[data-ftab="frame"]').click();
window.document.querySelector('#fcSave').click();
await new Promise(resolve=>setTimeout(resolve,200));
assert.deepEqual(exportedParts,Array.from({length:51},(_,i)=>i+1));
// A failed update replaces the previous success result and never reports completion.
holdExportStatus=true;releaseExportStatus=null;
window.document.querySelector('#fcSave').click();
assert(!window.document.querySelector('#modalHost').textContent.includes('Готовые Shorts'));
assert(window.document.querySelector('#toast').textContent.includes('началось'));
for(let i=0;i<100&&!releaseExportStatus;i++)await new Promise(resolve=>setTimeout(resolve,10));
assert(releaseExportStatus);
holdExportStatus=false;
releaseExportStatus({status:'failed',progress:0,error:'Проверочная ошибка рендера',files:[]});
await new Promise(resolve=>setTimeout(resolve,60));
assert(window.document.querySelector('#fcProgress').classList.contains('failed'));
assert(window.document.querySelector('#toast').textContent.includes('Проверочная ошибка'));
assert(!window.document.querySelector('#modalHost').textContent.includes('Готовые Shorts'));
assert.equal(window.document.querySelector('#fcSave').disabled,false);
// A plan-only result is inspected on the original source; absent videos must
// not masquerade as completed Shorts or expose dead download actions.
const cachedPlanJob = jobs.find(item => item.id === job);
cachedPlanJob.processing_mode = 'plan_only';
cachedPlanJob.outputs = [];
cachedPlanJob.files = [];
window.document.querySelector('.episode-navigation [data-screen="processing"]').click();
window.document.querySelector(`[data-action="open-job"][data-id="${job}"]`).click();
await new Promise(resolve=>setTimeout(resolve,80));
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert(window.document.querySelector('[data-action="open-review"]'), window.document.querySelector('main').textContent);
window.document.querySelector('[data-action="open-review"]').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert(window.document.body.textContent.includes('Проверка плана'));
assert(window.document.querySelector('#reviewSourceVideo'));
assert(!window.document.querySelector('#reviewShortVideo'));
assert.equal(window.document.querySelector('[data-action="download-mp4"]').disabled, true);
assert.equal(window.document.querySelector('[data-action="review-mode"][data-id="compare"]').disabled,true);
assert.equal(window.document.querySelector('[data-action="review-mode"][data-id="short"]').disabled,true);
// A stale server used to ignore processing_mode and start its default full
// run. Reject it before saving settings or creating any job.
window.document.querySelector('.episode-navigation [data-screen="editor"]').click();
window.document.querySelector('[data-action="processing-mode"][data-id="plan_only"]').click();
supportedProcessingModes = undefined;
const writesBeforeStaleLaunch = settingsWrites;
window.document.querySelector('[data-action="launch"]').click();
await new Promise(resolve=>setTimeout(resolve,80));
assert.equal(launchBodies.length,0,'an old backend must never receive a selective launch');
assert.equal(settingsWrites,writesBeforeStaleLaunch,'capability check must happen before settings mutations');
assert(window.document.querySelector('#toast').textContent.includes('Перезапустите'));
supportedProcessingModes = ['full','incremental','plan_only'];
const objectiveSelect = window.document.querySelector('#storyObjective');
assert.equal(objectiveSelect.value,'episode_condensation');
objectiveSelect.value='standalone_shorts';
objectiveSelect.dispatchEvent(new window.Event('change'));
window.document.querySelector('[data-action="launch"]').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert.deepEqual(launchBodies.map(({operation_id,...body})=>body),[{processing_mode:'plan_only'}], 'the split button must submit its displayed mode');
assert.match(launchBodies[0].operation_id,/^[0-9a-f-]{36}$/);
assert.deepEqual(lastEpisodeSettings.story_objective,{version:1,objective:'standalone_shorts',settings:{max_clips:3,preferred_min_duration:45,preferred_max_duration:90,max_duration:120}});
assert(window.document.querySelector('[data-action="open-review"]').textContent.includes('Проверить план'));
window.document.querySelector('.sidebar [data-screen="trash"]').click();
assert(window.document.querySelector('main').textContent.includes('Корзина'), 'global trash must remain available');

// Managed exchange needs no shell command and preserves an explicit manual opt-out.
jobs.find(item=>item.id===failedJob).analysis_provider='antigravity_manual';
window.document.querySelector('.sidebar [data-screen="projects"]').click();
window.document.querySelector(`[data-action="go-project"][data-id="${project}"]`).click();
window.document.querySelector(`[data-action="open-episode"][data-id="${episode}"]`).click();
window.document.querySelector('.episode-navigation [data-screen="processing"]').click();
window.document.querySelector(`[data-action="open-job"][data-id="${failedJob}"]`).click();
await new Promise(resolve=>setTimeout(resolve,120));
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
assert(window.document.querySelector('main').textContent.includes('автоматическая обработка'));
assert(!window.document.querySelector('main').textContent.includes('powershell -NoProfile'));
window.document.querySelector('[data-action="manual-auto"]').click();
await new Promise(resolve=>setTimeout(resolve,100));
assert.deepEqual(automationWrites,[{enabled:false,managed:true}]);
assert(window.document.querySelector('[data-action="manual-auto"]').textContent.includes('Включить'));
window.document.querySelector('[data-action="manual-auto"]').click();
await new Promise(resolve=>setTimeout(resolve,100));
assert.deepEqual(automationWrites,[{enabled:false,managed:true},{enabled:true,managed:true}]);
jobs.find(item=>item.id===failedJob).status='waiting_analysis';
analysisPackets=[{id:'a'.repeat(64),purpose:'choose_units',status:'error',error:'Antigravity: требуется восстановить авторизацию в официальном CLI'}];
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
assert(window.document.querySelector('#stageMessage').textContent.includes('восстановить авторизацию'));
jobs.find(item=>item.id===failedJob).status='running';
jobs.find(item=>item.id===failedJob).provider_wait={reason:'quota',resume_at:'2026-10-13T18:17:50Z'};
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
assert(window.document.querySelector('#stageMessage').textContent.includes('Продолжим автоматически'));
assert(window.document.querySelector('#stageMessage').textContent.includes(new Date('2026-10-13T18:17:50Z').toLocaleDateString('ru-RU')));
jobs.find(item=>item.id===failedJob).status='cancelled';
jobs.find(item=>item.id===failedJob).message='Обработка отменена';
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
assert(!window.document.querySelector('#stageMessage').textContent.includes('Продолжим автоматически'));

// Switch the running Antigravity job directly and keep editor preferences in step.
jobs.find(item=>item.id===failedJob).status='running';
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
const providerSelect=window.document.querySelector('#jobAnalysisSelect');
assert(providerSelect, 'Processing must expose a provider selector for the active job');
providerSelect.value='deepseek_plan';
providerSelect.dispatchEvent(new window.Event('change',{bubbles:true}));
const switchButton=window.document.querySelector('[data-action="switch-analysis-provider"]');
assert.equal(switchButton.disabled,false);
switchButton.click();
await new Promise(resolve=>setTimeout(resolve,180));
assert.deepEqual(providerSwitches,[{provider:'deepseek_plan',resume:true}]);
assert.equal(window.document.querySelector('#jobAnalysisSelect').value,'deepseek_plan');
assert.equal(window.document.querySelector('[data-action="switch-analysis-provider"]').disabled,true);
assert(!window.document.querySelector('[data-action="manual-auto"]'));
const economySwitch=window.document.querySelector('#jobEconomyMode');
assert(economySwitch.checked, 'Economy defaults to enabled');
assert.equal(window.document.querySelectorAll('.stage-row.check-disabled').length,5);
assert(![...window.document.querySelectorAll('.stage-row.check-disabled')].some(row=>row.textContent.includes('Проверка конкретного выбора')));
economySwitch.checked=false;
economySwitch.dispatchEvent(new window.Event('change',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,180));
assert.deepEqual(checkSwitches,[{economy_mode:false,resume:true}]);
assert.equal(window.document.querySelectorAll('.stage-row.check-disabled').length,0);
jobs.find(item=>item.id===failedJob).status='cancelled';
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
const stoppedSwitch=window.document.querySelector('#jobEconomyMode');
stoppedSwitch.checked=true;
stoppedSwitch.dispatchEvent(new window.Event('change',{bubbles:true}));
await new Promise(resolve=>setTimeout(resolve,180));
assert.deepEqual(checkSwitches[1],{economy_mode:true,resume:false});
assert.equal(jobs.find(item=>item.id===failedJob).status,'cancelled');
window.document.querySelector('.episode-navigation [data-screen="editor"]').click();
assert.equal(window.document.querySelector('#analysisSelect').value,'deepseek_plan');
assert(window.document.querySelector('#editEconomyMode').checked);

// Draft videos are viewable in processing without becoming approved outputs.
const draftURL='/api/jobs/'+failedJob+'/drafts/draft_'+'a'.repeat(20)+'/files/part_001.mp4';
jobs.find(item=>item.id===failedJob).latest_outcome={status:'needs_review',accepted:[],declined:[],technical_failures:[],
  drafts:[{id:'draft_'+'a'.repeat(20),status:'rendered_needs_review',export_eligible:false,video_url:draftURL}]};
window.document.querySelector('.episode-navigation [data-screen="processing"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
window.document.querySelector(`[data-action="open-job"][data-id="${failedJob}"]`).click();
await new Promise(resolve=>setTimeout(resolve,120));
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,120));
const draftVideo=window.document.querySelector('video[controls]');
assert(draftVideo && draftVideo.getAttribute('src')===draftURL,'draft must have its own review-only video URL');
assert(window.document.body.textContent.includes('Связность истории пока не подтверждена'));
assert.equal(jobs.find(item=>item.id===failedJob).files.length,0,'draft must not become a ready file');

// The visible committed publication remains editable after a failed attempt.
jobs.find(item=>item.id===job).status='failed';
jobs.find(item=>item.id===job).published_revision='a'.repeat(64);
window.document.querySelector(`[data-action="open-job"][data-id="${job}"]`).click();
await new Promise(resolve=>setTimeout(resolve,100));
window.document.querySelector('[data-action="read-job"]').click();
await new Promise(resolve=>setTimeout(resolve,100));
window.document.querySelector('.episode-navigation [data-screen="finishing"]').click();
await new Promise(resolve=>setTimeout(resolve,100));
assert(window.document.querySelector('.fc-workspace'),'failed job with publication must open finishing');
const exportsBeforeFailedAttempt=exportCalls;
window.document.querySelector('#fcSave').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert.equal(exportCalls,exportsBeforeFailedAttempt+1,'apply must reach the API for a prior committed publication');
assert.equal(jobs.find(item=>item.id===job).status,'failed','finishing must not change the analysis attempt status');
window.document.querySelector('#modalHost .buttons button[data-action="modal-confirm"]')?.click();
window.document.querySelector('#fcPreviewRequest').click();
await new Promise(resolve=>setTimeout(resolve,150));
assert.equal(window.document.querySelector('#fcVideo').dataset.renderedPreview,'true',
  'preview must work for a prior committed publication after a failed attempt');

dom.window.close();
console.log('Exact Studio Edition DOM smoke: live API, reference layout, tabs, save passed');

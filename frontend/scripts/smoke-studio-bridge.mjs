/* Verify Studio Edition's REAL API adapter without a running video service. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const win = new JSDOM('<!doctype html><body></body>', {
  runScripts:'outside-only',url:'http://127.0.0.1:8765/',
}).window;
win.eval(readFileSync(new URL('../public/studio-live-bridge.js', import.meta.url),'utf8'));
const project='10000000-0000-4000-8000-000000000001';
const episode='10000000-0000-4000-8000-000000000002';
const job='10000000-0000-4000-8000-000000000003';
const archivedProject='10000000-0000-4000-8000-000000000004';
const archivedEpisode='10000000-0000-4000-8000-000000000005';
let sources=[{id:'source-1',name:'one.mp4'}];
let status='completed';
let publishedRevision;
let librarySnapshot={
 projects:[{id:project,title:'Real project'}],
 episodes:[{id:episode,project_id:project,number:1,jobs:[{id:job}]}],
};
const db={projects:[],episodes:[],sources:[],jobs:[],plans:{},music:{tracks:['FAKE DEMO.mp3']},
          deepseek:{configured:true,remaining_usd:999}};
const ui={projectId:null,episodeId:null,jobId:null};
const jobListRequests=[];
win.fetch=async(input,opts={})=>{
  const url=String(input);
  if(['/api/music','/api/health','/api/deepseek'].includes(url))throw new Error('503 optional service');
  let data;
  if(url==='/api/library')data=librarySnapshot;
  else if(url==='/api/sources')data=sources;
  else if(url.startsWith('/api/jobs?')){
    jobListRequests.push(url);
    data=[{id:job,created_at:'2026-10-09T01:00:00Z',status,source_id:'source-1',published_revision:publishedRevision}];
  }
  else if(url==='/api/jobs/'+job&&opts.method==='GET')data={
    id:job,created_at:'2026-10-09T01:00:00Z',status,source_id:'source-1',
  };
  else if(url==='/api/jobs/'+job+'/retry'&&opts.method==='POST'){
    status='queued';
    data={id:job,status};
  }
  else if(url==='/api/jobs/'+job+'/analysis-provider'&&opts.method==='POST'){
    const body=JSON.parse(opts.body);
    assert.equal(body.provider,'deepseek_plan');assert.equal(body.resume,true);
    status='running';data={id:job,status,analysis_provider:body.provider};
  }
  else if(url==='/api/jobs/'+job+'/plan')data={source:{duration:8},parts:[]};
  else throw new Error('Unexpected call '+url+' '+opts.method);
  return {ok:true,headers:{get:()=> 'application/json'},json:async()=>data};
};

await win.KadrBridge.refresh(db,ui);
assert.equal(jobListRequests[0],'/api/jobs?summary=true',
  'Opening projects must not load historical diagnostic maps');
assert.equal(db.projects[0].title,'Real project');
assert.equal(db.music.tracks.length,0,'Fake demo audio must not survive music API outage');
assert.equal(db.music.enabled,false);
assert(!('folder' in db.music), 'Offline mode never invents an absolute Windows folder');

assert.equal(db.deepseek.configured,false,'Never show fake configured DeepSeek');
assert.equal(db.deepseek.remaining_usd,null);
assert.equal(ui.jobId,job);
assert.equal(db.jobs[0].episode_id,episode,'Link legacy job to library episode');
ui.screen='processing';
await win.KadrBridge.refresh(db,ui);
assert.equal(jobListRequests.at(-1),'/api/jobs?summary=true&progress_job_id='+job,
  'Processing must request detailed counters only for its selected job');
ui.screen='projects';

sources=[{id:'source-2',name:'new.mp4'}];
await win.KadrBridge.request('GET','/api/sources',null,db,ui);
assert.equal(db.sources[0].name,'new.mp4','Manual refresh must update visible sources');

status='failed';
await win.KadrBridge.request('GET','/api/jobs/'+job,null,db,ui);
assert.equal(db.jobs[0].status,'failed','Manual job status refresh must update visible job');

db.plans[job]={duration:999,parts:[{index:1}]};
await win.KadrBridge.request('POST','/api/jobs/'+job+'/retry',{},db,ui);
assert.equal(db.jobs[0].status,'queued');
assert.equal(db.plans[job],undefined,'Retry must not reuse stale plan cuts');
db.plans[job]={duration:999,parts:[{index:1}]};
await win.KadrBridge.request('POST','/api/jobs/'+job+'/analysis-provider',
                            {provider:'deepseek_plan',resume:true},db,ui);
assert.equal(db.jobs[0].status,'running');
assert.equal(db.plans[job],undefined,'Provider switch must invalidate the visible prior plan');

librarySnapshot={
 projects:[...librarySnapshot.projects,{id:archivedProject,title:'Archived',archived_at:'2026-10-09T00:00:00Z'}],
 episodes:[...librarySnapshot.episodes,{id:archivedEpisode,project_id:archivedProject,number:2,jobs:[]}],
};
ui.projectId=archivedProject;
ui.episodeId=archivedEpisode;
ui.jobId=job;
await win.KadrBridge.refresh(db,ui);
assert.equal(ui.projectId,project,'Archived project must not remain selected');
assert.equal(ui.episodeId,episode,'Archived project child must not remain selected');
assert.equal(ui.jobId,job,'Active episode keeps its own job');

// Loading a real 36-part montage must not launch 36 simultaneous HTTP
// caption queries. Missing cache entries are fetched in bounded batches.
status='completed';
const originalFetch=win.fetch;
const payloads=Array.from({length:36},(_,index)=>({index:index+1}));
db.plans[job]={source:{duration:150},duration:150,parts:payloads};
db.finishing={ [episode]:{revision:0} };
let inFlight=0,maxInFlight=0,captionRequests=0;
win.fetch=async(input,opts={})=>{
  const route=String(input);
  if(route.startsWith('/api/jobs/'+job+'/parts/')&&route.endsWith('/captions')){
    inFlight++;maxInFlight=Math.max(maxInFlight,inFlight);captionRequests++;
    await new Promise(resolve=>setTimeout(resolve,2));
    inFlight--;
    const partIndex=Number(route.split('/')[5]);
    return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({
      job_id:job,part_index:partIndex,revision:0,cues:[],
    })};
  }
  return originalFetch(input,opts);
};
await win.KadrBridge.refresh(db,ui);
ui.jobId=job;
await win.KadrBridge.loadSelected(db,ui);
assert.equal(captionRequests,36,'All 36 parts must be resolved');
assert(maxInFlight<=4,'Too many caption requests at once: '+maxInFlight);
await win.KadrBridge.loadSelected(db,ui);
assert.equal(captionRequests,36,'Cached captions must not be re-fetched');
assert.equal(db.captionOverrides[job+':36'].part_index,36);
win.fetch=originalFetch;

// Publication rank changes invalidate captions and cuts together. Preserve
// unsaved words separately rather than applying them to the new rank.
publishedRevision='revision-a';
await win.KadrBridge.refresh(db,ui);
db.plans[job]={parts:[{index:1,candidate_id:'a'}]};
db.captionOverrides={[job+':1']:{part_index:1,target_id:'a'.repeat(64),revision:0,
  cues:[{start:0,end:1,text:'Unsaved A'}]}};
db.finishDirtyCues={[job+':1']:true};
publishedRevision='revision-b';
await win.KadrBridge.refresh(db,ui);
assert.equal(db.plans[job],undefined);
assert.equal(db.captionOverrides[job+':1'],undefined);
assert.equal(db.finishDirtyCues[job+':1'],undefined);
assert.equal(db.captionDraftConflicts[job][0].cues[0].text,'Unsaved A');

// A lost submission response must retain the operation UUID until confirmation.
const operations=[];
let loseResponse=true;
win.fetch=async(input,opts={})=>{
  if(String(input)==='/api/episodes/'+episode+'/jobs'){
    operations.push(JSON.parse(opts.body).operation_id);
    if(loseResponse){loseResponse=false;throw new Error('response lost');}
    return {ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>({id:job,status:'queued'})};
  }
  return originalFetch(input,opts);
};
await assert.rejects(win.KadrBridge.request('POST','/api/episodes/'+episode+'/jobs',{processing_mode:'incremental'},db,ui),/response lost/);
await win.KadrBridge.request('POST','/api/episodes/'+episode+'/jobs',{processing_mode:'incremental'},db,ui);
assert.equal(operations[0],operations[1]);
assert.match(operations[0],/^[0-9a-f-]{36}$/);
assert.equal(win.sessionStorage.length,0,'confirmed submissions clear pending tokens');
// Changed persisted episode settings form a different submission even after a lost response.
loseResponse=true;
await assert.rejects(win.KadrBridge.request('POST','/api/episodes/'+episode+'/jobs',{processing_mode:'incremental'},db,ui),/response lost/);
const lostOperation=operations.at(-1);
db.episodes.find(item=>item.id===episode).settings={caption_style:'classic',story_objective:{version:1,objective:'standalone_shorts',settings:{max_clips:2}}};
await win.KadrBridge.request('POST','/api/episodes/'+episode+'/jobs',{processing_mode:'incremental'},db,ui);
assert.notEqual(operations.at(-1),lostOperation,'changed settings must not replay the prior operation');
// A finishing command retains its operation across an ambiguous POST and a
// page reload, and removes response-only profile fields before identity.
for (const kind of ['exports','previews']) {
  const path='/api/jobs/'+job+'/'+kind;
  const attempts=[];
  const payload=kind==='exports'?{part_indices:[7],settings:{episode_id:episode,revision:4,video:{zoom:100}}}
    : {part_index:7,from:0,duration:5,settings:null};
  let lose=true;
  win.fetch=async(input,opts={})=>{
    if(String(input)===path){
      const body=JSON.parse(opts.body);attempts.push(body);
      if(lose){lose=false;throw new Error('finishing response lost');}
      const key=kind==='exports'?'export_id':'preview_id';
      return {ok:true,status:202,headers:{get:()=> 'application/json'},json:async()=>({[key]:(kind==='exports'?'ex_':'pv_')+'a'.repeat(32),status:'queued'})};
    }
    throw new Error('confirmed finishing must not depend on unrelated library refresh');
  };
  await assert.rejects(win.KadrBridge.request('POST',path,payload,db,ui),/finishing response lost/);
  // Reload erases JS memory while the browser retains pending request storage.
  const reloadedDb={...db,pendingOperations:{}};
  await win.KadrBridge.request('POST',path,payload,reloadedDb,ui);
  assert.equal(attempts[0].operation_id,attempts[1].operation_id,kind+' must reuse exact operation after reload');
  assert.match(attempts[0].operation_id,/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  if(kind==='exports'){
    assert(!('episode_id' in attempts[0].settings));
    assert(!('revision' in attempts[0].settings));
  }else assert.equal(attempts[0].settings,null,'omitted profile marker must survive request identity');
  await win.KadrBridge.request('POST',path,payload,reloadedDb,ui);
  assert.notEqual(attempts[1].operation_id,attempts[2].operation_id,'confirmed command permits a new explicit intent');
  lose=true;
  await assert.rejects(win.KadrBridge.request('POST',path,payload,reloadedDb,ui),/finishing response lost/);
  const changed=kind==='exports'?{...payload,part_indices:[8]}:{...payload,duration:6};
  await win.KadrBridge.request('POST',path,changed,reloadedDb,ui);
  assert.notEqual(attempts[3].operation_id,attempts[4].operation_id,'changed finishing parameters require a new operation');
}
// Known tasks are reconstructed from the server, independently of local tabs.
win.fetch=async(input)=>{
  assert.equal(String(input),'/api/jobs/'+job+'/finishing-tasks');
  return {ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>[
    {export_id:'ex_'+'b'.repeat(32),source_job_id:job,status:'interrupted',resumable:true},
  ]};
};
await win.KadrBridge.loadFinishingTasks(db,job);
assert.equal(db.finishingTasks[job][0].status,'interrupted');
assert.equal(db.finishingTasks[job][0].resumable,true);
win.fetch=originalFetch;
// Failed reruns retain access to an earlier published plan.
db.jobs.find(item=>item.id===job).status='failed';
db.jobs.find(item=>item.id===job).published_revision=1;
delete db.plans[job];
await win.KadrBridge.loadSelected(db,ui);
assert(db.plans[job],'published revision remains reviewable after a failed rerun');
win.close();
console.log('Studio live bridge: optional APIs, retries and 36-part bounded loading PASS');

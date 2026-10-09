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
let librarySnapshot={
 projects:[{id:project,title:'Real project'}],
 episodes:[{id:episode,project_id:project,number:1,jobs:[{id:job}]}],
};
const db={projects:[],episodes:[],sources:[],jobs:[],plans:{},music:{tracks:['FAKE DEMO.mp3']},
          deepseek:{configured:true,remaining_usd:999}};
const ui={projectId:null,episodeId:null,jobId:null};
win.fetch=async(input,opts={})=>{
  const url=String(input);
  if(['/api/music','/api/health','/api/deepseek'].includes(url))throw new Error('503 optional service');
  let data;
  if(url==='/api/library')data=librarySnapshot;
  else if(url==='/api/sources')data=sources;
  else if(url==='/api/jobs')data=[{id:job,created_at:'2026-10-09T01:00:00Z',status,
                                   source_id:'source-1'}];
  else if(url==='/api/jobs/'+job&&opts.method==='GET')data={
    id:job,created_at:'2026-10-09T01:00:00Z',status,source_id:'source-1',
  };
  else if(url==='/api/jobs/'+job+'/retry'&&opts.method==='POST'){
    status='queued';
    data={id:job,status};
  }
  else if(url==='/api/jobs/'+job+'/plan')data={source:{duration:8},parts:[]};
  else throw new Error('Unexpected call '+url+' '+opts.method);
  return {ok:true,headers:{get:()=> 'application/json'},json:async()=>data};
};

await win.KadrBridge.refresh(db,ui);
assert.equal(db.projects[0].title,'Real project');
assert.equal(db.music.tracks.length,0,'Fake demo audio must not survive music API outage');
assert.equal(db.music.enabled,false);
assert(!('folder' in db.music), 'Offline mode never invents an absolute Windows folder');

assert.equal(db.deepseek.configured,false,'Never show fake configured DeepSeek');
assert.equal(db.deepseek.remaining_usd,null);
assert.equal(ui.jobId,job);
assert.equal(db.jobs[0].episode_id,episode,'Link legacy job to library episode');

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

win.close();
console.log('Studio live bridge: optional API failure, real refresh and retry invalidation PASS');

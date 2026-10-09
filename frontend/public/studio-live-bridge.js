/* KADR STUDIO / LIVE.  Exact reference DOM/CSS; real same-origin FastAPI.
   No demo records are ever sent to the server. */
(() => {
 'use strict';
 async function get(path,options={}){
  const response=await fetch(path,{credentials:'same-origin',...options});
  const type=response.headers.get('content-type')||'';
  const value=type.includes('json')?await response.json():{url:path};
  if(!response.ok){
   const detail=value?.detail;
   const e=new Error(typeof detail==='string'?detail:
     Array.isArray(detail)?detail.map(v=>v.msg||'Ошибка').join('; '):
     'Ошибка HTTP '+response.status);
   e.status=response.status;
   throw e;
  }
  return value;
 }
 const date=value=>{
   const n=typeof value==='number'?value:Date.parse(value||'');
   return Number.isFinite(n)?n:Date.now();
 };
 async function refresh(db,ui){
  const [library,sources,jobs,music,health]=await Promise.all([
    get('/api/library'),get('/api/sources'),get('/api/jobs'),get('/api/music'),get('/api/health')
  ]);
  db.projects=library.projects||[];
  db.episodes=library.episodes||[];
  db.sources=sources||[];
  db.jobs=(jobs||[]).map(j=>({
   ...j,created_at:date(j.created_at),updated_at:date(j.updated_at),
   episode_id:j.episode_id||library.episodes?.find(e=>e.jobs?.some(a=>a.id===j.id))?.id,
  }));
  db.health=health;
  db.music={...db.music,...music,tracks:music.tracks||[]};
  db.plans ||= {};
  db.finishing ||= {};
  const completed=db.jobs.filter(j=>j.status==='completed');
  await Promise.all(completed.map(async j=>{
    if(!db.plans[j.id]){
      try{db.plans[j.id]=await get('/api/jobs/'+encodeURIComponent(j.id)+'/plan')}
      catch(e){console.warn('KADR plan:',j.id,e)}
    }
  }));
  await Promise.all(completed.map(async j=>{
    const eid=j.episode_id;
    if(eid&&!db.finishing[eid]){
      try{db.finishing[eid]=await get('/api/episodes/'+encodeURIComponent(eid)+'/finishing')}
      catch(e){console.warn('KADR finish:',eid,e)}
    }
  }));
  try{db.deepseek=await get('/api/deepseek')}catch{}
  if(!db.projects.some(p=>p.id===ui.projectId&&!p.archived_at)){
    ui.projectId=db.projects.find(p=>!p.archived_at)?.id||null;
  }
  if(!db.episodes.some(e=>e.id===ui.episodeId&&!e.archived_at)){
    ui.episodeId=db.episodes.find(e=>e.project_id===ui.projectId&&!e.archived_at)?.id||
                 db.episodes.find(e=>!e.archived_at)?.id||null;
  }
  if(!db.jobs.some(j=>j.id===ui.jobId)){
    const list=db.jobs.filter(j=>j.episode_id===ui.episodeId);
    ui.jobId=list.find(j=>j.status==='completed')?.id||list[0]?.id||null;
  }
 }
 async function request(method,path,body,db,ui){
  let options={method};
  if(!['GET','HEAD'].includes(method)&&body!=null){
    if(body.file instanceof File){
      const form=new FormData();form.append('file',body.file);
      options.body=form;
    }else if(body instanceof FormData){
      options.body=body;
    }else{
      let data=body;
      if(method==='PUT'&&/^\/api\/episodes\/[^/]+\/finishing$/.test(path)){
        const {episode_id,revision,...profile}=body;data=profile;
      }
      if(method==='POST'&&/\/api\/jobs\/[^/]+\/(?:previews|exports)$/.test(path)&&body.settings){
        const {episode_id,revision,...settings}=body.settings;
        data={...body,settings};
      }
      options.headers={'Content-Type':'application/json'};
      options.body=JSON.stringify(data);
    }
  }
  const result=await get(path,options);
  if(method==='GET'){
    if(path==='/api/music')db.music={...db.music,...result};
    else if(path==='/api/health')db.health=result;
    else if(path==='/api/library')await refresh(db,ui);
    else if(/^\/api\/jobs\/[^/]+\/plan$/.test(path)){
      db.plans[path.split('/')[3]]=result;
    }
  }else if(method==='PUT'&&/^\/api\/episodes\/[^/]+\/finishing$/.test(path)){
    db.finishing ||= {};db.finishing[path.split('/')[3]]=result;
  }else if(method==='PUT'&&/\/captions$/.test(path)){
    db.captionOverrides ||= {};
    db.captionOverrides[path.split('/')[3]+':'+path.split('/')[5]]=result;
  }else{
    await refresh(db,ui);
  }
  return result;
 }
 window.KadrBridge={get,refresh,request};
})();
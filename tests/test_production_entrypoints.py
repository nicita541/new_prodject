"""Guard the real Windows startup against accidental demo regressions."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_old_interface_shortcut_delegates_to_real_entrypoint():
    shortcut = (ROOT / "ПОСМОТРЕТЬ_ИНТЕРФЕЙС.bat").read_text(encoding="utf-8")
    assert 'call "%~dp0start.bat"' in shortcut
    assert ".venv" not in shortcut
    assert "8766" not in shortcut
    assert "create_studio_demo" not in shortcut


def test_production_entrypoint_uses_portable_runtime_and_real_build():
    launcher = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert r"tools\python\python.exe" in launcher
    assert r"frontend\dist\studio-edition.html" in launcher
    assert r"frontend\dist\studio-live-bridge.js" in launcher
    assert 'fc /b "%~dp0frontend\\public\\studio-edition.html"' in launcher
    assert 'fc /b "%~dp0frontend\\public\\studio-live-bridge.js"' in launcher
    assert "npm.cmd run build" in launcher
    assert "http://127.0.0.1:8765" in launcher
    assert "create_studio_demo" not in launcher


def test_studio_is_the_only_built_interface():
    import json
    package = json.loads((ROOT/'frontend/package.json').read_text('utf-8'))
    assert package['scripts']['build'] == 'node scripts/build-studio.mjs'
    assert not (ROOT/'frontend/src').exists()
    assert not (ROOT/'app/static').exists()
    source = (ROOT/'frontend/public/studio-edition-app.js').read_text('utf-8')
    for name in ('DEMO_MP4_BASE64','function seed(', 'function examplePlan(', 'function handleRequest(', 'function mockFinishRoute('):
        assert name not in source


def test_no_synthetic_demo_is_shipped_as_startup_code():
    assert not (ROOT / "scripts" / "create_studio_demo.py").exists()


def test_live_studio_labels_and_transport_match_real_data():
    """Execute production render/transport functions with fake local media/API."""
    node = ROOT / 'tools' / 'node' / 'node.exe'
    if not node.exists():
        import pytest
        pytest.skip('Portable Node is unavailable')
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('frontend/public/studio-edition-app.js','utf8');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{
 textContent:'',innerHTML:'',style:{},dataset:{},classList:{toggle(){}},listeners:{},
 addEventListener(name,fn){(this.listeners[name] ||= []).push(fn)},
 querySelector(){return null},setAttribute(name,value){this[name]=value},focus(){},paused:true,readyState:4,duration:1420,
 play(){this.paused=false;this.emit('play');return Promise.resolve()},
 pause(){this.paused=true;this.emit('pause')},
 emit(name){for(const fn of this.listeners[name]||[])fn()},
 });return elements.get(id)}
const context=vm.createContext({console,URL,URLSearchParams,structuredClone,
 performance,Intl,Date,setTimeout(){},clearTimeout(){},setInterval(){},clearInterval(){},
 localStorage:{getItem(){return null},setItem(){}},
 document:{getElementById:element,addEventListener(){},querySelector(){return null},querySelectorAll(){return []}},
 window:{KadrBridge:{},addEventListener(){}},location:{search:''},navigator:{},Blob,File,FormData,TextEncoder,atob});
const expose=`window.audit={renderReview,renderProcessing,renderApi,bindReview,doAction,routes,exemplarRoute,request,tokenLabel,processingRows,processingProgress,processingStageRows,renderPacketSummary,processingMessage,
 setup(){
  db.projects=[{id:'p1',title:'Project',created_at:1}];
  db.episodes=[{id:'e1',project_id:'p1',number:1,settings:{analysis_provider:'local',layout:'cinema',caption_style:'accent'}}];
  db.sources=[{id:'s1',name:'source.mp4',size:100}];
  db.jobs=[{id:'j1',episode_id:'e1',source_id:'s1',status:'completed',stage:'completed',progress:1,created_at:1,outputs:[],files:[]}];
  db.plans={j1:{duration:1420,events:[],parts:[{index:1,duration:10,cuts:[{start:0,end:10}],subtitles:[]}],quality_summary:{available:false},debug_timeline:{available:false}}};
  ui.projectId='p1';ui.episodeId='e1';ui.jobId='j1';ui.reviewMode='compare';},
 job(){return currentJob();},data(){return db},entries(){return ui.apiEntries}};})();`;
vm.runInContext(source.split('// Live Studio Edition: preserve')[0]+expose,context);
const app=context.window.audit;assert.equal(app.data().projects.length,0);assert.equal(app.data().jobs.length,0);app.setup();
assert(!app.renderReview().includes('Демо: встроенные ролики'));
assert(app.renderReview().includes('Реальные видео'));
assert(!app.renderProcessing().includes('Имитация сообщений'));
assert(app.renderProcessing().includes('Сводка статуса'));
assert.equal(app.processingMessage({message:'Обработка завершилась с ошибкой',error:'FFmpeg: отсутствует звуковой поток'}),'FFmpeg: отсутствует звуковой поток');
assert.equal(app.processingMessage({message:'Antigravity: исчерпана квота',error:null}),'Antigravity: исчерпана квота');
const savedError=app.job().error;
app.job().error='Ошибка JSON <script>invalid</script>';
assert(app.renderProcessing().includes('Ошибка JSON &lt;script&gt;invalid&lt;/script&gt;'));
assert(!app.renderProcessing().includes('<script>invalid</script>'));
app.job().error=savedError;
const zero={local:{total_tokens:0,calls:0},deepseek:{total_tokens:0,calls:0},all_tokens:0,unknown_calls:0};
assert.equal(app.tokenLabel(zero),'Нет сохранённых данных о токенах');
assert(!app.renderProcessing().includes('Из фактических ответов API'));
assert.equal(app.tokenLabel({...zero,unknown_calls:2}),'Статистика токенов не предоставлена · 2 ответов без статистики токенов');
const reportedZero={...zero,local:{total_tokens:0,calls:1}};
assert(app.tokenLabel(reportedZero).includes('Локально: 0'));
assert(app.tokenLabel(reportedZero).includes('Всего: 0 токенов (1 запросов со статистикой)'));
assert(app.tokenLabel(reportedZero).includes('DeepSeek: нет данных'));
assert(app.tokenLabel({...reportedZero,unknown_calls:1}).includes('Известно: 0 токенов'));
assert(!app.tokenLabel({...reportedZero,unknown_calls:1}).includes('Всего:'));

assert(!app.renderProcessing().includes('stage_progress из'));
const selection={status:'running',stage:'condense',progress:.475,stage_progress:{condense:{status:'running',fraction:.25,completed:92,total:368}}};
assert.equal(app.processingRows(selection).titles.status,'pending');
assert.equal(app.processingProgress(selection).percent,25);
assert(app.processingStageRows(selection).includes('Проверка титров и заставок'));
const titles={...selection,analysis_passes:{visual_analysis:{status:'completed',fraction:1},story_refinement:{status:'completed',fraction:1},titles:{status:'running',fraction:null}}};
assert.equal(app.processingRows(titles).story_refinement.status,'completed');
assert.equal(app.processingRows(titles).titles.status,'running');
assert.equal(app.processingProgress(titles).percent,null);
assert(app.processingProgress(titles).label.includes('Проверка титров и заставок'));
const globalCheck={...titles,stage:'global_verify',analysis_passes:{...titles.analysis_passes,titles:{status:'completed',fraction:1},global_visual_verification:{status:'running',fraction:null}}};
assert.equal(app.processingRows(globalCheck).visual_analysis.status,'completed');
assert.equal(app.processingRows(globalCheck).global_visual_verification.status,'running');
const countedGlobal={...globalCheck,analysis_passes:{...globalCheck.analysis_passes,global_visual_verification:{status:'running',fraction:null,completed:6,total:129}}};
assert.equal(app.processingRows(countedGlobal).global_visual_verification.completed,6);
assert(app.processingStageRows(countedGlobal).includes('6 из 129'));
assert.equal(app.processingProgress(countedGlobal).percent,null);
const processedGlobal={...globalCheck,analysis_passes:{...globalCheck.analysis_passes,global_visual_verification:{status:'running',fraction:7/129,completed:7,total:129}}};
assert.equal(app.processingRows(processedGlobal).global_visual_verification.completed,7);
assert.equal(app.processingProgress(processedGlobal).percent,5);
const failedTitles={...titles,status:'failed',analysis_passes:{...titles.analysis_passes,titles:{status:'failed',fraction:null}}};
assert.equal(app.processingRows(failedTitles).titles.status,'failed');
assert(app.processingStageRows(failedTitles).includes('Ошибка'));
assert(app.processingStageRows({...titles,analysis_passes:{titles:{status:'not_required',fraction:null}}}).includes('Не потребовалось'));
assert.equal(app.processingProgress({...titles,status:'completed'}).percent,100);
const packetSummary=app.renderPacketSummary([{id:'abc123',purpose:'choose_units',status:'ready'},{id:'xyz789',purpose:'story_refinement',status:'error',batch_size:4}], 'j1',false);
assert(packetSummary.includes('1 готовы · 0 ожидают · 1 с ошибкой в истории'));
assert(packetSummary.includes('<details class="expand" id="manualPacketDetails">'));
assert(!packetSummary.includes('id="manualPacketDetails" open'));
assert(packetSummary.includes('Импортировать результат'));
assert(!app.renderApi().includes('в демо'));
assert(!app.renderApi().includes('демонстрационную базу'));
for(const [method,path] of app.routes)assert(!/balance|recovery|spending|reset-budget/.test(path),path);
assert(app.exemplarRoute(['POST','/api/import']).unavailable);
assert(app.exemplarRoute(['GET','/api/jobs/{id}/previews/{preview_id}']).unavailable);
assert(app.exemplarRoute(['GET','/api/exports/{export_id}']).unavailable);
app.data().previews={selected:{preview_id:'selected',source_job_id:'j1'},other:{preview_id:'other',source_job_id:'j2'}};
assert.equal(app.exemplarRoute(['GET','/api/jobs/{id}/previews/{preview_id}']).path,'/api/jobs/j1/previews/selected');
app.bindReview();
const button=element('rvPlayButton'),video=element('reviewShortVideo');
assert.equal(button.textContent,'▷ Смотреть');
video.play();assert.equal(button.textContent,'Ⅱ Пауза');
video.pause();assert.equal(button.textContent,'▷ Смотреть');
video.play();video.paused=true;video.emit('ended');assert.equal(button.textContent,'▷ Смотреть');
const calls=[];
context.fetch=async(path,options)=>{
 calls.push({path,options});
 assert(!('onResponse' in options));
 let value,status=200;
 if(path.endsWith('/previews')){value={preview_id:'real-preview',source_job_id:'j1',status:'queued'};status=202}
 else if(path.endsWith('/exports')){value={export_id:'real-export',status:'queued'};status=202}
 else if(path==='/api/library')value={projects:[],episodes:[]};
 else if(['/api/jobs','/api/sources'].includes(path))value=[];
 else if(path==='/api/music')value={tracks:[]};
 else if(path==='/api/health')value={ready:true};
 else if(path==='/api/deepseek')value={configured:false};
 else assert.fail('Unexpected mocked path: '+path);
 return {ok:true,status,headers:{get(){return 'application/json'}},json:async()=>value};
};
vm.runInContext(fs.readFileSync('frontend/public/studio-live-bridge.js','utf8'),context);
async function checkBridge(){
 const db={projects:[],episodes:[],jobs:[]},ui={};let status;
 await context.window.KadrBridge.request('POST','/api/jobs/j1/previews',{part_index:1},db,ui,v=>status=v);
 assert.equal(status,202);assert.equal(db.previews['real-preview'].status,'queued');
 await context.window.KadrBridge.request('POST','/api/jobs/j1/exports',{part_indices:[1]},db,ui,v=>status=v);
 assert.equal(status,202);assert.equal(db.exports['real-export'].status,'queued');
 await app.request('POST','/api/jobs/j1/previews',{part_index:1});
 assert.equal(app.entries()[0].status,202);
 console.log('PASS: live copy, task catalog, HTTP status and media play/pause/ended');
}
checkBridge().catch(error=>{console.error(error);process.exitCode=1});
'''
    result = subprocess.run([str(node), '-e', script], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr

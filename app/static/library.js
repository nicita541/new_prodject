"use strict";

function libraryCount(n, forms) { const last=n%10, tail=n%100; return `${n} ${forms[tail>=11 && tail<=14 ? 2 : last===1 ? 0 : last>=2 && last<=4 ? 1 : 2]}`; }

// Screens own navigation; the existing engine owns import, processing and playback.
const libraryUI = {
  data: {projects: [], episodes: []}, episode: null, project: null,
  view: 'projects', revision: 0, loaded: false, cardKey: '', wasRunning: false,
  async refreshLibrary() { this.data=await api('/api/library'); this.loaded=true; },
  alive(episode) { return !episode.archived_at && this.data.projects.some(p=>p.id===episode.project_id && !p.archived_at); },
  projects() { return this.data.projects.filter(p=>!p.archived_at); },
  episodes(projectId) { return this.data.episodes.filter(e=>this.alive(e) && (!projectId || e.project_id===projectId)); },
  running(episode) { return this.attempts(episode).some(j=>['running','queued'].includes(j.status)); },
  deleteButton(label,kind,item) {
    const button=document.createElement('button'); button.type='button'; button.className='danger-button'; button.textContent=label;
    button.disabled=kind==='project' ? this.episodes(item.id).some(e=>this.running(e)) : this.running(item);
    button.addEventListener('click',()=>this.archive(kind,item.id)); return button;
  },
  async archive(kind,id) {
    if(state.busyAction) return;
    state.busyAction=true;
    const parent=this.data.episodes.find(e=>e.id===id)?.project_id;
    try {
      await api(`/api/${kind==='project' ? 'projects' : 'episodes'}/${id}`,{method:'DELETE'});
      await this.refreshLibrary();
      const hash=kind==='project' ? '#projects' : `#project/${parent}`;
      this.notice={hash,text:`${kind==='project' ? 'Проект' : 'Серия'} перемещён${kind==='project' ? '' : 'а'} в корзину. Восстановить можно в меню «Корзина».`};
      location.hash=hash; await this.route();
    } catch(error) { setText('library-message',error.message); }
    finally { state.busyAction=false; this.controls(); }
  },
  async restore(kind,id) {
    if(state.busyAction) return; state.busyAction=true;
    try {
      await api(`/api/${kind==='project' ? 'projects' : 'episodes'}/${id}/restore`,{method:'POST'});
      await this.refreshLibrary(); this.cardKey=''; this.renderCards();
      setText('library-message',`${kind==='project' ? 'Проект восстановлен' : 'Серия восстановлена'}. Он${kind==='project' ? '' : 'а'} снова доступ${kind==='project' ? 'ен' : 'на'} в меню проектов.`);
    } catch(error) { setText('library-message',error.message); }
    finally { state.busyAction=false; this.controls(); }
  },
  controls() {
    $('delete-current-project').disabled=state.busyAction || (this.project && this.episodes(this.project.id).some(e=>this.running(e)));
    $('delete-current-episode').disabled=state.busyAction || (this.episode && this.running(this.episode));
  },
  attempts(episode=this.episode) {
    if(!episode) return [];
    const ids=new Set((episode.jobs ?? []).map(j=>j.id));
    return state.jobs.filter(j=>j.episode_id===episode.id || ids.has(j.id));
  },
  async route() {
    this.routing=true;
    const revision=++this.revision; this.cardKey=''; this.wasRunning=false;
    const parts=location.hash.slice(1).split('/');
    let view='projects', project=null, episode=null;
    if(parts[0]==='trash') view='trash';
    if(parts[0]==='project') { project=this.projects().find(p=>p.id===parts[1]); if(project) view='episodes'; }
    if(parts[0]==='episode') {
      episode=this.episodes().find(e=>e.id===parts[1]);
      project=this.projects().find(p=>p.id===episode?.project_id);
      if(episode && project) view=parts[2]==='review' ? 'review' : 'edit';
    }
    this.view=view; this.project=project; this.episode=episode;
    $('player').pause(); $('source-player').pause(); state.sourceSelection=null;
    state.selected=null; state.selectedJob=null; state.timeline=null; state.timelineKey=''; state.filesKey=''; state.files=[];
    $('job-panel').hidden=true; $('timeline-panel').hidden=true; $('source-panel-review').hidden=true; $('results-panel').hidden=true;
    for(const name of ['projects','episodes','edit','review','trash']) $(`${name}-screen`).hidden=name!==view;
    if(this.notice?.hash!==location.hash) this.notice=null;
    setText('library-message',this.notice?.text ?? ''); setText('form-message','');
    this.heading(); this.renderCards(); this.controls();
    if(view==='episodes') $('episode-number').value=String(Math.max(0,...this.episodes(project.id).map(e=>e.number))+1);
    $('edit-review-link').hidden=true;
    if(!episode) { updateControls(); this.routing=false; return; }
    $('review-edit-link').href=`#episode/${episode.id}/edit`;
    const attempts=this.attempts();
    const requested=attempts.find(j=>j.id===parts[3]);
    const selected=(view==='review' ? (requested?.status==='completed' ? requested : attempts.find(j=>j.status==='completed')) : attempts[0]);
    if(view==='edit') {
      $('analysis-provider').value=episode.settings.analysis_provider;
      $('layout').value=episode.settings.layout; $('caption-style').value=episode.settings.caption_style;
      renderProvider(); renderEditing(); musicUI.load();
      setText('episode-source-note',episode.source_id ? 'Одно видео закреплено за этой серией. Для другой серии создайте отдельный подпроект.' : 'Выбранное видео будет закреплено за этим подпроектом после сохранения настроек.');
      try { await loadSources(episode.source_id ?? ''); } catch(error) { setText('form-message',error.message); }
      if(revision!==this.revision) return;
      $('source').value=episode.source_id ?? ''; sourceChanged();
      this.wasRunning=['running','queued'].includes(selected?.status);
    }
    this.renderAttempts();
    $('review-empty').hidden=view!=='review' || !!selected;
    if(selected && revision===this.revision) await selectJob(selected.id);
    if(revision===this.revision) { this.heading(); updateControls(); this.routing=false; }
  },
  heading() {
    const crumbs=[];
    const link=(label,href)=>{const a=document.createElement('a'); a.textContent=label; a.href=href; return a;};
    crumbs.push(link('Проекты','#projects'));
    if(this.project) crumbs.push(link(this.project.title,`#project/${this.project.id}`));
    if(this.episode) crumbs.push(link(this.episode.title,`#episode/${this.episode.id}/edit`));
    if(this.view==='trash') crumbs.push(link('Корзина','#trash'));
    $('breadcrumbs').replaceChildren(...crumbs);
    setText('workspace-title',this.view==='trash' ? 'Корзина' : this.view==='projects' ? 'Проекты аниме' : this.view==='episodes' ? this.project.title : this.view==='edit' ? `${this.episode.title} · настройки монтажа` : `${this.episode.title} · проверка`);
    setText('screen-context',this.view==='trash' ? 'Можно восстановить' : this.episode ? this.project.title : this.view==='episodes' ? libraryCount(this.episodes(this.project.id).length,['серия','серии','серий']) : libraryCount(this.projects().length,['проект','проекта','проектов']));
  },
  renderCards() {
    const key=JSON.stringify([this.view,this.project?.id,this.data.projects,this.data.episodes,state.jobs.map(j=>[j.id,j.status,j.files?.length])]);
    if(key===this.cardKey) return; this.cardKey=key;
    if(this.view==='projects') {
      $('projects-empty').hidden=this.projects().length>0;
      $('project-cards').replaceChildren(...this.projects().map((project,index)=>{
        const wrapper=document.createElement('article'); wrapper.className='item-card-wrap';
        const card=document.createElement('a'); card.className='item-card'; card.href=`#project/${project.id}`;
        const mark=document.createElement('span'); mark.className=`project-monogram color-${index%4}`; mark.textContent=project.title.slice(0,1).toUpperCase();
        const name=document.createElement('h2'); name.textContent=project.title; name.className='card-title';
        const meta=document.createElement('p'); const episodes=this.episodes(project.id);
        const ready=episodes.filter(e=>this.attempts(e).some(j=>j.status==='completed')).length;
        meta.className='card-meta'; meta.textContent=`Серий: ${episodes.length} · готовы: ${ready}`;
        const action=document.createElement('span'); action.className='btn-text card-actions'; action.textContent='Открыть проект';
        card.append(mark,name,meta,action); wrapper.append(card,this.deleteButton('Удалить проект','project',project)); return wrapper;
      }));
    }
    if(this.view==='episodes') {
      const episodes=this.episodes(this.project.id).sort((a,b)=>a.number-b.number);
      $('episodes-empty').hidden=episodes.length>0;
      $('episode-cards').replaceChildren(...episodes.map(episode=>{
        const card=document.createElement('article'); card.className='item-card';
        const number=document.createElement('span'); number.className='card-icon'; number.textContent=String(episode.number).padStart(2,'0');
        const name=document.createElement('h2'); name.textContent=episode.title; name.className='card-title';
        const attempts=this.attempts(episode); const current=attempts[0], ready=attempts.find(j=>j.status==='completed');
        const meta=document.createElement('p'); meta.className='card-meta'; meta.textContent=current ? `${statuses[current.status] ?? current.status} · монтажей: ${attempts.length}` : episode.source_id ? 'Видео добавлено · монтаж не запускался' : 'Добавьте видео этой серии';
        const actions=document.createElement('div'); actions.className='card-actions';
        const edit=document.createElement('a'); edit.className='btn-secondary'; edit.textContent='Настроить монтаж'; edit.href=`#episode/${episode.id}/edit`; actions.append(edit);
        if(ready) { const review=document.createElement('a'); review.className='btn-text'; review.textContent=`Проверить шортсы (${ready.files?.length ?? 0})`; review.href=`#episode/${episode.id}/review/${ready.id}`; actions.append(review); }
        actions.append(this.deleteButton('Удалить серию','episode',episode));
        card.append(number,name,meta,actions); return card;
      }));
    }
    if(this.view==='trash') {
      const entries=[...this.data.projects.filter(p=>p.archived_at).map(item=>({kind:'project',item})),
        ...this.data.episodes.filter(e=>e.archived_at && this.projects().some(p=>p.id===e.project_id)).map(item=>({kind:'episode',item}))];
      $('trash-empty').hidden=entries.length>0;
      $('trash-cards').replaceChildren(...entries.map(({kind,item})=>{
        const card=document.createElement('article'); card.className='item-card';
        const name=document.createElement('h2'); name.textContent=item.title;
        const meta=document.createElement('p'); meta.className='card-meta'; meta.textContent=kind==='project' ? 'Проект · вместе со всеми сериями' : this.data.projects.find(p=>p.id===item.project_id).title;
        const button=document.createElement('button'); button.type='button'; button.className='secondary-button'; button.textContent=kind==='project' ? 'Восстановить проект' : 'Восстановить серию';
        button.addEventListener('click',()=>this.restore(kind,item.id)); card.append(name,meta,button); return card;
      }));
    }
  },
  renderAttempts() {
    const completed=this.attempts().filter(j=>j.status==='completed');
    const key=JSON.stringify(completed.map(j=>[j.id,j.status]));
    if($('episode-attempt').getAttribute('data-key')!==key) {
      $('episode-attempt').setAttribute('data-key',key);
      $('episode-attempt').replaceChildren(...completed.map((job,index)=>{
        const option=document.createElement('option'); option.value=job.id;
        option.textContent=`${index===0 ? 'Последний монтаж' : 'Предыдущий монтаж'} · ${dateLabel(job.created_at)}`; return option;
      }));
    }
    if(state.selected) $('episode-attempt').value=state.selected;
    const ready=completed[0]; $('edit-review-link').hidden=!ready;
    if(ready) $('edit-review-link').href=`#episode/${this.episode.id}/review/${ready.id}`;
  },
  onJobs() {
    if(!this.loaded) return; this.renderCards(); this.controls(); if(this.episode) this.renderAttempts();
    if(this.episode && !state.selected && !this.routing && this.attempts().some(j=>this.view==='review' ? j.status==='completed' : true)) this.route().catch(error=>setText('library-message',error.message));
  },
  onJob(job) {
    if(!this.episode || !this.attempts().some(j=>j.id===job.id)) return;
    this.heading();
    if(this.view==='edit') {
      if(['running','queued'].includes(job.status)) this.wasRunning=true;
      if(job.status==='completed' && this.wasRunning) { this.wasRunning=false; location.hash=`episode/${this.episode.id}/review/${job.id}`; }
    }
  },
  async save() {
    const episode=this.episode;
    if(!episode || !['edit'].includes(this.view)) throw new Error('Сначала откройте настройки серии');
    if(!$('source').value) throw new Error('Выберите видео этой серии');
    const saved=await api(`/api/episodes/${episode.id}/settings`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:$('source').value,analysis_provider:analysisProvider(),...editingOptions()})});
    const current=this.data.episodes.find(e=>e.id===episode.id); if(current) Object.assign(current,saved);
    if(this.episode?.id===episode.id) { this.episode=current; updateControls(); }
    return saved.id;
  },
  async launch() {
    if(state.busyAction) return;
    const episodeId=this.episode?.id;
    state.busyAction=true; updateControls(); setText('form-message','');
    try {
      await this.save();
      const job=await api(`/api/episodes/${episodeId}/jobs`,{method:'POST'});
      await this.refreshLibrary(); await refresh();
      if(this.episode?.id===episodeId && this.view==='edit') { this.wasRunning=true; await selectJob(job.id); }
    } catch(error) { setText('form-message',error.message); }
    finally { state.busyAction=false; updateControls(); }
  }
};
const musicUI = {
  tracks: [],
  current: {enabled: true, volume: 0.15, track: null, mode: 'random_per_part', part_tracks: {}},
  partCount: 15,
  option(value, label) { const option=document.createElement('option'); option.value=value; option.textContent=label; return option; },
  populateTracks(selected) {
    const select = $('music-track');
    const options = [this.option('', '🎲 Случайный трек')];
    for (const name of this.tracks) options.push(this.option(name, `🎵 ${name}`));
    select.replaceChildren(...options);
    select.value = selected ?? '';
  },
  renderPartsList() {
    const container = $('music-parts-list');
    if (!container) return;
    const parts = this.current.part_tracks || {};
    let count = 15;
    const completed = libraryUI.attempts().find(j => j.status === 'completed');
    if (completed?.files?.length) count = completed.files.length;
    else if (state.selectedJob?.files?.length) count = state.selectedJob.files.length;
    this.partCount = count;
    setText('music-parts-count', `${count} фрагментов`);
    const elements = [];
    for (let i = 1; i <= count; i++) {
      const row = document.createElement('div');
      row.className = 'music-part-row';
      const label = document.createElement('span');
      label.className = 'music-part-label';
      label.textContent = `Часть ${String(i).padStart(2, '0')}:`;
      const select = document.createElement('select');
      select.className = 'music-part-select';
      select.dataset.part = String(i);
      const options = [
        this.option('', '🎲 Случайный трек'),
        this.option('none', '🔇 Без музыки'),
      ];
      for (const name of this.tracks) {
        options.push(this.option(name, `🎵 ${name}`));
      }
      select.replaceChildren(...options);
      select.value = parts[String(i)] ?? '';
      select.addEventListener('change', () => {
        if (!this.current.part_tracks) this.current.part_tracks = {};
        this.current.part_tracks[String(i)] = select.value || null;
        this.save();
      });
      row.append(label, select);
      elements.push(row);
    }
    container.replaceChildren(...elements);
  },
  render() {
    const enabled = $('music-enabled').checked;
    const volume = Number($('music-volume').value) || 0;
    const mode = $('music-mode').value;
    const track = $('music-track').value;
    setText('music-volume-label', `${volume}%`);

    $('music-single-panel').hidden = mode !== 'single';
    $('music-parts-panel').hidden = mode !== 'per_part';

    let currentDesc = '';
    if (!enabled) currentDesc = 'Фоновая музыка выключена';
    else if (!this.tracks.length) currentDesc = 'В папке music пока нет треков. Нажмите «Открыть папку с музыкой» и закиньте MP3/WAV.';
    else if (mode === 'random_per_part') currentDesc = `Режим: случайный трек для каждого фрагмента (${this.tracks.length} треков в папке) · громкость ${volume}%`;
    else if (mode === 'single') currentDesc = track ? `Режим: один трек на всю серию (${track}) · громкость ${volume}%` : `Режим: один случайный трек на всю серию · громкость ${volume}%`;
    else if (mode === 'per_part') {
      const countSet = Object.values(this.current.part_tracks || {}).filter(Boolean).length;
      currentDesc = `Режим: ручной выбор по фрагментам (настроено ${countSet} частей) · громкость ${volume}%`;
    }

    setText('music-current', currentDesc);
    setText('music-summary', enabled ? (mode === 'random_per_part' ? 'случайный для каждого' : mode === 'per_part' ? 'по фрагментам' : (track || 'один трек')) : 'выключена');

    $('music-volume').disabled = !enabled;
    $('music-mode').disabled = !enabled;
    $('music-track').disabled = !enabled;
    $('music-random').disabled = !enabled;
    if (mode === 'per_part') this.renderPartsList();
  },
  async load() {
    try {
      const data = await api('/api/music');
      this.current = data;
      this.tracks = data.tracks ?? [];
      $('music-enabled').checked = !!data.enabled;
      $('music-volume').value = String(Math.round((data.volume ?? 0.15) * 100));
      $('music-mode').value = data.mode ?? 'random_per_part';
      this.populateTracks(data.track);
      this.render();
    } catch(error) { setText('music-message', error.message); }
  },
  async save() {
    try {
      const body = {
        enabled: $('music-enabled').checked,
        volume: (Number($('music-volume').value) || 0) / 100,
        track: $('music-track').value || null,
        mode: $('music-mode').value,
        part_tracks: this.current.part_tracks || {},
      };
      const saved = await api('/api/music', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      this.current = saved;
      this.tracks = saved.tracks ?? [];
      setText('music-message', 'Настройки музыки сохранены.');
      this.render();
    } catch(error) { setText('music-message', error.message); }
  },
  async refresh() {
    setText('music-message', 'Обновляем список треков из папки...');
    await this.load();
    setText('music-message', this.tracks.length ? `Найдено треков в папке: ${this.tracks.length}.` : 'Папка music пуста. Закиньте туда треки без АП.');
  },
  async random() {
    if (!this.tracks.length) { setText('music-message', 'В папке music нет аудиофайлов.'); return; }
    $('music-track').value = this.tracks[Math.floor(Math.random() * this.tracks.length)];
    this.render(); await this.save();
  },
  async openFolder() {
    try {
      const res = await api('/api/music/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
      });
      const path = res?.path || 'F:\\new_prodject\\music';
      setText('music-message', `Папка открыта в Проводнике Windows: ${path}. Если окно на заднем плане, проверьте панель задач Windows.`);
    } catch(error) {
      setText('music-message', `Папка музыки находится по адресу: F:\\new_prodject\\music (нажмите «Скопировать путь»). Ошибка автооткрытия: ${error.message}`);
    }
  },
  async copyPath() {
    const path = 'F:\\new_prodject\\music';
    try {
      await navigator.clipboard.writeText(path);
      setText('music-message', `Путь скопирован в буфер обмена: ${path}`);
    } catch {
      setText('music-message', `Путь к папке: ${path}`);
    }
  },
};
state.navigation=libraryUI;
$('delete-current-project').addEventListener('click',()=>libraryUI.archive('project',libraryUI.project.id));
$('delete-current-episode').addEventListener('click',()=>libraryUI.archive('episode',libraryUI.episode.id));
addEventListener('hashchange',()=>libraryUI.route().catch(error=>setText('library-message',error.message)));
$('project-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=$('project-form').querySelector('button'); button.disabled=true;
  try { const project=await api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:$('project-title').value})}); await libraryUI.refreshLibrary(); $('project-title').value=''; location.hash=`project/${project.id}`; }
  catch(error) { setText('library-message',error.message); }
  finally { button.disabled=false; }
});
$('episode-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=$('episode-form').querySelector('button'); button.disabled=true;
  try { const episode=await api(`/api/projects/${libraryUI.project.id}/episodes`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({number:Number($('episode-number').value)})}); await libraryUI.refreshLibrary(); location.hash=`episode/${episode.id}/edit`; }
  catch(error) { setText('library-message',error.message); }
  finally { button.disabled=false; }
});
$('save-settings').addEventListener('click',async()=>{
  if(state.busyAction) return; $('save-settings').disabled=true;
  try { await libraryUI.save(); setText('form-message','Настройки этой серии сохранены. Монтаж не запускался.'); }
  catch(error) { setText('form-message',error.message); }
  finally { $('save-settings').disabled=false; }
});
$('episode-attempt').addEventListener('change',()=>{
  if(libraryUI.attempts().some(j=>j.id===$('episode-attempt').value && j.status==='completed')) location.hash=`episode/${libraryUI.episode.id}/review/${$('episode-attempt').value}`;
});
$('music-enabled').addEventListener('change', () => { musicUI.render(); musicUI.save(); });
$('music-volume').addEventListener('input', () => setText('music-volume-label', `${$('music-volume').value}%`));
$('music-volume').addEventListener('change', () => musicUI.save());
$('music-mode').addEventListener('change', () => { musicUI.render(); musicUI.save(); });
$('music-track').addEventListener('change', () => { musicUI.render(); musicUI.save(); });
$('music-random').addEventListener('click', () => musicUI.random());
$('music-open-folder').addEventListener('click', () => musicUI.openFolder());
$('music-copy-path')?.addEventListener('click', () => musicUI.copyPath());
$('music-refresh').addEventListener('click', () => musicUI.refresh());
libraryUI.refreshLibrary().then(()=>libraryUI.route()).catch(error=>setText('library-message',`Не удалось открыть проекты: ${error.message}`));

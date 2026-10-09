import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type {
  FinishAudio, FinishCue, FinishFile, FinishProfile, FinishRenderTask,
  FinishSubtitles, FinishVideo, Job, Plan
} from '../api/types';
import { useLibrary } from '../hooks/useLibrary';
import { activeEpisodes, completedJobsForEpisode, episodeById, projectById } from '../library/selectors';
import './FinishingPage.css';

type Tab = 'subtitles' | 'audio' | 'frame';

function clock(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return String(minutes).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
}
function errorMessage(e: unknown) { return e instanceof Error ? e.message : 'Ошибка запроса'; }

export function StudioHomePage() {
  const { data, error, isLoading } = useLibrary();
  if (isLoading && !data) return <main className="st-room"><p>Загружаем библиотеку…</p></main>;
  if (error) return <main className="st-room"><p role="alert">{error.message}</p></main>;
  const ready = activeEpisodes(data).filter(ep => completedJobsForEpisode(ep).length > 0);
  return <main className="st-room st-home">
    <p className="st-overline">КАДР / STUDIO EDITION</p>
    <h1>Финальный штрих.</h1>
    <p className="st-muted">Выберите готовую серию, чтобы настроить кадр, субтитры и музыку без повторного анализа.</p>
    <div className="st-projects">
      {ready.map(ep => {
        const jobId = completedJobsForEpisode(ep)[0].id;
        const project = projectById(data, ep.project_id);
        return <Link className="st-project-link" key={ep.id} to={'/episode/' + ep.id + '/finishing/' + jobId}>
          <span className="st-project-monogram">К</span>
          <span><strong>{project?.title || 'Проект'} · Серия {ep.number}</strong>
          <small>Открыть редактор оформления →</small></span>
        </Link>;
      })}
    </div>
    {ready.length === 0 && <p className="st-empty">Пока нет готовых Shorts. <Link to="/projects">Открыть проекты</Link></p>}
  </main>;
}

export function FinishingPage() {
  const { episodeId, jobId: pathJobId } = useParams<{episodeId: string; jobId?: string}>();
  const { data, error: libraryError } = useLibrary();
  const episode = episodeById(data, episodeId);
  const project = projectById(data, episode?.project_id);
  const jobId = pathJobId || completedJobsForEpisode(episode)[0]?.id;

  const [job, setJob] = useState<Job | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [profile, setProfile] = useState<FinishProfile | null>(null);
  const [tracks, setTracks] = useState<string[]>([]);
  const [index, setIndex] = useState(0);
  const [cueIndex, setCueIndex] = useState(0);
  const [tab, setTab] = useState<Tab>('subtitles');
  const [playTime, setPlayTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [problem, setProblem] = useState('');
  const [dirtyCues, setDirtyCues] = useState<Record<string, boolean>>({});
  const [cueRevision, setCueRevision] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<FinishRenderTask | null>(null);
  const [exportTask, setExportTask] = useState<FinishRenderTask | null>(null);
  const [useRendered, setUseRendered] = useState(false);
  const [guides, setGuides] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const dragging = useRef(false);

  useEffect(() => {
    if (!jobId || !episodeId) { setLoading(false); return; }
    let live = true;
    setLoading(true);
    setProblem('');
    Promise.all([api.getJob(jobId), api.getJobPlan(jobId), api.getFinishing(episodeId), api.getMusicSettings()])
      .then(async ([j, p, saved, music]) => {
        // The episode profile stores style only. The current job's caption
        // endpoint is authoritative, even if a legacy profile contains cues
        // copied from a *different* montage of the same episode.
        const captionResults = await Promise.all(p.parts.map(part =>
          api.getFinishCaptions(jobId, part.index)));
        if (!live) return;
        const overrides = { ...saved.part_overrides };
        const revisions: Record<string, number> = {};
        captionResults.forEach((result, idx) => {
          const partKey = String(p.parts[idx].index);
          overrides[partKey] = { ...overrides[partKey], cues: result.cues };
          revisions[partKey] = result.revision;
        });
        setJob(j); setPlan(p); setProfile({ ...saved, part_overrides: overrides });
        setTracks(music.tracks || []); setCueRevision(revisions);
      })
      .catch(err => { if (live) setProblem(errorMessage(err)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [episodeId, jobId]);

  useEffect(() => {
    const id = preview?.preview_id;
    if (!jobId || !id || !['queued', 'running'].includes(preview.status)) return;
    const timer = window.setInterval(() => {
      api.getFinishPreview(jobId, id).then(setPreview).catch(err => setProblem(errorMessage(err)));
    }, 1100);
    return () => window.clearInterval(timer);
  }, [jobId, preview?.preview_id, preview?.status]);

  useEffect(() => {
    const id = exportTask?.export_id;
    if (!id || !['queued', 'running'].includes(exportTask.status)) return;
    const timer = window.setInterval(() => {
      api.getFinishExport(id).then(setExportTask).catch(err => setProblem(errorMessage(err)));
    }, 1300);
    return () => window.clearInterval(timer);
  }, [exportTask?.export_id, exportTask?.status]);

  const currentPart = plan?.parts[index];
  const partKey = String(currentPart?.index ?? 1);
  const currentStyle = profile?.part_overrides[partKey]?.style || profile?.subtitles;
  const cues = profile?.part_overrides[partKey]?.cues ?? currentPart?.subtitles ?? [];
  const activeCue = cues[Math.min(cueIndex, Math.max(0, cues.length - 1))];
  const showingCue = !isPlaying ? (activeCue ?? cues.find(c => c.start <= playTime && playTime < c.end)) : cues.find(c => c.start <= playTime && playTime < c.end);

  const patchVideo = (update: Partial<FinishVideo>) =>
    setProfile(old => old ? { ...old, video: { ...old.video, ...update } } : old);
  const patchAudio = (update: Partial<FinishAudio>) =>
    setProfile(old => old ? { ...old, audio: { ...old.audio, ...update } } : old);
  const patchStyle = (update: Partial<FinishSubtitles>) =>
    setProfile(old => {
      if (!old) return old;
      const overrides = { ...old.part_overrides };
      const current = overrides[partKey] ?? {};
      const style = { ...(current.style ?? old.subtitles), ...update };
      overrides[partKey] = { ...current, style };
      return { ...old, part_overrides: overrides };
    });
  const updateCues = (next: FinishCue[]) => {
    setProfile(old => {
      if (!old) return old;
      return { ...old, part_overrides: {
        ...old.part_overrides, [partKey]: { ...old.part_overrides[partKey], cues: next }
      }};
    });
    setDirtyCues(old => ({ ...old, [partKey]: true }));
  };
  const patchCue = (update: Partial<FinishCue>) => {
    updateCues(cues.map((cue, i) => i === cueIndex ? { ...cue, ...update } : cue));
  };
  const selectPart = (next: number) => {
    setIndex(next); setCueIndex(0); setPlayTime(0); setIsPlaying(false);
    setUseRendered(false); setPreview(null);
    const video = videoRef.current;
    if (video) video.currentTime = 0;
  };

  const saveDraftCaptions = async () => {
    if (!profile || !jobId) return;
    for (const key of Object.keys(dirtyCues)) {
      if (!dirtyCues[key]) continue;
      const items = profile.part_overrides[key]?.cues ?? [];
      const updated = await api.saveFinishCaptions(jobId, Number(key), items, cueRevision[key] ?? 0);
      setCueRevision(old => ({ ...old, [key]: updated.revision }));
      // Keep the other dirty parts editable if a subsequent part fails.
      setDirtyCues(old => { const next = { ...old }; delete next[key]; return next; });
    }
  };
  const save = async () => {
    if (!profile || !episodeId || !jobId || saving) return;
    setSaving(true); setProblem(''); setMessage('');
    try {
      const changes = Object.keys(dirtyCues).filter(key => dirtyCues[key]).map(key => ({
        part_index: Number(key), revision: cueRevision[key] ?? 0,
        cues: profile.part_overrides[key]?.cues ?? []
      }));
      const result = await api.saveFinishingState(jobId, profile, changes);
      const stored = result.profile;
      setCueRevision(old => ({
        ...old, ...Object.fromEntries(result.captions.map(entry => [
          String(entry.part_index), entry.revision]))
      }));
      setDirtyCues({});
      // The API intentionally stores styles at episode scope and captions at
      // job scope. Keep the current job's captions in view after the profile
      // response (which has no cues) so Save cannot blank the editor.
      setProfile({
        ...stored,
        part_overrides: Object.fromEntries(Object.entries(stored.part_overrides).map(
          ([key, value]) => [key, { ...value, cues: profile.part_overrides[key]?.cues }]))
      });
      setMessage('Настройки и реплики сохранены на сервере');
    } catch (err) { setProblem(errorMessage(err)); }
    finally { setSaving(false); }
  };

  const createPreview = async () => {
    if (!jobId || !profile || !currentPart) return;
    setProblem(''); setMessage('Создаём предпросмотр на сервере…');
    setUseRendered(false);
    try {
      await saveDraftCaptions();
      setPreview(await api.createFinishPreview(jobId, currentPart.index, profile, 0,
        Math.min(5, currentPart.duration || 5)));
    }
    catch (err) { setProblem(errorMessage(err)); }
  };
  const exportParts = async (all: boolean) => {
    if (!jobId || !profile || !plan) return;
    setProblem(''); setMessage('Создана отдельная задача повторного экспорта');
    try {
      await saveDraftCaptions();
      setExportTask(await api.createFinishExport(jobId,
        all ? plan.parts.map(p => p.index) : [currentPart!.index], profile));
    } catch (err) { setProblem(errorMessage(err)); }
  };
  const copyStyle = () => {
    setProfile(old => {
      if (!old || !plan || !currentStyle) return old;
      const next = { ...old.part_overrides };
      plan.parts.forEach(p => { next[String(p.index)] = {
        ...next[String(p.index)], style: { ...currentStyle }
      }; });
      return { ...old, part_overrides: next };
    });
    setMessage('Стиль скопирован во все части. Реплики не менялись.');
  };
  const importMusic = async (file: File | undefined) => {
    if (!file) return;
    setProblem('');
    try {
      const created = await api.importMusic(file);
      const settings = await api.getMusicSettings();
      setTracks(settings.tracks || []);
      patchAudio({ enabled: true, track: created.name, mode: 'single' });
      setMessage('Музыка загружена: ' + created.name);
    } catch (err) { setProblem(errorMessage(err)); }
  };
  const downloadProfile = () => {
    if (!profile) return;
    const blob = new Blob([JSON.stringify(profile, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const element = document.createElement('a');
    element.href = url; element.download = 'kadr-finishing.json'; element.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  if (loading) return <main className="st-room"><p role="status">Загружаем монтаж и настройки оформления…</p></main>;
  if (libraryError || problem && !profile) return <main className="st-room"><p role="alert">{problem || libraryError?.message}</p></main>;
  if (!job || !plan || !profile || !jobId || !episode || !project || episode.archived_at || project.archived_at || job.status !== 'completed')
    return <main className="st-room"><p className="st-empty">Готовый монтаж недоступен. <Link to="/studio">Вернуться в студию</Link></p></main>;

  const currentFile = job.files?.[index];
  const previewUrl = useRendered && preview?.status === 'completed' ? preview.url : null;
  const sourceUrl = previewUrl || currentFile?.url;
  const frame = profile.video;
  const audio = profile.audio;
  const viewStyle = currentStyle!;
  const previewBusy = preview?.status === 'running' || preview?.status === 'queued';
  const exportBusy = exportTask?.status === 'running' || exportTask?.status === 'queued';

  return <main className="st-room">
    <nav className="st-breadcrumbs" aria-label="Путь">
      <Link to="/projects">Проекты</Link><span> / </span>
      <Link to={'/project/' + project.id}>{project.title}</Link><span> / </span>
      <strong>Серия {episode.number} · Оформление</strong>
    </nav>

    <header className="st-heading">
      <div>
        <div className="st-overline">КАДР / FINISHING ROOM · СЕРИЯ {episode.number}</div>
        <h1>Финальный штрих.</h1>
        <p>Кадр, титры, музыка. Результат виден сразу.</p>
      </div>
      <div className="st-heading-actions">
        <Link to={'/episode/' + episode.id + '/review/' + jobId} className="st-button st-ghost">← К проверке</Link>
        <button type="button" className="st-button st-bright" onClick={save} disabled={saving}>
          {saving ? 'Сохраняем…' : 'Сохранить правки ↗'}
        </button>
      </div>
    </header>

    {problem && <div className="st-message st-error" role="alert">{problem}</div>}
    {message && <div className="st-message" role="status">{message}</div>}

    <div className="st-editor">
      <section className="st-tools" aria-label="Настройки оформления">
        <div className="st-panel-kicker">ИНСТРУМЕНТЫ <span>01 / 03</span></div>
        <div className="st-tabs" role="tablist" aria-label="Инструменты">
          <button role="tab" aria-selected={tab === 'subtitles'} className={tab === 'subtitles' ? 'active' : ''}
            onClick={() => setTab('subtitles')}>Субтитры</button>
          <button role="tab" aria-selected={tab === 'audio'} className={tab === 'audio' ? 'active' : ''}
            onClick={() => setTab('audio')}>Звук</button>
          <button role="tab" aria-selected={tab === 'frame'} className={tab === 'frame' ? 'active' : ''}
            onClick={() => setTab('frame')}>Кадр</button>
        </div>

        {tab === 'subtitles' && <div className="st-settings" role="tabpanel">
          <h2>Слова в кадре</h2><p>Настраивай титры прямо на видео.</p>
          <label className="st-check"><input type="checkbox" checked={viewStyle.enabled}
            onChange={e => patchStyle({enabled: e.target.checked})}/> Показывать субтитры</label>
          <div className="st-cue-list">
            {cues.map((cue, i) => <button type="button" key={i}
              className={'st-cue' + (cueIndex === i ? ' selected' : '')} onClick={() => {
                setCueIndex(i); videoRef.current!.currentTime = Math.max(0, cue.start); setPlayTime(cue.start);
              }}><small>{clock(cue.start)}—{clock(cue.end)}</small><strong>{cue.text}</strong></button>)}
          </div>
          <div className="st-row">
            <button className="st-button st-lightline" type="button" onClick={() => {
              const start = cues.length ? cues[cues.length - 1].end : 0;
              const end = Math.min(currentPart?.duration || 5, start + 2);
              if (start < end) { updateCues([...cues, { start, end, text: 'НОВАЯ РЕПЛИКА' }]); setCueIndex(cues.length); }
            }}>+ Реплика</button>
            <button className="st-button st-ghost" type="button" disabled={!activeCue}
              onClick={() => { updateCues(cues.filter((_, i) => i !== cueIndex)); setCueIndex(0); }}>Удалить</button>
          </div>
          {activeCue && <>
            <div className="st-row">
              <label>Начало, с <input aria-label="Начало реплики" type="number" step=".1" min="0" value={activeCue.start}
                onChange={e => patchCue({start: Number(e.target.value)})}/></label>
              <label>Конец, с <input aria-label="Конец реплики" type="number" step=".1" min="0" value={activeCue.end}
                onChange={e => patchCue({end: Number(e.target.value)})}/></label>
            </div>
            <label className="st-field">Текст реплики<textarea aria-label="Текст реплики" rows={3} value={activeCue.text}
              onChange={e => patchCue({text: e.target.value})}/></label>
          </>}
          <div className="st-presets">
            {[
              {label:'Яркие', color:'#f6d779', outline:4, font_size:32},
              {label:'Классика', color:'#ffffff', outline:3, font_size:30},
              {label:'Минимализм', color:'#e7e7e0', outline:1, font_size:26},
            ].map(preset => <button key={preset.label} className="st-button st-lightline"
              onClick={() => patchStyle(preset)}>{preset.label}</button>)}
          </div>
          <div className="st-swatches">
            {['#f6d779','#ffffff','#a9e4c6','#ffb0ab','#d0b8fa'].map(color=>
              <button type="button" aria-label={'Цвет ' + color} key={color} onClick={() => patchStyle({color})}
                className={viewStyle.color === color ? 'active' : ''} style={{background:color}}/>)}
            <input aria-label="Свободный цвет" type="color" value={viewStyle.color} onChange={e=>patchStyle({color:e.target.value})}/>
          </div>
          <label className="st-slider">Размер текста <strong>{viewStyle.font_size} px</strong>
            <input type="range" min="18" max="54" value={viewStyle.font_size}
              onChange={e=>patchStyle({font_size:Number(e.target.value)})}/></label>
          <label className="st-slider">Контур <strong>{viewStyle.outline}</strong>
            <input type="range" min="0" max="6" value={viewStyle.outline}
              onChange={e=>patchStyle({outline:Number(e.target.value)})}/></label>
          <div className="st-row">
            <label>X, % <input aria-label="Позиция X" type="number" min="0" max="100" value={viewStyle.x}
              onChange={e=>patchStyle({x:Number(e.target.value)})}/></label>
            <label>Y, % <input aria-label="Позиция Y" type="number" min="0" max="100" value={viewStyle.y}
              onChange={e=>patchStyle({y:Number(e.target.value)})}/></label>
          </div>
          <label className="st-check"><input type="checkbox" checked={viewStyle.uppercase}
            onChange={e=>patchStyle({uppercase:e.target.checked})}/> Заглавные буквы</label>
          <label className="st-check"><input type="checkbox" checked={viewStyle.background}
            onChange={e=>patchStyle({background:e.target.checked})}/> Подложка</label>
          <button type="button" className="st-button st-ghost st-full" onClick={copyStyle}>Применить стиль ко всем частям ↗</button>
        </div>}

        {tab === 'audio' && <div className="st-settings" role="tabpanel">
          <h2>Звуковая дорожка</h2><p>Оригинальные голоса сохраняются при микшировании.</p>
          <label className="st-check"><input type="checkbox" checked={audio.enabled}
            onChange={e=>patchAudio({enabled:e.target.checked})}/> Добавлять фоновую музыку</label>
          <label className="st-field">Режим
            <select value={audio.mode} onChange={e=>patchAudio({mode:e.target.value as FinishAudio['mode']})}>
              <option value="single">Один трек</option><option value="random_per_part">Случайный на часть</option>
              <option value="per_part">Для каждой части отдельно</option>
            </select></label>
          {audio.mode === 'single' && <label className="st-field">Музыка
            <select aria-label="Музыкальный трек" value={audio.track || ''}
              onChange={e=>patchAudio({track:e.target.value || null})}>
              <option value="">Случайный трек</option>
              {tracks.map(name=><option key={name} value={name}>{name}</option>)}
            </select></label>}
          {audio.mode === 'per_part' && (plan?.parts || []).map(part=>
            <label className="st-field" key={part.index}>Часть {part.index}
              <select value={audio.part_tracks?.[String(part.index)] || ''}
                onChange={e=>patchAudio({part_tracks:{...audio.part_tracks,[String(part.index)]:e.target.value || null}})}>
                <option value="">Случайно</option><option value="none">Без музыки</option>
                {tracks.map(name=><option key={name}>{name}</option>)}
              </select>
            </label>)}
          <label className="st-slider">Громкость <strong>{Math.round(audio.volume*100)}%</strong>
            <input aria-label="Громкость музыки" type="range" min="0" max="100" value={Math.round(audio.volume*100)}
              onChange={e=>patchAudio({volume:Number(e.target.value)/100})}/></label>
          <label className="st-slider">Появление <strong>{audio.fade_in} с</strong>
            <input type="range" min="0" max="5" step=".1" value={audio.fade_in}
              onChange={e=>patchAudio({fade_in:Number(e.target.value)})}/></label>
          <label className="st-slider">Затухание <strong>{audio.fade_out} с</strong>
            <input type="range" min="0" max="5" step=".1" value={audio.fade_out}
              onChange={e=>patchAudio({fade_out:Number(e.target.value)})}/></label>
          <label className="st-check"><input type="checkbox" checked={audio.ducking}
            onChange={e=>patchAudio({ducking:e.target.checked})}/> Приглушать музыку под репликами</label>
          {audio.track && <audio controls preload="none" className="st-audio"
            src={'/api/music/tracks/' + encodeURIComponent(audio.track) + '/stream'}/>}
          <label className="st-upload">＋ Добавить собственный MP3 / WAV
            <input aria-label="Загрузить музыку" type="file" accept="audio/*,.mp3,.wav,.m4a,.ogg" onChange={e=>{
              void importMusic(e.target.files?.[0]); e.currentTarget.value='';
            }}/></label>
          <button className="st-button st-lightline st-full" onClick={()=>api.openMusicFolder().then(()=>setMessage('Папка открыта')).catch(err=>setProblem(errorMessage(err)))}>
            Открыть папку музыки ↗</button>
        </div>}

        {tab === 'frame' && <div className="st-settings" role="tabpanel">
          <h2>Кадрирование</h2><p>Визуальное оформление для 9:16 Shorts.</p>
          <div className="st-presets">
            <button className={'st-button '+(frame.layout==='cinema'?'st-bright':'st-lightline')}
              onClick={()=>patchVideo({layout:'cinema'})}>Полный кадр</button>
            <button className={'st-button '+(frame.layout==='portrait'?'st-bright':'st-lightline')}
              onClick={()=>patchVideo({layout:'portrait'})}>Крупный план</button>
          </div>
          {([
            ['zoom','Масштаб',90,160,'%'],['brightness','Яркость',60,140,'%'],
            ['blur','Размытие фона',0,45,''],['vignette','Виньетка',0,60,'']
          ] as const).map(([key,label,min,max,unit])=>
            <label className="st-slider" key={key}>{label}<strong>{frame[key]}{unit}</strong>
              <input aria-label={label} type="range" min={min} max={max} value={frame[key]}
                onChange={e=>patchVideo({[key]:Number(e.target.value)})}/></label>)}
          <label className="st-check"><input type="checkbox" checked={guides} onChange={e=>setGuides(e.target.checked)}/>
            Сетка безопасной зоны</label>
          <button className="st-button st-ghost st-full" onClick={()=>patchVideo({
            zoom:100,brightness:100,blur:24,vignette:15})}>Сбросить настройки кадра</button>
        </div>}
      </section>

      <section className="st-preview-col" aria-label="Предпросмотр">
        <div className="st-preview-head"><span className="st-live">● LIVE PREVIEW</span>
          <div className="st-row">
            <button type="button" className={'st-button st-ghost '+(guides?'st-selected':'')} onClick={()=>setGuides(x=>!x)}># Сетка</button>
            <button type="button" className="st-button st-ghost" onClick={()=>{setUseRendered(false);setPlayTime(0);if(videoRef.current)videoRef.current.currentTime=0;}}>↶</button>
          </div>
        </div>
        <div className="st-preview-stage">
          <div className="st-video-frame">
            {sourceUrl ? <video key={sourceUrl} aria-label="Видео предпросмотра" ref={videoRef}
              src={sourceUrl} playsInline preload="metadata"
              onTimeUpdate={e=>setPlayTime(e.currentTarget.currentTime)}
              onPlay={()=>setIsPlaying(true)} onPause={()=>setIsPlaying(false)} onEnded={()=>setIsPlaying(false)}
              style={{filter:'brightness(' + frame.brightness + '%)',transform:'scale('+(frame.zoom/100)+')'}}/>:
              <div className="st-no-video">Видео ещё не готово</div>}
            {guides && <div className="st-safe-guides" aria-hidden="true"/>}
            {!useRendered && viewStyle.enabled && showingCue &&
              <div className="st-caption-layer" role="button" tabIndex={0}
                aria-label="Перетащить субтитры" title="Перетащите субтитры мышью или стрелками"
                style={{left:viewStyle.x+'%',top:viewStyle.y+'%',fontSize:Math.max(10,viewStyle.font_size/2)+'px',
                  color:viewStyle.color, textAlign:viewStyle.align,
                  background:viewStyle.background?'rgba(0,0,0,.55)':'transparent',
                  WebkitTextStroke:viewStyle.outline/3+'px #101010'}}
                onPointerDown={e=>{dragging.current=true;e.currentTarget.setPointerCapture(e.pointerId);}}
                onPointerMove={e=>{if(!dragging.current)return;const rect=e.currentTarget.parentElement!.getBoundingClientRect();
                  patchStyle({x:Math.round(Math.max(0,Math.min(100,100*(e.clientX-rect.left)/rect.width))),
                    y:Math.round(Math.max(0,Math.min(100,100*(e.clientY-rect.top)/rect.height)))});}}
                onPointerUp={()=>{dragging.current=false;}}
                onKeyDown={e=>{let dx=0,dy=0;if(e.key==='ArrowLeft')dx=-1;if(e.key==='ArrowRight')dx=1;
                  if(e.key==='ArrowUp')dy=-1;if(e.key==='ArrowDown')dy=1;
                  if(dx||dy){e.preventDefault();patchStyle({x:Math.max(0,Math.min(100,viewStyle.x+dx)),
                    y:Math.max(0,Math.min(100,viewStyle.y+dy))});}}}>
                {viewStyle.uppercase ? showingCue.text.toUpperCase():showingCue.text}
              </div>}
            <div className="st-watermark">КАДР STUDIO / {String(index+1).padStart(2,'0')}</div>
          </div>
        </div>
        <div className="st-preview-control">
          <button className="st-play" aria-label="Воспроизвести или пауза" onClick={()=>{
            if(videoRef.current?.paused) void videoRef.current.play();
            else videoRef.current?.pause();
          }}>▶</button>
          <span>{clock(playTime)}</span>
          <input aria-label="Позиция видео" type="range" min="0" max={currentPart?.duration||1} step=".05"
            value={Math.min(playTime,currentPart?.duration||1)} onChange={e=>{const t=Number(e.target.value);
              setPlayTime(t);if(videoRef.current)videoRef.current.currentTime=t;}}/>
          <span>{clock(currentPart?.duration||0)}</span>
          <button className="st-button st-ghost" onClick={()=>setTab('audio')}>♫</button>
        </div>
        <div className="st-preview-bottom">
          <span>1080 × 1920 · 9:16 Shorts</span>
          <span>{preview?.status==='completed' ? '✓ Серверное видео готово' : '● Браузерное наложение'}</span>
        </div>
        {preview && <div className="st-render-status" role="status">
          Предпросмотр: {preview.status} · {Math.round(preview.progress*100)}%
          {preview.status==='completed' && <button className="st-button st-lightline" onClick={()=>setUseRendered(!useRendered)}>
            {useRendered?'Браузерный вид':'Смотреть серверный MP4'}</button>}
          {preview.status==='failed' && <span>{preview.error}</span>}
        </div>}
      </section>

      <aside className="st-rail" aria-label="Готовые части">
        <div className="st-panel-kicker">МОНТАЖНЫЙ НАБОР</div>
        <strong>{plan.parts.length} Shorts</strong>
        <div className="st-part-list">
          {plan.parts.map((part, i) => <button type="button" key={part.index}
            className={'st-part'+(index===i?' current':'')} onClick={()=>selectPart(i)}>
            <span>{String(part.index).padStart(2,'0')}</span>
            <span><strong>Часть {String(part.index).padStart(2,'0')}</strong>
              <small>{clock(part.duration||0)} · {part.cuts.length} сцен</small></span>
            <span>→</span>
          </button>)}
        </div>
        <div className="st-rail-footer">
          <div className="st-panel-kicker">БЫСТРЫЕ ДЕЙСТВИЯ</div>
          <button className="st-action" onClick={copyStyle}>▣ <span>Применить стиль ко всем частям</span> →</button>
          <button className="st-action" onClick={downloadProfile}>↓ <span>Скачать настройки JSON</span> →</button>
          <button className="st-action" onClick={createPreview} disabled={previewBusy}>▣ <span>
            {previewBusy?'Готовим предпросмотр…':'Запрос предпросмотра'}</span> →</button>
          <hr/>
          <div className="st-panel-kicker">ПОВТОРНЫЙ ЭКСПОРТ</div>
          <p>Готовые MP4 сохраняются как новая версия. Предыдущие Shorts не изменяются.</p>
          <button className="st-button st-bright st-full" disabled={exportBusy} onClick={()=>void exportParts(false)}>
            Экспортировать часть {index+1} ↗</button>
          <button className="st-button st-lightline st-full" disabled={exportBusy} onClick={()=>void exportParts(true)}>
            Экспортировать все части</button>
          {exportTask && <div className="st-export-progress" role="status">
            <strong>Экспорт: {exportTask.status}</strong>
            <progress value={exportTask.progress} max="1"/>
            {exportTask.error && <span>{exportTask.error}</span>}
            {exportTask.files?.map((file: FinishFile)=> <div className="st-download" key={file.url}>
              <a href={file.url+'?download=1'}>↓ {file.name}</a>
              {file.subtitle_url && <a href={file.subtitle_url+'?download=1'}>SRT</a>}
            </div>)}
          </div>}
          <p className="st-footnote">Локальный сервер · Отдельные версии экспорта</p>
        </div>
      </aside>
    </div>
    <footer className="st-editor-foot">
      <span>Часть {index+1} из {plan.parts.length} · {cues.length} реплик</span>
      <span>Источник: {job.source_name} · Работа в локальной сети не требуется</span>
    </footer>
  </main>;
}

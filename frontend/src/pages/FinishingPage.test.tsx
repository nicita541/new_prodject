import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { FinishingPage, StudioHomePage } from './FinishingPage';
import { api } from '../api/client';
import { useLibrary } from '../hooks/useLibrary';
import { libraryCopy, e1, completedJob } from '../test/fixtures/library';
import type { FinishProfile, Job, Plan } from '../api/types';

vi.mock('../api/client');
vi.mock('../hooks/useLibrary');

const profile: FinishProfile = {
  version: 1,
  video: { layout: 'portrait', zoom: 100, brightness: 100, blur: 24, vignette: 15 },
  subtitles: { enabled: true, text: '', x: 50, y: 74, font_size: 32, color: '#f6d779',
    outline: 3, background: false, align: 'center', uppercase: true, safe_guides: true },
  audio: { enabled: true, volume: 0.15, track: null, mode: 'random_per_part',
    fade_in: .8, fade_out: 1.3, ducking: false, part_tracks: {} },
  part_overrides: {},
  episode_id: e1.id, revision: 0,
};

const plan: Plan = { source: { duration: 120 },
  parts: [
    { index: 1, duration: 6, cuts: [{start:0,end:6}], subtitles: [
      { start: 0, end: 4.4, text: 'ПРОВЕРКА СУБТИТРОВ' }]},
    { index: 2, duration: 6, cuts: [{start:10,end:16}], subtitles: [
      { start: 0, end: 3, text: 'ВТОРАЯ ЧАСТЬ' }]}
  ]
};
const job: Job = {
  id: completedJob.id, source_id:'src', source_name:'Серия тестовая.mp4',
  analysis_provider:'local', layout:'portrait', caption_style:'classic',
  status:'completed', stage:'completed', progress:1,
  created_at:'2026-10-09T00:00:00Z', files: [
    { name:'part_001.mp4',url:'/api/jobs/1/files/part_001.mp4',subtitle_url:null,duration:6},
    { name:'part_002.mp4',url:'/api/jobs/1/files/part_002.mp4',subtitle_url:null,duration:6}
  ]
};

const page = () => render(<MemoryRouter initialEntries={['/episode/' + e1.id + '/finishing/' + completedJob.id]}>
  <Routes><Route path="/episode/:episodeId/finishing/:jobId" element={<FinishingPage/>}/></Routes>
</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useLibrary).mockReturnValue({data: libraryCopy(),isLoading:false,error:null,refetch:vi.fn()});
  vi.mocked(api.getJob).mockResolvedValue(job);
  vi.mocked(api.getJobPlan).mockResolvedValue(plan);
  vi.mocked(api.getFinishing).mockResolvedValue(structuredClone(profile));
  vi.mocked(api.getMusicSettings).mockResolvedValue({enabled:true,volume:.15,track:null,mode:'single',
    tracks:['song.mp3']});
  vi.mocked(api.getFinishCaptions).mockImplementation(async (_,index)=>({
    job_id:job.id,part_index:index,revision:0,
    cues:index===1?[{start:0,end:4.4,text:'ПРОВЕРКА СУБТИТРОВ'}]:
      [{start:0,end:3,text:'ВТОРАЯ ЧАСТЬ'}]
  }));
  vi.mocked(api.saveFinishing).mockImplementation(async(_,p)=>({
    ...p, revision:1,
    part_overrides: Object.fromEntries(Object.entries(p.part_overrides).map(
      ([key, value]) => [key, { ...value, cues: undefined }]))
  }));
  vi.mocked(api.saveFinishingState).mockImplementation(async (_, p, captions) => ({
    profile: { ...p, revision:1,
      part_overrides: Object.fromEntries(Object.entries(p.part_overrides).map(
        ([key,value]) => [key,{...value,cues:undefined}])) },
    captions: captions.map(entry=>({
      job_id:job.id,part_index:entry.part_index,cues:entry.cues,revision:entry.revision+1
    }))
  }));
  vi.mocked(api.saveFinishCaptions).mockImplementation(async(_,i,cues)=>({
    job_id:job.id,part_index:i,cues,revision:1
  }));
  window.HTMLMediaElement.prototype.load=vi.fn();
  window.HTMLMediaElement.prototype.pause=vi.fn();
  window.HTMLMediaElement.prototype.play=vi.fn().mockResolvedValue(undefined);
});

describe('Studio Edition actual backend contract', () => {
  it('opens a finished episode and renders three live editor panels', async () => {
    page();
    expect(await screen.findByText('Финальный штрих.')).toBeInTheDocument();
    expect(screen.getByRole('tab',{name:'Субтитры'})).toHaveAttribute('aria-selected','true');
    expect(screen.getByRole('tab',{name:'Звук'})).toBeInTheDocument();
    expect(screen.getByRole('tab',{name:'Кадр'})).toBeInTheDocument();
    expect(screen.getByText('2 Shorts')).toBeInTheDocument();
    expect(document.querySelector('video')).toBeInTheDocument();
    expect(api.getFinishing).toHaveBeenCalledWith(e1.id);
    expect(api.getFinishCaptions).toHaveBeenCalledTimes(2);
  });

  it('persists updated captions and styles through a single validated request', async () => {
    const user = userEvent.setup();
    page();
    const textarea = await screen.findByLabelText('Текст реплики');
    await user.clear(textarea);
    await user.type(textarea,'НОВАЯ РЕПЛИКА');
    await user.click(screen.getByRole('button',{name:/Сохранить правки/}));
    await waitFor(()=>expect(api.saveFinishingState).toHaveBeenCalledWith(
      job.id,expect.objectContaining({part_overrides:expect.any(Object)}),
      [{part_index:1,revision:0,cues:[{start:0,end:4.4,text:'НОВАЯ РЕПЛИКА'}]}]));
    expect(api.saveFinishCaptions).not.toHaveBeenCalled();
    expect(api.saveFinishing).not.toHaveBeenCalled();
    expect(await screen.findByText(/реплики сохранены на сервере/)).toBeInTheDocument();
    expect(screen.getByLabelText('Текст реплики')).toHaveValue('НОВАЯ РЕПЛИКА');
  });

  it('hides the video subtitle after its time span, even when the cue stays selected', async () => {
    page();
    await screen.findByText('Финальный штрих.');
    expect(document.querySelector('.st-caption-layer')).toHaveTextContent('ПРОВЕРКА СУБТИТРОВ');
    const video = screen.getByLabelText('Видео предпросмотра') as HTMLVideoElement;
    // While paused, show the selected caption even if the playhead is outside
    // the speech span. During playback, it must follow timecodes exactly.
    video.currentTime = 5;
    fireEvent.timeUpdate(video);
    expect(document.querySelector('.st-caption-layer')).toHaveTextContent('ПРОВЕРКА СУБТИТРОВ');
    fireEvent.play(video);
    await waitFor(() => expect(document.querySelector('.st-caption-layer')).not.toBeInTheDocument());
    fireEvent.pause(video);
    await waitFor(() => expect(document.querySelector('.st-caption-layer')).toHaveTextContent('ПРОВЕРКА СУБТИТРОВ'));
    expect(screen.getByLabelText('Текст реплики')).toHaveValue('ПРОВЕРКА СУБТИТРОВ');
  });

  it('uses the current job captions rather than legacy episode-level text', async () => {
    vi.mocked(api.getFinishing).mockResolvedValue({
      ...profile,
      part_overrides: { '1': { cues: [{ start:0,end:3,text:'ЧУЖОЙ МОНТАЖ' }] } }
    });
    page();
    await screen.findByText('Финальный штрих.');
    await waitFor(()=>expect(screen.getByLabelText('Текст реплики')).toHaveValue('ПРОВЕРКА СУБТИТРОВ'));
    expect(screen.queryByText('ЧУЖОЙ МОНТАЖ')).not.toBeInTheDocument();
  });

  it('keeps the selected cue visible while paused over a different spoken cue', async () => {
    vi.mocked(api.getFinishCaptions).mockImplementation(async (_,partIndex)=>({
      job_id:job.id, part_index:partIndex, revision:0,
      cues:partIndex===1?[
        {start:0,end:4.4,text:'ПРОВЕРКА СУБТИТРОВ'},
        {start:5,end:5.8,text:'ДРУГАЯ РЕПЛИКА'}
      ]:[{start:0,end:3,text:'ВТОРАЯ ЧАСТЬ'}]
    }));
    page();
    await screen.findByText('Финальный штрих.');
    const video = screen.getByLabelText('Видео предпросмотра') as HTMLVideoElement;
    video.currentTime = 5.2;
    fireEvent.timeUpdate(video);
    expect(document.querySelector('.st-caption-layer')).toHaveTextContent('ПРОВЕРКА СУБТИТРОВ');
    fireEvent.play(video);
    await waitFor(() => expect(document.querySelector('.st-caption-layer')).toHaveTextContent('ДРУГАЯ РЕПЛИКА'));
  });

  it('moves subtitles and copies styles to all parts without altering cues', async () => {
    const user = userEvent.setup();
    page();
    await screen.findByText('Финальный штрих.');
    fireEvent.change(screen.getByLabelText('Позиция Y'), {target:{value:'65'}});
    await user.click(screen.getAllByRole('button',{name:/Применить стиль ко всем частям/})[0]);
    await user.click(screen.getByRole('button',{name:/Сохранить правки/}));
    await waitFor(()=>expect(api.saveFinishing).toHaveBeenCalled());
    const stored = vi.mocked(api.saveFinishing).mock.lastCall?.[1];
    expect(stored?.part_overrides['1']?.style?.y).toBe(65);
    expect(stored?.part_overrides['2']?.style?.y).toBe(65);
    expect(stored?.part_overrides['2']?.cues?.[0].text).toBe('ВТОРАЯ ЧАСТЬ');
  });

  it('persists edited captions before asking FFmpeg to render a preview', async () => {
    const user = userEvent.setup();
    page();
    await screen.findByText('Финальный штрих.');
    fireEvent.change(screen.getByLabelText('Текст реплики'), {target:{value:'НОВЫЕ СУБТИТРЫ'}});
    await user.click(screen.getByRole('button',{name:/Запрос предпросмотра/}));
    await waitFor(()=>expect(api.createFinishPreview).toHaveBeenCalled());
    expect(api.saveFinishCaptions).toHaveBeenCalledWith(job.id,1,
      expect.arrayContaining([expect.objectContaining({text:'НОВЫЕ СУБТИТРЫ'})]),0);
    const saveOrder = vi.mocked(api.saveFinishCaptions).mock.invocationCallOrder[0];
    const renderOrder = vi.mocked(api.createFinishPreview).mock.invocationCallOrder[0];
    expect(saveOrder).toBeLessThan(renderOrder);
  });

  it('offers real audio import and the server-side preview request', async () => {
    const user = userEvent.setup();
    vi.mocked(api.importMusic).mockResolvedValue({name:'own.wav',stored:true,playback_url:'/api/music/tracks/own.wav/stream'});
    vi.mocked(api.getMusicSettings).mockResolvedValue({enabled:true,volume:.15,track:'own.wav',
      mode:'single',tracks:['song.mp3','own.wav']});
    vi.mocked(api.createFinishPreview).mockResolvedValue({
      preview_id:'pv_123',status:'completed',progress:1,url:'/api/jobs/a/previews/pv_123.mp4'
    });
    page();
    await screen.findByText('Финальный штрих.');
    await user.click(screen.getByRole('tab',{name:'Звук'}));
    const file = new File(['audio'], 'own.wav',{type:'audio/wav'});
    fireEvent.change(screen.getByLabelText('Загрузить музыку'),{target:{files:[file]}});
    await waitFor(()=>expect(api.importMusic).toHaveBeenCalledWith(file));
    await user.click(screen.getByRole('button',{name:/Запрос предпросмотра/}));
    await waitFor(()=>expect(api.createFinishPreview).toHaveBeenCalledWith(job.id,1,
      expect.any(Object),0,5));
  });

  it('requests a separate export of all shorts, leaving original job untouched', async () => {
    const user = userEvent.setup();
    vi.mocked(api.createFinishExport).mockResolvedValue({
      export_id:'ex_example',status:'completed',progress:1,files:[
        {part_index:1,name:'part_001.mp4',duration:6,
          url:'/api/exports/ex_example/files/part_001.mp4',subtitle_url:null}
      ]
    });
    page();
    await screen.findByText('Финальный штрих.');
    await user.click(screen.getByRole('button',{name:'Экспортировать все части'}));
    await waitFor(()=>expect(api.createFinishExport).toHaveBeenCalledWith(
      job.id,[1,2],expect.any(Object)));
    expect(await screen.findByRole('link',{name:/part_001.mp4/})).toHaveAttribute('href',
      '/api/exports/ex_example/files/part_001.mp4?download=1');
  });
});

describe('Studio landing', () => {
  it('excludes finished episodes belonging to an archived project', () => {
    const snapshot = libraryCopy();
    const archivedProject = snapshot.projects.find(project => Boolean(project.archived_at))!;
    const child = snapshot.episodes.find(ep => ep.project_id === archivedProject.id && !ep.archived_at)!;
    child.jobs = [{ ...completedJob, id: '00000000-0000-0000-0000-000000000099' }];
    vi.mocked(useLibrary).mockReturnValue({data: snapshot,isLoading:false,error:null,refetch:vi.fn()});
    render(<MemoryRouter><StudioHomePage/></MemoryRouter>);
    expect(screen.queryByText(/Archived Project/)).not.toBeInTheDocument();
    expect(document.querySelectorAll('a[href*="/finishing/"]')).toHaveLength(1);
  });

  it('shows eligible finished episodes from the library', () => {
    render(<MemoryRouter><StudioHomePage/></MemoryRouter>);
    expect(document.querySelectorAll('a[href*="/finishing/"]').length).toBeGreaterThan(0);
  });
});

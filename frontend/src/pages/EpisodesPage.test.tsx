import { describe,it,expect,vi,beforeEach } from 'vitest';
import { render,screen,waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter,Route,Routes } from 'react-router-dom';
import { EpisodesPage } from './EpisodesPage';
import { api } from '../api/client';import { useLibrary } from '../hooks/useLibrary';
import { libraryCopy,p1,e1,e2,completedJob } from '../test/fixtures/library';
vi.mock('../api/client');vi.mock('../hooks/useLibrary');const refetch=vi.fn();
const page=()=>render(<MemoryRouter initialEntries={[`/project/${p1.id}`]}><Routes><Route path="/project/:projectId" element={<EpisodesPage/>}/><Route path="/episode/:episodeId/edit" element={<p>Created episode</p>}/></Routes></MemoryRouter>);
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useLibrary).mockReturnValue({data:libraryCopy(),isLoading:false,error:null,refetch});});
describe('Episodes flat backend contract',()=>{
  it('renders e1/e2, with a completed-only review URL using job.id',()=>{
    page();expect(screen.getByText('Серия 1')).toBeInTheDocument();expect(screen.getByText('Серия 2')).toBeInTheDocument();
    expect(screen.queryByText('Серия 3')).not.toBeInTheDocument();
    const links=screen.getAllByText('Посмотреть результаты');expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute('href',`/episode/${e1.id}/review/${completedJob.id}`);
  });
  it('creates an episode with a real number and follows its ID',async()=>{
    const {jobs:_,...stored}=e1;vi.mocked(api.createEpisode).mockResolvedValue(stored);page();
    await userEvent.type(screen.getByRole('spinbutton'),'3');await userEvent.click(screen.getByRole('button',{name:/Добавить серию/}));
    expect(api.createEpisode).toHaveBeenCalledWith(p1.id,3);expect(refetch).toHaveBeenCalled();
    expect(await screen.findByText('Created episode')).toBeInTheDocument();
  });
  it('allows an empty episode number so the backend can assign the next one',async()=>{
    const {jobs:_,...stored}=e1;vi.mocked(api.createEpisode).mockResolvedValue(stored);page();
    const field=screen.getByRole('spinbutton');
    expect(field).not.toBeRequired();
    await userEvent.click(screen.getByRole('button',{name:/Добавить серию/}));
    expect(api.createEpisode).toHaveBeenCalledWith(p1.id,undefined);
    expect(await screen.findByText('Created episode')).toBeInTheDocument();
  });
  it('archives an idle episode, locks running episode and parent deletion',async()=>{
    vi.mocked(api.deleteEpisode).mockResolvedValue({id:e1.id,archived:true});page();
    const buttons=screen.getAllByRole('button',{name:'Удалить серию'});expect(buttons[1]).toBeDisabled();
    expect(screen.getByRole('button',{name:'Удалить проект'})).toBeDisabled();
    await userEvent.click(buttons[0]);await waitFor(()=>expect(api.deleteEpisode).toHaveBeenCalledWith(e1.id));expect(refetch).toHaveBeenCalled();
    expect(api.deleteEpisode).not.toHaveBeenCalledWith(e2.id);
  });
  it('does not create a review link for queued, failed, cancelled or interrupted jobs',()=>{
    const data=libraryCopy();data.episodes[0].jobs=data.episodes.flatMap(e=>e.jobs).filter(j=>j.status!=='completed');
    vi.mocked(useLibrary).mockReturnValue({data,isLoading:false,error:null,refetch});page();
    expect(screen.queryByText('Посмотреть результаты')).not.toBeInTheDocument();
  });
});

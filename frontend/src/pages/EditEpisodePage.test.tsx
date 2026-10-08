import { describe,it,expect,vi,beforeEach } from 'vitest';
import { render,screen,waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter,Routes,Route } from 'react-router-dom';
import { EditEpisodePage } from './EditEpisodePage';
import { api } from '../api/client';
import { useLibrary } from '../hooks/useLibrary';
import { libraryCopy,e1,e2,jobDetails } from '../test/fixtures/library';
vi.mock('../api/client');vi.mock('../hooks/useLibrary');
vi.mock('../components/SourceSelect',()=>({SourceSelect:()=> <p>Source picker</p>}));
vi.mock('../components/DeepSeekPanel',()=>({DeepSeekPanel:()=>null}));
vi.mock('../components/MusicPanel',()=>({MusicPanel:()=>null}));
vi.mock('../components/JobProgressPanel',()=>({JobProgressPanel:({jobId}:{jobId:string|null})=> <p data-testid="job">{jobId}</p>}));
const refetch=vi.fn();
const page=(id:string)=>render(<MemoryRouter initialEntries={[`/episode/${id}/edit`]}><Routes><Route path="/episode/:episodeId/edit" element={<EditEpisodePage/>}/></Routes></MemoryRouter>);
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useLibrary).mockReturnValue({data:libraryCopy(),isLoading:false,error:null,refetch});vi.mocked(api.getJob).mockImplementation(async id=>jobDetails(id));});
describe('Edit flat episode ownership and job references',()=>{
  it('finds the episode and parent without nested projects and chooses latest fallback reference',async()=>{
    page(e1.id);expect(screen.getAllByText('Project 1').length).toBeGreaterThan(0);
    expect(screen.getByText('Серия 1 · настройки монтажа')).toBeInTheDocument();
    await waitFor(()=>expect(screen.getByTestId('job')).toHaveTextContent(e1.jobs[0].id));
    for(const call of vi.mocked(api.getJob).mock.calls) expect(typeof call[0]).toBe('string');
  });
  it('prioritizes running job and locks episode deletion',async()=>{
    page(e2.id);await waitFor(()=>expect(screen.getByTestId('job')).toHaveTextContent(e2.jobs[0].id));
    expect(screen.getByRole('button',{name:'Удалить серию'})).toBeDisabled();
    expect(api.getJob).toHaveBeenCalledWith(e2.jobs[0].id);
  });
  it('saves series settings with success feedback without launching montage',async()=>{
    const data=libraryCopy();data.episodes[0].source_id='fixture-source';
    vi.mocked(useLibrary).mockReturnValue({data,isLoading:false,error:null,refetch});
    page(e1.id);
    const save=screen.getByRole('button',{name:'Сохранить настройки серии'});
    await waitFor(()=>expect(save).toBeEnabled());
    await userEvent.click(save);
    expect(api.saveEpisodeSettings).toHaveBeenCalledWith(e1.id,expect.objectContaining({source_id:'fixture-source'}));
    expect(api.launchEpisodeJob).not.toHaveBeenCalled();
    expect(await screen.findByRole('status')).toHaveClass('success');
  });
});

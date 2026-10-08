import {describe,it,expect,vi,beforeEach} from 'vitest';
import {render,screen,waitFor} from '@testing-library/react';import {MemoryRouter,Routes,Route} from 'react-router-dom';
import {ReviewEpisodePage} from './ReviewEpisodePage';import {useLibrary} from '../hooks/useLibrary';import {api} from '../api/client';
import {libraryCopy,e1,completedJob,jobDetails} from '../test/fixtures/library';
vi.mock('../hooks/useLibrary');vi.mock('../api/client');const refetch=vi.fn();
const page=(jobId?:string)=>render(<MemoryRouter initialEntries={[`/episode/${e1.id}/review${jobId?'/'+jobId:''}`]}><Routes><Route path="/episode/:episodeId/review/:jobId?" element={<ReviewEpisodePage/>}/></Routes></MemoryRouter>);
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useLibrary).mockReturnValue({data:libraryCopy(),isLoading:false,error:null,refetch});
 vi.mocked(api.getJob).mockImplementation(async id=>jobDetails(id));vi.mocked(api.getJobPlan).mockResolvedValue({source:{duration:10},parts:[]});});
describe('Review real job references',()=>{
 it('shows loading rather than a false empty result while fetching',()=>{
  vi.mocked(api.getJob).mockReturnValue(new Promise(()=>{}));page();
  expect(screen.getByRole('status')).toHaveTextContent('Загрузка монтажа');
  expect(screen.queryByText(/Готового монтажа пока нет/)).not.toBeInTheDocument();
 });
 it('requests completed job by its string ID, ignoring newer failed attempts',async()=>{
  page();await waitFor(()=>expect(api.getJobPlan).toHaveBeenCalledWith(completedJob.id));
  expect(api.getJob).toHaveBeenCalledWith(completedJob.id);expect(api.getJob).toHaveBeenCalledTimes(1);
  expect(screen.getAllByRole('option')).toHaveLength(2);
 });
 it('rejects foreign job before making its API request',async()=>{
  page('foreignJob');expect(await screen.findByText('Монтаж не принадлежит данной серии')).toBeInTheDocument();expect(api.getJob).not.toHaveBeenCalled();
 });
 it('rejects noncompleted own job without loading a plan',async()=>{
  page(e1.jobs.find(j=>j.status==='failed')!.id);expect(await screen.findByText('Монтаж ещё не завершён')).toBeInTheDocument();expect(api.getJobPlan).not.toHaveBeenCalled();
 });
 it('shows a truthful empty state without completed references',async()=>{
  const data=libraryCopy();data.episodes[0].jobs=data.episodes[0].jobs.filter(j=>j.status!=='completed');
  vi.mocked(useLibrary).mockReturnValue({data,isLoading:false,error:null,refetch});page();
  expect(await screen.findByText('Нет завершённых монтажей для проверки')).toBeInTheDocument();expect(api.getJob).not.toHaveBeenCalled();
 });
 it('shows plan API errors',async()=>{
  vi.mocked(api.getJobPlan).mockRejectedValue(new Error('Plan boom'));page(completedJob.id);
  expect(await screen.findByText('Plan boom')).toBeInTheDocument();
 });
});

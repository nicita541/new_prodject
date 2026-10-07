import {describe,it,expect,vi,beforeEach} from 'vitest';
import {render,screen} from '@testing-library/react';import userEvent from '@testing-library/user-event';
import {MemoryRouter} from 'react-router-dom';import {TrashPage} from './TrashPage';
import {api} from '../api/client';import {useLibrary} from '../hooks/useLibrary';
import {libraryCopy,archivedProject,archivedEpisode} from '../test/fixtures/library';
vi.mock('../api/client');vi.mock('../hooks/useLibrary');const refetch=vi.fn();
const page=()=>render(<MemoryRouter><TrashPage/></MemoryRouter>);
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useLibrary).mockReturnValue({data:libraryCopy(),isLoading:false,error:null,refetch});});
describe('Trash archived_at contract',()=>{
 it('shows archived project and episode under its active parent, without nested children',()=>{
  page();expect(screen.getByText('Archived Project')).toBeInTheDocument();expect(screen.getByText('Серия 3')).toBeInTheDocument();
  expect(screen.getByText('Project 1')).toBeInTheDocument();expect(screen.queryByText('Серия 2')).not.toBeInTheDocument();
  expect(screen.getByText('Проект · вместе со всеми сериями')).toBeInTheDocument();
 });
 it('restores project using actual id/archived response then refetches',async()=>{
  vi.mocked(api.restoreProject).mockResolvedValue({id:archivedProject.id,archived:false});page();
  await userEvent.click(screen.getByRole('button',{name:'Восстановить проект'}));
  expect(api.restoreProject).toHaveBeenCalledWith(archivedProject.id);expect(refetch).toHaveBeenCalled();
 });
 it('restored episode disappears from trash after refetch',async()=>{
  vi.mocked(api.restoreEpisode).mockResolvedValue({id:archivedEpisode.id,archived:false});
  const view=page();const data=libraryCopy();delete data.episodes[4].archived_at;
  refetch.mockImplementationOnce(async()=>{vi.mocked(useLibrary).mockReturnValue({data,isLoading:false,error:null,refetch});});
  await userEvent.click(screen.getByRole('button',{name:'Восстановить серию'}));
  expect(api.restoreEpisode).toHaveBeenCalledWith(archivedEpisode.id);
  view.rerender(<MemoryRouter><TrashPage/></MemoryRouter>);expect(screen.queryByText('Серия 3')).not.toBeInTheDocument();
 });
 it('renders empty state for real flat arrays with no archived entries',()=>{
  vi.mocked(useLibrary).mockReturnValue({data:{projects:[],episodes:[]},isLoading:false,error:null,refetch});
  page();expect(screen.getByText('Корзина пуста.')).toBeInTheDocument();
 });
});

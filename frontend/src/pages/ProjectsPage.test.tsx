import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ProjectsPage } from './ProjectsPage';
import { api } from '../api/client';
import { useLibrary } from '../hooks/useLibrary';
import { libraryCopy, p1 } from '../test/fixtures/library';
vi.mock('../api/client'); vi.mock('../hooks/useLibrary');
const refetch=vi.fn();
const page=()=>render(<MemoryRouter><ProjectsPage /></MemoryRouter>);
beforeEach(()=>{vi.clearAllMocks();vi.mocked(useLibrary).mockReturnValue({data:libraryCopy(),isLoading:false,error:null,refetch});});
describe('Projects backend contract',()=>{
  it('shows real episode and ready counts and hides archived projects',()=>{
    page(); expect(screen.getByText('Project 1')).toBeInTheDocument();
    expect(screen.getByText('Серий: 2 · готовы: 1')).toBeInTheDocument();
    expect(screen.queryByText('Archived Project')).not.toBeInTheDocument();
  });
  it('creates a project with the entered title and refetches',async()=>{
    vi.mocked(api.createProject).mockResolvedValue(p1); page();
    await userEvent.type(screen.getByPlaceholderText(/Название нового проекта/),'New Project');
    await userEvent.click(screen.getByRole('button',{name:/Создать проект/}));
    expect(api.createProject).toHaveBeenCalledWith('New Project');expect(refetch).toHaveBeenCalled();
  });
  it('disables deletion for projects with running or queued jobs',()=>{
    const data=libraryCopy();data.episodes[2].jobs[0].status='queued';
    vi.mocked(useLibrary).mockReturnValue({data,isLoading:false,error:null,refetch});
    page(); for(const button of screen.getAllByRole('button',{name:'Удалить проект'})) expect(button).toBeDisabled();
  });
  it('archives an idle project and refetches',async()=>{
    const data=libraryCopy();data.episodes[1].jobs=[];
    vi.mocked(useLibrary).mockReturnValue({data,isLoading:false,error:null,refetch});
    vi.mocked(api.deleteProject).mockResolvedValue({id:p1.id,archived:true});page();
    await userEvent.click(screen.getAllByRole('button',{name:'Удалить проект'})[0]);
    await waitFor(()=>expect(api.deleteProject).toHaveBeenCalledWith(p1.id));expect(refetch).toHaveBeenCalled();
  });
});

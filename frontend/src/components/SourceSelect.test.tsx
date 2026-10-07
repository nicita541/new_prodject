import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest';
import {render,screen,waitFor,fireEvent} from '@testing-library/react';import userEvent from '@testing-library/user-event';
import {SourceSelect} from './SourceSelect';import {api} from '../api/client';
vi.mock('../api/client');const onChange=vi.fn();
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.getSources).mockResolvedValue([{id:'s1',name:'video1.mp4',size:10},{id:'s2',name:'video2.mp4',size:20}]);});
afterEach(()=>vi.unstubAllGlobals());
describe('SourceSelect actual sources/import contract',()=>{
 it('renders sources and returns selected source ID',async()=>{
  render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);await screen.findByText('video1.mp4');
  await userEvent.selectOptions(screen.getByRole('combobox'),'s2');expect(onChange).toHaveBeenCalledWith('s2');
 });
 it('disables selection and import while locked',()=>{
  const view=render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange} disabled/>);
  expect(screen.getByRole('combobox')).toBeDisabled();expect(view.container.querySelector('input[type="file"]')).not.toBeInTheDocument();
 });
 it('uses multipart /api/import and its Source.id response',async()=>{
  const xhr={open:vi.fn(),send:vi.fn(),upload:{onprogress:null},status:201,responseText:JSON.stringify({id:'s3',name:'new.mp4',size:5}),onload:null as null|(()=>void),onerror:null};
  vi.stubGlobal('XMLHttpRequest',vi.fn(function(){return xhr;}));
  const view=render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  fireEvent.change(view.container.querySelector('input[type="file"]')!,{target:{files:[new File(['video'],'new.mp4',{type:'video/mp4'})]}});
  expect(xhr.open).toHaveBeenCalledWith('POST','/api/import',true);expect(xhr.send).toHaveBeenCalledWith(expect.any(FormData));
  xhr.onload!();await waitFor(()=>expect(onChange).toHaveBeenCalledWith('s3'));
 });
 it('does not accept an error response as a source ID',async()=>{
  const alert=vi.spyOn(window,'alert').mockImplementation(()=>{});
  const xhr={open:vi.fn(),send:vi.fn(),upload:{onprogress:null},status:400,responseText:'Invalid media',onload:null as null|(()=>void),onerror:null};
  vi.stubGlobal('XMLHttpRequest',vi.fn(function(){return xhr;}));
  const view=render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  fireEvent.change(view.container.querySelector('input[type="file"]')!,{target:{files:[new File(['bad'],'bad.mp4')]}});xhr.onload!();
  expect(alert).toHaveBeenCalledWith('Ошибка загрузки: Invalid media');expect(onChange).not.toHaveBeenCalled();alert.mockRestore();
 });
});

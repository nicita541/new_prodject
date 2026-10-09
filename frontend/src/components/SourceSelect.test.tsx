import {describe,it,expect,vi,beforeEach,afterEach} from 'vitest';
import {render,screen,waitFor,fireEvent,act} from '@testing-library/react';import userEvent from '@testing-library/user-event';
import {SourceSelect} from './SourceSelect';import {api} from '../api/client';
vi.mock('../api/client');const onChange=vi.fn();
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.getSources).mockResolvedValue([{id:'s1',name:'video1.mp4',size:10},{id:'s2',name:'video2.mp4',size:20}]);});
afterEach(()=>vi.unstubAllGlobals());
describe('SourceSelect actual sources/import contract',()=>{
 it('rejects WebM before starting an upload because the API supports only MP4/MKV',()=>{
  const xhr = vi.fn();
  vi.stubGlobal('XMLHttpRequest', xhr);
  const view = render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  const input = view.container.querySelector('input[type="file"]') as HTMLInputElement;
  expect(input.accept).toBe('.mp4,.mkv');
  fireEvent.change(input,{target:{files:[new File(['video'],'unsupported.webm')]}});
  expect(screen.getByRole('alert')).toHaveTextContent('MP4 или MKV');
  expect(xhr).not.toHaveBeenCalled();
 });

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
  act(()=>xhr.onload!());await waitFor(()=>expect(onChange).toHaveBeenCalledWith('s3'));
 });
 it('does not accept an error response as a source ID',async()=>{
  const xhr={open:vi.fn(),send:vi.fn(),upload:{onprogress:null},status:400,responseText:'Invalid media',onload:null as null|(()=>void),onerror:null};
  vi.stubGlobal('XMLHttpRequest',vi.fn(function(){return xhr;}));
  const view=render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  await screen.findByText('video1.mp4');
  fireEvent.change(view.container.querySelector('input[type="file"]')!,{target:{files:[new File(['bad'],'bad.mp4')]}});act(()=>xhr.onload!());
  expect(screen.getByRole('alert')).toHaveTextContent('Ошибка загрузки: Invalid media');expect(onChange).not.toHaveBeenCalled();
 });
 it('imports a dropped file and prevents overlapping uploads',()=>{
  const xhr={open:vi.fn(),send:vi.fn(),upload:{onprogress:null},status:201,responseText:'{"id":"s3"}',onload:null,onerror:null};
  vi.stubGlobal('XMLHttpRequest',vi.fn(function(){return xhr;}));
  render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  const zone=screen.getByRole('button',{name:'Загрузить файл'});
  const drop={dataTransfer:{files:[new File(['video'],'dropped.mp4',{type:'video/mp4'})]}};
  fireEvent.drop(zone,drop);fireEvent.drop(zone,drop);
  expect(xhr.send).toHaveBeenCalledTimes(1);expect(zone).toHaveAttribute('aria-disabled','true');
 });
 it('opens file picker with the keyboard',()=>{
  const view=render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  const input=view.container.querySelector('input[type="file"]')!;
  const click=vi.spyOn(input as HTMLInputElement,'click');
  fireEvent.keyDown(screen.getByRole('button',{name:'Загрузить файл'}),{key:'Enter'});
  expect(click).toHaveBeenCalledTimes(1);
 });
 it('recovers from a malformed successful upload response',async()=>{
  const xhr={open:vi.fn(),send:vi.fn(),upload:{onprogress:null},status:201,responseText:'invalid',onload:null as null|(()=>void),onerror:null};
  vi.stubGlobal('XMLHttpRequest',vi.fn(function(){return xhr;}));
  render(<SourceSelect episodeId="e1" sourceId="" onChange={onChange}/>);
  await screen.findByText('video1.mp4');
  fireEvent.drop(screen.getByRole('button',{name:'Загрузить файл'}),{dataTransfer:{files:[new File(['video'],'dropped.mp4')]}});
  act(()=>xhr.onload!());expect(screen.getByRole('alert')).toHaveTextContent('Не удалось прочитать ответ загрузки');
  expect(screen.getByRole('combobox')).toBeEnabled();expect(onChange).not.toHaveBeenCalled();
 });
});

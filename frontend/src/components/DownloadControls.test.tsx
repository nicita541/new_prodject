import {describe,it,expect,vi,beforeEach} from 'vitest';import {render,screen} from '@testing-library/react';import userEvent from '@testing-library/user-event';
import {DownloadControls} from './DownloadControls';import {api} from '../api/client';
vi.mock('../api/client');const files=[{name:'file1.mp4',url:'/api/jobs/job1/files/file1.mp4',subtitle_url:'/api/jobs/job1/files/file1.srt',duration:null},{name:'file2.mp4',url:'/api/jobs/job1/files/file2.mp4',subtitle_url:null}];
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.saveVideos).mockResolvedValue({cancelled:false,count:2,files:['file1.mp4','file2.mp4']});});
describe('DownloadControls backend receipt contract',()=>{
 it('disables actions with no registered file',()=>{render(<DownloadControls jobId="job1" files={[]} selectedIndex={0}/>);expect(screen.getByRole('button',{name:/Скачать MP4/})).toBeDisabled();expect(screen.getByRole('button',{name:/Сохранить все/})).toBeDisabled();});
 it('saves selected MP4 by registered name',async()=>{render(<DownloadControls jobId="job1" files={files} selectedIndex={0}/>);await userEvent.click(screen.getByRole('button',{name:/Скачать MP4/}));expect(api.saveVideos).toHaveBeenCalledWith('job1',false,'file1.mp4');});
 it('downloads subtitle through the supplied file URL',()=>{render(<DownloadControls jobId="job1" files={files} selectedIndex={0}/>);expect(screen.getByRole('link',{name:'Субтитры'})).toHaveAttribute('href',files[0].subtitle_url+'?download=1');});
 it('saves all files through the actual endpoint',async()=>{render(<DownloadControls jobId="job1" files={files} selectedIndex={0}/>);await userEvent.click(screen.getByRole('button',{name:/Сохранить все/}));expect(api.saveVideos).toHaveBeenCalledWith('job1',true);expect(screen.getByText('Успешно сохранено видео: 2')).toBeInTheDocument();});
 it('reports a partial save failure without claiming success',async()=>{vi.mocked(api.saveVideos).mockRejectedValue(new Error('partial'));render(<DownloadControls jobId="job1" files={files} selectedIndex={0}/>);await userEvent.click(screen.getByRole('button',{name:/Сохранить все/}));expect(screen.getByText(/Не удалось сохранить видео: partial/)).toBeInTheDocument();});
});

import {describe,it,expect,vi} from 'vitest';import {render,screen} from '@testing-library/react';import userEvent from '@testing-library/user-event';import {PartContext} from './PartContext';
const part={index:1,cuts:[],cover_context:{title:'Test Title',synopsis:'Test Synopsis',prompt:'Test Prompt',method:'vision'}};
describe('PartContext actual plan context',()=>{
 it('renders cover_context synopsis and prompt',()=>{render(<PartContext part={part}/>);expect(screen.getByText('Test Synopsis')).toBeInTheDocument();expect(screen.getByDisplayValue('Test Prompt')).toBeInTheDocument();});
 it('handles missing optional context',()=>{render(<PartContext part={{index:1,cuts:[]}}/>);expect(screen.getByText('Контекст неизвестен')).toBeInTheDocument();expect(screen.getByRole('button',{name:'Скопировать'})).toBeDisabled();});
 it('copies current synopsis and prompt',async()=>{const user=userEvent.setup();const writeText=vi.spyOn(navigator.clipboard,'writeText').mockResolvedValue(undefined);render(<PartContext part={part}/>);await user.click(screen.getByText('Скопировать'));expect(writeText).toHaveBeenCalledWith('Контекст: Test Synopsis\n\nTest Prompt');writeText.mockRestore();});
});

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PartContext } from './PartContext';

describe('PartContext', () => {
  it('renders correctly with all data', () => {
    const part = {
      title: 'Test Title',
      synopsis: 'Test Synopsis',
      prompts: { image: 'Test Prompt' }
    } as any;
    render(<PartContext part={part} />);

    expect(screen.getByText('Test Title')).toBeInTheDocument();
    expect(screen.getByText('Test Synopsis')).toBeInTheDocument();
    expect(screen.getByText('Test Prompt')).toBeInTheDocument();
  });

  it('renders without missing data safely', () => {
    render(<PartContext part={{} as any} />);
    expect(screen.getByText(/часть/i)).toBeInTheDocument();
  });

  it('copies prompt to clipboard', async () => {
    const part = { prompts: { image: 'CopyMe' } } as any;
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<PartContext part={part} />);
    await userEvent.click(screen.getByText('Скопировать'));
    
    expect(writeText).toHaveBeenCalledWith('CopyMe');
  });
});

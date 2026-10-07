import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Playlist } from './Playlist';

describe('Playlist', () => {
  it('renders empty state', () => {
    render(<Playlist files={[]} selectedIndex={0} onSelect={() => {}} />);
    expect(screen.getByText('Готовых частей пока нет')).toBeInTheDocument();
  });

  it('renders items and handles selection', async () => {
    const files = [
      { duration: 15.5 },
      { duration: 30.1 }
    ] as any;
    const onSelect = vi.fn();

    render(<Playlist files={files} selectedIndex={0} onSelect={onSelect} />);
    
    const btns = screen.getAllByRole('button');
    expect(btns).toHaveLength(2);
    expect(btns[0]).toHaveAttribute('aria-pressed', 'true');
    expect(btns[1]).toHaveAttribute('aria-pressed', 'false');
    expect(btns[0]).toHaveTextContent('15.5s');
    expect(btns[1]).toHaveTextContent('30.1s');

    await userEvent.click(btns[1]);
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});

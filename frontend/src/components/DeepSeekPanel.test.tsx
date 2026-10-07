import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeepSeekPanel } from './DeepSeekPanel';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    checkDeepSeek: vi.fn()
  }
}));

describe('DeepSeekPanel', () => {
  it('renders available status with balance', async () => {
    vi.mocked(client.api.checkDeepSeek).mockResolvedValue({
      available: true,
      model: 'deepseek-chat',
      balance_infos: [{ total_balance: '100', currency: 'USD' }]
    } as any);

    render(<DeepSeekPanel />);

    await waitFor(() => {
      expect(screen.getByText('Доступен')).toBeInTheDocument();
      expect(screen.getByText('100 USD')).toBeInTheDocument();
      expect(screen.getByText('deepseek-chat')).toBeInTheDocument();
    });
  });

  it('renders unavailable status', async () => {
    vi.mocked(client.api.checkDeepSeek).mockResolvedValue({
      available: false,
      error: 'Not configured'
    } as any);

    render(<DeepSeekPanel />);

    await waitFor(() => {
      expect(screen.getByText('Недоступен')).toBeInTheDocument();
    });
  });

  it('handles API error gracefully', async () => {
    vi.mocked(client.api.checkDeepSeek).mockRejectedValue(new Error('Network error'));

    render(<DeepSeekPanel />);

    await waitFor(() => {
      expect(screen.getByText('Проблема с DeepSeek')).toBeInTheDocument();
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('refreshes status on click', async () => {
    vi.mocked(client.api.checkDeepSeek).mockResolvedValueOnce({
      available: false
    } as any).mockResolvedValueOnce({
      available: true,
      balance_infos: [{ total_balance: '50', currency: 'USD' }]
    } as any);

    render(<DeepSeekPanel />);

    await waitFor(() => {
      expect(screen.getByText('Недоступен')).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('button', { name: /Обновить/ }));

    await waitFor(() => {
      expect(screen.getByText('50 USD')).toBeInTheDocument();
    });
  });
});

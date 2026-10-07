import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QualityWarnings } from './QualityWarnings';
import type { Plan } from '../api/types';

describe('QualityWarnings', () => {
  it('renders nothing when there are no warnings or notes', () => {
    const plan: Plan = { source: { duration: 10 }, parts: [], quality_summary: { available: true, warnings: [], notes: [] } };
    const { container } = render(<QualityWarnings plan={plan} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders strings and objects correctly', () => {
    const plan: Plan = {
      source: { duration: 10 }, parts: [],
      quality_summary: {
        available: true,
        warnings: [{ text: 'String warning' }, { text: 'Object warning' }],
        notes: [{ text: 'String note' }, { text: 'Object note' }]
      }
    };
    render(<QualityWarnings plan={plan} />);

    expect(screen.getByText(/String warning/)).toBeInTheDocument();
    expect(screen.getByText(/Object warning/)).toBeInTheDocument();
    expect(screen.getByText(/String note/)).toBeInTheDocument();
    expect(screen.getByText(/Object note/)).toBeInTheDocument();
  });
});

/**
 * Tests for ModelTable collapse/expand functionality.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ModelTable } from './ModelTable';

function mkRow(model: string, runs: number, successRate: number) {
  return {
    model,
    runs,
    successRate,
    medianDuration: 100,
    stddevDuration: 10,
  };
}

describe('ModelTable', () => {
  const defaultProps = {
    sortField: 'success' as const,
    sortAsc: false,
    onSort: vi.fn(),
  };

  it('renders all rows when fewer than collapsedCount', () => {
    const rows = [mkRow('model-1', 10, 0.9), mkRow('model-2', 5, 0.8)];
    render(<ModelTable {...defaultProps} rows={rows} />);

    expect(screen.getByText('model-1')).toBeInTheDocument();
    expect(screen.getByText('model-2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /show/i })).not.toBeInTheDocument();
  });

  it('renders only top 5 rows by default when more than 5', () => {
    const rows = [
      mkRow('model-1', 10, 0.95),
      mkRow('model-2', 9, 0.90),
      mkRow('model-3', 8, 0.85),
      mkRow('model-4', 7, 0.80),
      mkRow('model-5', 6, 0.75),
      mkRow('model-6', 5, 0.70),
      mkRow('model-7', 4, 0.65),
    ];
    render(<ModelTable {...defaultProps} rows={rows} />);

    // Top 5 should be visible
    expect(screen.getByText('model-1')).toBeInTheDocument();
    expect(screen.getByText('model-2')).toBeInTheDocument();
    expect(screen.getByText('model-3')).toBeInTheDocument();
    expect(screen.getByText('model-4')).toBeInTheDocument();
    expect(screen.getByText('model-5')).toBeInTheDocument();

    // Bottom 2 should be hidden
    expect(screen.queryByText('model-6')).not.toBeInTheDocument();
    expect(screen.queryByText('model-7')).not.toBeInTheDocument();

    // Show more button should be present
    expect(screen.getByRole('button', { name: /show 2 more models/i })).toBeInTheDocument();
  });

  it('expands to show all rows when "Show more" clicked', () => {
    const rows = [
      mkRow('model-1', 10, 0.95),
      mkRow('model-2', 9, 0.90),
      mkRow('model-3', 8, 0.85),
      mkRow('model-4', 7, 0.80),
      mkRow('model-5', 6, 0.75),
      mkRow('model-6', 5, 0.70),
    ];
    render(<ModelTable {...defaultProps} rows={rows} />);

    const expandBtn = screen.getByRole('button', { name: /show 1 more model$/i });
    fireEvent.click(expandBtn);

    // Now all rows should be visible
    expect(screen.getByText('model-6')).toBeInTheDocument();

    // Button should now say "Show less"
    expect(screen.getByRole('button', { name: /show less/i })).toBeInTheDocument();
  });

  it('collapses rows when "Show less" clicked', () => {
    const rows = [
      mkRow('model-1', 10, 0.95),
      mkRow('model-2', 9, 0.90),
      mkRow('model-3', 8, 0.85),
      mkRow('model-4', 7, 0.80),
      mkRow('model-5', 6, 0.75),
      mkRow('model-6', 5, 0.70),
    ];
    render(<ModelTable {...defaultProps} rows={rows} />);

    // Expand first
    fireEvent.click(screen.getByRole('button', { name: /show 1 more model$/i }));
    expect(screen.getByText('model-6')).toBeInTheDocument();

    // Now collapse
    fireEvent.click(screen.getByRole('button', { name: /show less/i }));
    expect(screen.queryByText('model-6')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /show 1 more model$/i })).toBeInTheDocument();
  });

  it('respects custom collapsedCount prop', () => {
    const rows = [
      mkRow('model-1', 10, 0.95),
      mkRow('model-2', 9, 0.90),
      mkRow('model-3', 8, 0.85),
    ];
    render(<ModelTable {...defaultProps} rows={rows} collapsedCount={2} />);

    // Only top 2 should be visible
    expect(screen.getByText('model-1')).toBeInTheDocument();
    expect(screen.getByText('model-2')).toBeInTheDocument();
    expect(screen.queryByText('model-3')).not.toBeInTheDocument();

    expect(screen.getByRole('button', { name: /show 1 more model$/i })).toBeInTheDocument();
  });

  it('renders empty message when no rows', () => {
    render(<ModelTable {...defaultProps} rows={[]} emptyMessage="No data" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });
});

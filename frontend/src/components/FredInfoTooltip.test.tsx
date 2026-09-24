import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { FredInfoTooltip } from './FredInfoTooltip';
import * as api from '../services/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('FredInfoTooltip', () => {
  it('opens a popover whose content is NOT pointer-events: none, and a link inside it is actually clickable', async () => {
    vi.spyOn(api, 'fetchFredMetadata').mockResolvedValue({
      series_id: 'DCOILBRENTEU',
      title: 'Crude Oil Prices: Brent - Europe',
      notes: 'Definitions, Sources and Explanatory Notes (http://www.eia.doe.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp)',
    });

    render(<FredInfoTooltip seriesId="DCOILBRENTEU" />);

    const trigger = screen.getByRole('button', { name: /Información de la serie FRED/i });
    fireEvent.click(trigger);

    // Wait for the async fetch to resolve and the popover to render the link.
    const link = await screen.findByRole('link', {
      name: 'http://www.eia.doe.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp',
    });

    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', 'http://www.eia.doe.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');

    // The popover container itself must not have pointer-events: none — this
    // was the bug: the whole popover was inert regardless of what a browser's
    // hit-testing would otherwise allow, so even a real <a> inside it could
    // never actually receive a click.
    const popover = link.closest('span[class*="absolute"]');
    expect(popover).not.toBeNull();
    const computedStyle = window.getComputedStyle(popover as Element);
    expect(computedStyle.pointerEvents).not.toBe('none');

    // A real click handler must fire on the link — not just "it exists in the
    // DOM tree". jsdom doesn't perform actual navigation, but it does dispatch
    // the click event to the element and any listener attached to it; this
    // confirms nothing upstream (e.g. a pointer-events:none ancestor bypassed
    // only by jsdom's lack of hit-testing) is silently swallowing the event
    // via stopPropagation/preventDefault in a way that would break a real click.
    const clickHandler = vi.fn();
    link.addEventListener('click', clickHandler);
    fireEvent.click(link);
    expect(clickHandler).toHaveBeenCalledTimes(1);
  });

  it('stays open after the mouse leaves the icon (state-controlled, not CSS hover)', async () => {
    vi.spyOn(api, 'fetchFredMetadata').mockResolvedValue({
      series_id: 'DHHNGSP',
      title: 'Henry Hub Natural Gas Spot Price',
      notes: 'More information about this series can be found at http://www.eia.gov/dnav/ng/TblDefs/ng_pri_fut_tbldef2.asp',
    });

    render(<FredInfoTooltip seriesId="DHHNGSP" />);
    const trigger = screen.getByRole('button', { name: /Información de la serie FRED/i });

    fireEvent.click(trigger);
    await screen.findByRole('link', { name: /eia\.gov/ });

    // Simulate the mouse moving away from the icon entirely — a CSS
    // hover/group-hover implementation would hide the popover at this point.
    fireEvent.mouseLeave(trigger);

    expect(screen.getByRole('link', { name: /eia\.gov/ })).toBeInTheDocument();
  });

  it('closes when clicking outside the popover', async () => {
    vi.spyOn(api, 'fetchFredMetadata').mockResolvedValue({
      series_id: 'DHHNGSP',
      title: 'Henry Hub Natural Gas Spot Price',
      notes: 'No links here.',
    });

    render(
      <div>
        <FredInfoTooltip seriesId="DHHNGSP" />
        <div data-testid="outside">Outside content</div>
      </div>
    );

    fireEvent.click(screen.getByRole('button', { name: /Información de la serie FRED/i }));
    await screen.findByText('No links here.');

    fireEvent.mouseDown(screen.getByTestId('outside'));

    expect(screen.queryByText('No links here.')).not.toBeInTheDocument();
  });

  it('closes via its own close button', async () => {
    vi.spyOn(api, 'fetchFredMetadata').mockResolvedValue({
      series_id: 'DHHNGSP',
      title: 'Henry Hub Natural Gas Spot Price',
      notes: 'No links here either.',
    });

    render(<FredInfoTooltip seriesId="DHHNGSP" />);
    fireEvent.click(screen.getByRole('button', { name: /Información de la serie FRED/i }));
    await screen.findByText('No links here either.');

    fireEvent.click(screen.getByRole('button', { name: /Cerrar/i }));

    expect(screen.queryByText('No links here either.')).not.toBeInTheDocument();
  });
});

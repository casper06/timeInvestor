import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BackendWarnings } from './BackendWarnings';

/**
 * 4.4: the backend's warnings reach the screen. They used to be dropped in
 * Fundamentals, portfolio optimization and risk — the numbers looked clean
 * while the reason they weren't was thrown away.
 */
describe('BackendWarnings (4.4)', () => {
  it('renders nothing when there are no warnings', () => {
    const { container } = render(<BackendWarnings warnings={[]} testId="w" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when warnings are missing entirely', () => {
    const { container } = render(<BackendWarnings warnings={undefined} testId="w" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('lists every warning the backend sent', () => {
    render(
      <BackendWarnings
        warnings={['Sin fundamentales para PSQ.', 'La matriz necesitó un shrinkage alto (0.87).']}
        testId="w"
      />,
    );
    const box = screen.getByTestId('w');
    expect(box).toHaveTextContent('Sin fundamentales para PSQ.');
    expect(box).toHaveTextContent('La matriz necesitó un shrinkage alto (0.87).');
    expect(box).toHaveTextContent('Advertencias del cálculo (2)');
  });

  it('uses the singular for a single warning', () => {
    render(<BackendWarnings warnings={['Una sola.']} testId="w" />);
    expect(screen.getByTestId('w')).toHaveTextContent('Advertencia del cálculo');
  });

  it('is announced to assistive tech', () => {
    render(<BackendWarnings warnings={['Algo pasó.']} testId="w" />);
    expect(screen.getByTestId('w')).toHaveAttribute('role', 'status');
  });
});

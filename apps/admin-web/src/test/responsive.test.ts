import { describe, expect, it } from 'vitest';
import { repoFile } from './repo';

// jsdom has no layout engine. This guards the CSS CONTRACT (breakpoints, drawer, no fixed overflow);
// the rendered result at each width is verified separately with real-browser screenshots (docs/admin-01).
const css = repoFile('apps/admin-web/src/styles/app.css');

describe('responsive CSS contract', () => {
  it('collapses the sidebar into a drawer below 1024 px', () => {
    expect(css).toMatch(/@media \(max-width: 1023px\)[\s\S]*\.sidebar[\s\S]*translateX\(-102%\)/);
    expect(css).toMatch(/\.menu-toggle \{ display: inline-flex; \}/);
  });
  it('stacks the editor and two-column layouts on narrow screens', () => {
    expect(css).toMatch(/max-width: 1180px[\s\S]*\.editor-grid \{ grid-template-columns: 1fr; \}/);
    expect(css).toMatch(/\.two-col \{ grid-template-columns: 1fr; \}/);
  });
  it('keeps tables scrollable inside their own region instead of scrolling the page', () => {
    // position: relative keeps visually-hidden spans inside the cells from escaping the scroll region (caused page-wide overflow on phones).
    expect(css).toMatch(/\.table-wrap \{ position: relative; overflow-x: auto;/);
  });
  it('honours reduced motion and visible focus', () => {
    expect(css).toMatch(/prefers-reduced-motion: reduce/);
    expect(css).toMatch(/:focus-visible \{ outline: 3px solid/);
  });
  it('uses no inline-style-dependent layout (strict CSP: style-src self)', async () => {
    const files = ['components/charts.tsx', 'components/Heatmap.tsx', 'components/PhonePreview.tsx', 'pages/Dashboard.tsx'];
    for (const f of files) expect(repoFile(`apps/admin-web/src/${f}`)).not.toMatch(/style=\{\{/);
  });
});

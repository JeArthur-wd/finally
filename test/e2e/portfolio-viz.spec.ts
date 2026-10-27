import { test, expect, openApp, apiBuy } from './helpers';

test.describe('Portfolio visualisations', () => {
  test('heatmap shows a coloured cell per position', async ({ page, request }) => {
    await apiBuy(request, 'AAPL', 2);
    await apiBuy(request, 'NVDA', 1);
    await openApp(page);

    await expect(page.getByTestId('heatmap')).toBeVisible();
    for (const t of ['AAPL', 'NVDA']) {
      const cell = page.getByTestId(`heatmap-cell-${t}`);
      await expect(cell).toBeVisible();
      const box = await cell.boundingBox();
      expect(box, `heatmap cell ${t} has no box`).not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
      expect(box!.height).toBeGreaterThan(0);
      // Cell must be coloured (works for HTML divs or SVG rects).
      const colour = await cell.evaluate((el) => {
        const cs = getComputedStyle(el);
        return el instanceof SVGElement ? cs.fill : cs.backgroundColor;
      });
      expect(colour).not.toMatch(/^(rgba\(0, 0, 0, 0\)|transparent|none)$/);
    }
    await expect(page.getByTestId('position-row-AAPL')).toBeVisible();
    await expect(page.getByTestId('position-row-NVDA')).toBeVisible();
  });

  test('P&L chart renders with snapshot data', async ({ page, request }) => {
    await apiBuy(request, 'AAPL', 1);
    const history = await (await request.get('/api/portfolio/history')).json();
    // reset records one snapshot and the trade records another.
    expect(history.length).toBeGreaterThanOrEqual(2);

    await openApp(page);
    const chart = page.getByTestId('pnl-chart');
    await expect(chart).toBeVisible();
    await expect(chart.locator('canvas').first()).toBeVisible(); // Lightweight Charts draws to canvas
    const box = await chart.boundingBox();
    expect(box!.width).toBeGreaterThan(50);
    expect(box!.height).toBeGreaterThan(50);
  });

  test('clicking a watchlist ticker shows it in the main chart', async ({ page }) => {
    await openApp(page);
    await page.getByTestId('watchlist-row-TSLA').click();
    const chart = page.getByTestId('main-chart');
    await expect(chart).toBeVisible();
    await expect(chart).toContainText('TSLA');
    await expect(chart.locator('canvas').first()).toBeVisible();
  });
});

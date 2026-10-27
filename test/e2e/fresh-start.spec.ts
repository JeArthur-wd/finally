import { test, expect, DEFAULT_TICKERS, openApp, readNumber, waitForPrice, parseNumber } from './helpers';

test.describe('Fresh start', () => {
  test('shows the 10 default tickers in order', async ({ page }) => {
    await openApp(page);
    const rows = page.getByTestId('watchlist').locator('[data-testid^="watchlist-row-"]');
    await expect(rows).toHaveCount(10);
    for (const t of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${t}`)).toBeVisible();
    }
    const ids = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')));
    expect(ids).toEqual(DEFAULT_TICKERS.map((t) => `watchlist-row-${t}`));
  });

  test('shows $10,000.00 cash and total value', async ({ page }) => {
    await openApp(page);
    await expect(page.getByTestId('cash-balance')).toHaveText(/\$\s*10,000\.00/);
    await expect.poll(() => readNumber(page, 'total-value')).toBeCloseTo(10000, 2);
  });

  test('connection indicator is connected', async ({ page }) => {
    await openApp(page);
    await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected');
  });

  test('prices stream and change over time', async ({ page }) => {
    await openApp(page);
    const initial: Record<string, number> = {};
    for (const t of DEFAULT_TICKERS) initial[t] = await waitForPrice(page, t);
    // With ~500ms simulator ticks, at least one price must change within a few seconds.
    await expect
      .poll(
        async () => {
          for (const t of DEFAULT_TICKERS) {
            const now = parseNumber(await page.getByTestId(`watchlist-price-${t}`).textContent());
            if (Number.isFinite(now) && now !== initial[t]) return true;
          }
          return false;
        },
        { message: 'no watchlist price changed', timeout: 15_000 },
      )
      .toBe(true);
  });

  test('empty positions state and main chart are shown', async ({ page }) => {
    await openApp(page);
    await expect(page.getByText(/No positions yet/i).first()).toBeVisible();
    await expect(page.getByTestId('main-chart')).toBeVisible();
    await expect(page.getByTestId('positions-table').locator('[data-testid^="position-row-"]')).toHaveCount(0);
  });
});

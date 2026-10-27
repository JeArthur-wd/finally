import { test, expect, openApp, waitForPrice } from './helpers';

const rows = (page: import('@playwright/test').Page) =>
  page.getByTestId('watchlist').locator('[data-testid^="watchlist-row-"]');

test.describe('Watchlist', () => {
  test('add a ticker via the UI; it gets a live price', async ({ page, request }) => {
    await openApp(page);
    await page.getByTestId('watchlist-add-input').fill('pypl');
    await page.getByTestId('watchlist-add-button').click();
    await expect(page.getByTestId('watchlist-row-PYPL')).toBeVisible();
    await expect(rows(page)).toHaveCount(11);
    await waitForPrice(page, 'PYPL');

    const items: Array<{ ticker: string }> = await (await request.get('/api/watchlist')).json();
    expect(items[items.length - 1].ticker).toBe('PYPL');
  });

  test('remove a ticker via the UI', async ({ page, request }) => {
    await openApp(page);
    const row = page.getByTestId('watchlist-row-NFLX');
    await expect(row).toBeVisible();
    await row.hover(); // remove button may be hover-revealed
    await page.getByTestId('watchlist-remove-NFLX').click();
    await expect(row).toHaveCount(0);
    await expect(rows(page)).toHaveCount(9);

    const items: Array<{ ticker: string }> = await (await request.get('/api/watchlist')).json();
    expect(items.map((i) => i.ticker)).not.toContain('NFLX');
  });

  test('add then remove persists across reloads', async ({ page }) => {
    await openApp(page);
    await page.getByTestId('watchlist-add-input').fill('SHOP');
    await page.getByTestId('watchlist-add-button').click();
    await expect(page.getByTestId('watchlist-row-SHOP')).toBeVisible();

    await page.reload();
    const row = page.getByTestId('watchlist-row-SHOP');
    await expect(row).toBeVisible();
    await row.hover();
    await page.getByTestId('watchlist-remove-SHOP').click();
    await expect(row).toHaveCount(0);

    await page.reload();
    await expect(page.getByTestId('watchlist-row-AAPL')).toBeVisible();
    await expect(page.getByTestId('watchlist-row-SHOP')).toHaveCount(0);
  });
});

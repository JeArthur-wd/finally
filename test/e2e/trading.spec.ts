import { test, expect, openApp, readNumber, waitForPrice, apiBuy, apiPortfolio, trade } from './helpers';

test.describe('Trading', () => {
  test('buy: cash decreases and a position row appears', async ({ page, request }) => {
    await openApp(page);
    await waitForPrice(page, 'AAPL');
    await trade(page, 'AAPL', '2', 'buy');

    const row = page.getByTestId('position-row-AAPL');
    await expect(row).toBeVisible();
    await expect(row).toContainText('AAPL');
    await expect.poll(() => readNumber(page, 'cash-balance')).toBeLessThan(10000);

    const pf = await apiPortfolio(request);
    expect(pf.positions).toHaveLength(1);
    expect(pf.positions[0].ticker).toBe('AAPL');
    expect(pf.positions[0].quantity).toBeCloseTo(2, 4);
    await expect.poll(() => readNumber(page, 'cash-balance')).toBeCloseTo(pf.cash_balance, 2);
    await expect(page.getByTestId('heatmap-cell-AAPL')).toBeVisible();
  });

  test('sell all: cash increases and the position disappears', async ({ page, request }) => {
    await apiBuy(request, 'AAPL', 3);
    const afterBuy = await apiPortfolio(request);
    await openApp(page);
    await expect(page.getByTestId('position-row-AAPL')).toBeVisible();

    await trade(page, 'AAPL', '3', 'sell');
    await expect(page.getByTestId('position-row-AAPL')).toHaveCount(0);
    await expect(page.getByTestId('heatmap-cell-AAPL')).toHaveCount(0);
    await expect.poll(() => readNumber(page, 'cash-balance')).toBeGreaterThan(afterBuy.cash_balance);

    const pf = await apiPortfolio(request);
    expect(pf.positions).toHaveLength(0);
    await expect.poll(() => readNumber(page, 'cash-balance')).toBeCloseTo(pf.cash_balance, 2);
  });

  test('partial sell keeps the position with reduced quantity', async ({ page, request }) => {
    await apiBuy(request, 'MSFT', 5);
    await openApp(page);
    await expect(page.getByTestId('position-row-MSFT')).toBeVisible();
    await trade(page, 'MSFT', '2', 'sell');

    await expect.poll(async () => (await apiPortfolio(request)).positions[0]?.quantity).toBeCloseTo(3, 4);
    await expect(page.getByTestId('position-row-MSFT')).toBeVisible();
  });

  test('selling shares not held shows a trade error', async ({ page, request }) => {
    await openApp(page);
    await trade(page, 'AAPL', '5', 'sell');
    await expect(page.getByTestId('trade-error')).toContainText(/insufficient shares/i);
    const pf = await apiPortfolio(request);
    expect(pf.cash_balance).toBe(10000);
    expect(pf.positions).toHaveLength(0);
  });

  test('buying beyond available cash shows a trade error', async ({ page }) => {
    await openApp(page);
    await waitForPrice(page, 'AAPL');
    await trade(page, 'AAPL', '100000', 'buy');
    await expect(page.getByTestId('trade-error')).toContainText(/insufficient cash/i);
    await expect(page.getByTestId('position-row-AAPL')).toHaveCount(0);
    await expect(page.getByTestId('cash-balance')).toHaveText(/10,000\.00/);
  });
});

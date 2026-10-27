/**
 * Shared helpers for FinAlly E2E specs.
 * Selectors follow planning/API_CONTRACT.md §7 data-testids.
 */
import { APIRequestContext, Page, expect, test as base } from '@playwright/test';

export const DEFAULT_TICKERS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'NFLX'];

/** Parse a displayed money/number string like "$10,000.00", "-$12.34", "(1.5%)" into a number. */
export function parseNumber(text: string | null | undefined): number {
  if (!text) return NaN;
  const negative = /-|−|\(/.test(text);
  const cleaned = text.replace(/[^0-9.]/g, '');
  if (!cleaned) return NaN;
  const n = parseFloat(cleaned);
  return negative ? -n : n;
}

export async function resetState(request: APIRequestContext): Promise<void> {
  const res = await request.post('/api/reset');
  expect(res.status(), `POST /api/reset failed: ${await res.text()}`).toBe(200);
}

export async function apiBuy(request: APIRequestContext, ticker: string, quantity: number) {
  const res = await request.post('/api/portfolio/trade', { data: { ticker, quantity, side: 'buy' } });
  expect(res.status(), `API buy failed: ${await res.text()}`).toBe(200);
  return res.json();
}

export async function apiPortfolio(request: APIRequestContext) {
  const res = await request.get('/api/portfolio');
  expect(res.status()).toBe(200);
  return res.json();
}

export async function readNumber(page: Page, testId: string): Promise<number> {
  return parseNumber(await page.getByTestId(testId).textContent());
}

/** Navigate to the app and wait until the SSE connection is up. */
export async function openApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.getByTestId('watchlist')).toBeVisible();
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected', { timeout: 15_000 });
}

/** Wait until a watchlist row shows a numeric price; returns it. */
export async function waitForPrice(page: Page, ticker: string): Promise<number> {
  let value = NaN;
  await expect
    .poll(
      async () => {
        value = parseNumber(await page.getByTestId(`watchlist-price-${ticker}`).textContent());
        return Number.isFinite(value) && value > 0;
      },
      { message: `price for ${ticker} never appeared`, timeout: 15_000 },
    )
    .toBe(true);
  return value;
}

export async function trade(page: Page, ticker: string, qty: string, side: 'buy' | 'sell') {
  await page.getByTestId('trade-ticker').fill(ticker);
  await page.getByTestId('trade-quantity').fill(qty);
  await page.getByTestId(side === 'buy' ? 'trade-buy' : 'trade-sell').click();
}

/**
 * Test object: every test starts from a fresh backend state (contract §9).
 * Implemented as an auto fixture, NOT a module-level test.beforeEach: a hook
 * registered in this shared module only attaches to the first spec file that
 * imports it in each worker (module cache), so later files would skip reset.
 */
export const test = base.extend<{ resetBackend: void }>({
  resetBackend: [
    async ({ request }, use) => {
      await resetState(request);
      await use();
    },
    { auto: true },
  ],
});

export { expect };

import type { Page } from '@playwright/test';
import { test, expect, openApp, apiPortfolio } from './helpers';

async function sendChat(page: Page, text: string) {
  await page.getByTestId('chat-input').fill(text);
  await page.getByTestId('chat-send').click();
}

const messages = (page: Page, role: 'user' | 'assistant') =>
  page.getByTestId('chat-panel').locator(`[data-testid="chat-message"][data-role="${role}"]`);

test.describe('AI chat (LLM_MOCK=true)', () => {
  test('buy 1 AAPL: response, executed chip and new position', async ({ page, request }) => {
    await openApp(page);
    await expect(page.getByTestId('chat-panel')).toBeVisible();
    await sendChat(page, 'buy 1 AAPL');

    await expect(messages(page, 'user').last()).toContainText('buy 1 AAPL');
    await expect(messages(page, 'assistant').last()).toContainText(/Buying 1 shares of AAPL\./i, { timeout: 15_000 });
    const chip = page.getByTestId('chat-action').last();
    await expect(chip).toHaveAttribute('data-status', 'executed');
    await expect(chip).toContainText('AAPL');
    await expect(page.getByTestId('chat-loading')).toHaveCount(0);

    await expect(page.getByTestId('position-row-AAPL')).toBeVisible();
    const pf = await apiPortfolio(request);
    expect(pf.positions.map((p: { ticker: string }) => p.ticker)).toContain('AAPL');
  });

  test('buy 100000 AAPL: failed chip with error, no position', async ({ page, request }) => {
    await openApp(page);
    await sendChat(page, 'buy 100000 AAPL');

    await expect(messages(page, 'assistant').last()).toContainText(/Buying 100000 shares of AAPL/i, { timeout: 15_000 });
    const chip = page.getByTestId('chat-action').last();
    await expect(chip).toHaveAttribute('data-status', 'failed');
    await expect(chip).toContainText(/insufficient cash/i);
    await expect(page.getByTestId('position-row-AAPL')).toHaveCount(0);
    expect((await apiPortfolio(request)).positions).toHaveLength(0);
  });

  test('add PYPL via chat updates the watchlist', async ({ page }) => {
    await openApp(page);
    await sendChat(page, 'add PYPL');
    await expect(messages(page, 'assistant').last()).toContainText(/Adding PYPL to your watchlist\./i, { timeout: 15_000 });
    await expect(page.getByTestId('chat-action').last()).toHaveAttribute('data-status', 'executed');
    await expect(page.getByTestId('watchlist-row-PYPL')).toBeVisible();
  });

  test('chat history reloads after page refresh', async ({ page }) => {
    await openApp(page);
    await sendChat(page, 'hello there');
    await expect(messages(page, 'assistant').last()).toContainText(/mock mode/i, { timeout: 15_000 });
    await page.reload();
    await expect(messages(page, 'user').last()).toContainText('hello there');
    await expect(messages(page, 'assistant').last()).toContainText(/mock mode/i);
  });
});

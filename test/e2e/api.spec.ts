/** API-level contract checks (planning/API_CONTRACT.md §4-§6). No browser. */
import type { APIResponse } from '@playwright/test';
import { test, expect, DEFAULT_TICKERS } from './helpers';

/* eslint-disable @typescript-eslint/no-explicit-any */

function expectPortfolioShape(pf: any) {
  for (const k of ['cash_balance', 'total_value', 'positions_value', 'unrealized_pnl']) {
    expect(typeof pf[k], `Portfolio.${k}`).toBe('number');
  }
  expect(Array.isArray(pf.positions)).toBe(true);
  for (const p of pf.positions) {
    expect(typeof p.ticker).toBe('string');
    for (const k of ['quantity', 'avg_cost', 'current_price', 'market_value', 'unrealized_pnl', 'unrealized_pnl_pct']) {
      expect(typeof p[k], `Position.${k}`).toBe('number');
    }
  }
}

async function expectError(res: APIResponse, status: number, pattern?: RegExp) {
  const body = await res.json().catch(() => null);
  expect(res.status(), `body: ${JSON.stringify(body)}`).toBe(status);
  expect(body && typeof body.error, `error body: ${JSON.stringify(body)}`).toBe('string');
  if (pattern) expect(body.error).toMatch(pattern);
}

const tradeReq = (ticker: string, quantity: unknown, side: string) => ({ data: { ticker, quantity, side } });

test.describe('REST API contract', () => {
  test('GET /api/health', async ({ request }) => {
    const res = await request.get('/api/health');
    expect(res.status()).toBe(200);
    expect(await res.json()).toEqual({ status: 'ok' });
  });

  test('POST /api/reset returns a fresh Portfolio', async ({ request }) => {
    await request.post('/api/portfolio/trade', tradeReq('AAPL', 1, 'buy'));
    const res = await request.post('/api/reset');
    expect(res.status()).toBe(200);
    const pf = await res.json();
    expectPortfolioShape(pf);
    expect(pf.cash_balance).toBe(10000);
    expect(pf.total_value).toBe(10000);
    expect(pf.positions).toEqual([]);
  });

  test('GET /api/watchlist returns the default WatchlistItems in order', async ({ request }) => {
    const items = await (await request.get('/api/watchlist')).json();
    expect(items.map((i: any) => i.ticker)).toEqual(DEFAULT_TICKERS);
    for (const i of items) {
      for (const k of ['price', 'previous_price', 'open_price', 'change_percent']) {
        expect(i[k] === null || typeof i[k] === 'number', `WatchlistItem.${k}=${i[k]}`).toBe(true);
      }
      expect(typeof i.added_at).toBe('string');
    }
  });

  test('POST /api/watchlist: 201 new, 200 duplicate, normalises, rejects invalid', async ({ request }) => {
    const created = await request.post('/api/watchlist', { data: { ticker: ' pypl ' } });
    expect(created.status()).toBe(201);
    expect((await created.json()).ticker).toBe('PYPL');
    const dup = await request.post('/api/watchlist', { data: { ticker: 'PYPL' } });
    expect(dup.status()).toBe(200);
    expect((await dup.json()).ticker).toBe('PYPL');

    await expectError(await request.post('/api/watchlist', { data: { ticker: '123!' } }), 400, /invalid ticker/i);
    // Missing field: FastAPI's 422 must be reshaped to 400 {error}.
    await expectError(await request.post('/api/watchlist', { data: {} }), 400);
  });

  test('DELETE /api/watchlist/{ticker}: 200 then 404', async ({ request }) => {
    const ok = await request.delete('/api/watchlist/NFLX');
    expect(ok.status()).toBe(200);
    expect(await ok.json()).toEqual({ ticker: 'NFLX' });
    await expectError(await request.delete('/api/watchlist/NFLX'), 404);
  });

  test('removing a watched ticker with an open position keeps its price flowing', async ({ request }) => {
    await request.post('/api/portfolio/trade', tradeReq('AAPL', 1, 'buy'));
    expect((await request.delete('/api/watchlist/AAPL')).status()).toBe(200);
    const pf = await (await request.get('/api/portfolio')).json();
    expect(pf.positions[0].ticker).toBe('AAPL');
    expect(pf.positions[0].current_price).toBeGreaterThan(0);
    const sell = await request.post('/api/portfolio/trade', tradeReq('AAPL', 1, 'sell'));
    expect(sell.status()).toBe(200);
  });

  test('POST /api/portfolio/trade: success shape', async ({ request }) => {
    const res = await request.post('/api/portfolio/trade', tradeReq('AAPL', 1.5, 'buy'));
    expect(res.status()).toBe(200);
    const body = await res.json();
    const t = body.trade;
    expect(typeof t.id).toBe('string');
    expect(t).toMatchObject({ ticker: 'AAPL', side: 'buy' });
    expect(t.quantity).toBeCloseTo(1.5, 4);
    expect(t.price).toBeGreaterThan(0);
    expect(typeof t.executed_at).toBe('string');
    expectPortfolioShape(body.portfolio);
    expect(body.portfolio.cash_balance).toBeCloseTo(10000 - 1.5 * t.price, 1);
    expect(body.portfolio.positions[0].ticker).toBe('AAPL');
    expect(body.portfolio.positions[0].avg_cost).toBeCloseTo(t.price, 2);
  });

  test('POST /api/portfolio/trade: validation errors are 400 {error}', async ({ request }) => {
    await expectError(await request.post('/api/portfolio/trade', tradeReq('AAPL', 100000, 'buy')), 400, /insufficient cash/i);
    await expectError(await request.post('/api/portfolio/trade', tradeReq('AAPL', 5, 'sell')), 400, /insufficient shares/i);
    await expectError(await request.post('/api/portfolio/trade', tradeReq('AAPL', 0, 'buy')), 400);
    await expectError(await request.post('/api/portfolio/trade', tradeReq('AAPL', -1, 'buy')), 400);
    await expectError(await request.post('/api/portfolio/trade', tradeReq('AAPL', 1, 'hold')), 400);
    await expectError(await request.post('/api/portfolio/trade', tradeReq('!!', 1, 'buy')), 400, /invalid ticker/i);
    const pf = await (await request.get('/api/portfolio')).json();
    expect(pf.cash_balance).toBe(10000);
    expect(pf.positions).toEqual([]);
  });

  test('trading an untracked ticker adds it to the watchlist', async ({ request }) => {
    const res = await request.post('/api/portfolio/trade', tradeReq('AMD', 1, 'buy'));
    expect(res.status(), await res.text()).toBe(200);
    const items = await (await request.get('/api/watchlist')).json();
    expect(items.map((i: any) => i.ticker)).toContain('AMD');
  });

  test('GET /api/portfolio/history returns ascending snapshots', async ({ request }) => {
    await request.post('/api/portfolio/trade', tradeReq('AAPL', 1, 'buy'));
    const hist = await (await request.get('/api/portfolio/history')).json();
    expect(hist.length).toBeGreaterThanOrEqual(2);
    for (const s of hist) {
      expect(typeof s.total_value).toBe('number');
      expect(typeof s.recorded_at).toBe('string');
    }
    const times = hist.map((s: any) => s.recorded_at);
    expect([...times].sort()).toEqual(times);
  });

  test('POST /api/chat (mock) trade actions and history persistence', async ({ request }) => {
    const res = await request.post('/api/chat', { data: { message: 'buy 1 AAPL' } });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.message.role).toBe('assistant');
    expect(body.message.content).toContain('Buying 1 shares of AAPL.');
    expect(typeof body.message.id).toBe('string');
    expect(typeof body.message.created_at).toBe('string');
    expect(body.actions).toHaveLength(1);
    expect(body.actions[0]).toMatchObject({ type: 'trade', ticker: 'AAPL', side: 'buy', quantity: 1, status: 'executed' });
    expect(body.actions[0].price).toBeGreaterThan(0);

    const failed = await (await request.post('/api/chat', { data: { message: 'buy 100000 AAPL' } })).json();
    expect(failed.actions[0].status).toBe('failed');
    expect(failed.actions[0].error).toMatch(/insufficient cash/i);
    expect(failed.message.content).toMatch(/insufficient cash/i); // templated failure line appended

    const hist = await (await request.get('/api/chat/history')).json();
    expect(hist.map((m: any) => m.role)).toEqual(['user', 'assistant', 'user', 'assistant']);
    expect(hist[0].actions).toBeNull();
    expect(Array.isArray(hist[1].actions)).toBe(true);
  });

  test('POST /api/chat (mock) fallback and watchlist actions', async ({ request }) => {
    const hi = await (await request.post('/api/chat', { data: { message: 'hello' } })).json();
    expect(hi.message.content).toMatch(/mock mode/i);
    expect(hi.actions).toEqual([]);
    const add = await (await request.post('/api/chat', { data: { message: 'add PYPL' } })).json();
    expect(add.actions[0]).toMatchObject({ type: 'watchlist', ticker: 'PYPL', action: 'add', status: 'executed' });
    const rm = await (await request.post('/api/chat', { data: { message: 'remove PYPL' } })).json();
    expect(rm.actions[0]).toMatchObject({ type: 'watchlist', ticker: 'PYPL', action: 'remove', status: 'executed' });
  });

  test('GET /api/stream/prices emits SSE with all tickers and open_price', async ({ baseURL }) => {
    const ctrl = new AbortController();
    const res = await fetch(`${baseURL}/api/stream/prices`, { signal: ctrl.signal });
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let payload: any = null;
    const deadline = Date.now() + 10_000;
    try {
      while (!payload && Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const m = buf.match(/^data: (.+)$/m);
        if (m) payload = JSON.parse(m[1]);
      }
    } finally {
      ctrl.abort();
    }
    expect(payload, 'no SSE data event received').not.toBeNull();
    for (const t of DEFAULT_TICKERS) {
      const u = payload[t];
      expect(u, `SSE payload missing ${t}`).toBeTruthy();
      for (const k of ['price', 'previous_price', 'open_price', 'timestamp', 'change', 'change_percent']) {
        expect(typeof u[k], `SSE ${t}.${k}`).toBe('number');
      }
      expect(['up', 'down', 'flat']).toContain(u.direction);
      expect(u.timestamp).toBeLessThan(1e11); // Unix seconds, not ms
    }
  });
});

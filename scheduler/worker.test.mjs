import assert from 'node:assert/strict';
import { test } from 'node:test';
import worker from './worker.js';

test('scheduled pass calls only the configured collector with its bearer secret', async t => {
  let pending;
  t.mock.method(console, 'log', () => {});
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, 'https://example.com/internal/collect');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers.Authorization, 'Bearer test-secret');
    return Response.json({ processed: 1, busy: false });
  });
  await worker.scheduled({}, { SEMBLANCE_URL: 'https://example.com', COLLECTOR_SECRET: 'test-secret' },
    { waitUntil(promise) { pending = promise; } });
  await pending;
});

test('failed collector request rejects so the scheduler records a failed invocation', async t => {
  let pending;
  t.mock.method(globalThis, 'fetch', async () => new Response('Unavailable', {status: 503}));
  await worker.scheduled({}, { SEMBLANCE_URL: 'https://example.com', COLLECTOR_SECRET: 'test-secret' },
    { waitUntil(promise) { pending = promise; } });
  await assert.rejects(pending, /HTTP 503/);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { getBenchmarkNotice } from './chat-model-picker';

test('live BenchLM rankings do not show a fallback notice', () => {
  assert.equal(getBenchmarkNotice({ source: 'benchlm', stale: false }), null);
});

test('catalog and stale rankings show the service message in the picker', () => {
  assert.equal(
    getBenchmarkNotice({
      source: 'catalog-fallback',
      stale: false,
      message: 'Add a BenchLM key in Preferences to load current rankings.',
    }),
    'Add a BenchLM key in Preferences to load current rankings.',
  );
  assert.equal(
    getBenchmarkNotice({
      source: 'benchlm',
      stale: true,
      message: 'BenchLM could not be reached; showing the last successful rankings.',
    }),
    'BenchLM could not be reached; showing the last successful rankings.',
  );
});

test('request failures without a response clearly explain that badges are omitted', () => {
  assert.equal(
    getBenchmarkNotice(undefined, true),
    'BenchLM rankings are unavailable. Model list is shown without ranking badges.',
  );
});

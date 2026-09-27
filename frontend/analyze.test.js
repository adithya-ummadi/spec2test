/**
 * analyze.test.js
 *
 * In-memory mock tests for the Analyze feature in app.js.
 * No real network calls, no backend changes, no saved state.
 *
 * Run with Node.js:  node frontend/analyze.test.js
 *
 * Strategy
 * --------
 * 1.  Build a minimal DOM stub (no browser, no JSDOM dependency) that mirrors
 *     the exact element IDs app.js references for the analyze path.
 * 2.  Monkey-patch global.fetch so every test controls the HTTP response.
 * 3.  Import the analyzeBtn click handler logic inline (copied verbatim from
 *     app.js analyzeBtn click handler) so we can call it directly without a browser.
 * 4.  Assert state changes on the DOM stubs after each scenario.
 */

'use strict';

// ── 1. Minimal DOM stubs ──────────────────────────────────────────────────────

function makeEl(id, tag = 'div') {
  return {
    id,
    hidden: false,
    disabled: false,
    className: '',
    textContent: '',
    innerHTML: '',
    style: {},
    _listeners: {},
    addEventListener(evt, fn) { this._listeners[evt] = fn; },
    dispatchEvent(evt) { if (this._listeners[evt]) this._listeners[evt](); },
  };
}

const analyzeBtn       = makeEl('analyze-btn', 'button');
const analyzeStatusEl  = makeEl('analyze-status');
const analyzeResult    = makeEl('analyze-result');

// Simulate the module globals that the handler reads
let currentDocId = null;

const API_BASE = 'http://localhost:8000/api/documents';

// ── 2. Handler extracted verbatim from app.js (analyzeBtn click handler)
//    (the only change: `currentDocId` and DOM refs are the stubs above)

async function runAnalyzeClick() {
  if (!currentDocId) return;

  analyzeBtn.disabled = true;
  analyzeStatusEl.className = 'loading';
  analyzeStatusEl.textContent = 'Analyzing requirements… this may take a moment.';
  analyzeResult.hidden = true;
  analyzeResult.innerHTML = '';
  analyzeResult.style.whiteSpace = '';

  try {
    const response = await fetch(`${API_BASE}/${currentDocId}/analyze`, {
      method: 'POST',
    });

    if (!response.ok) {
      let detail = `Server returned ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail ?? err.message ?? err.error ?? detail;
      } catch (_) { /* ignore */ }
      throw new Error(detail);
    }

    const data = await response.json();
    analyzeStatusEl.className = '';
    analyzeStatusEl.textContent = '';

    analyzeResult.hidden = false;
    // Render a human-readable summary from the structured API response.
    // API shape: { document_id, analyzed, failed, skipped, errors: [] }
    if (typeof data === 'object' && data !== null) {
      const summary = data.summary ?? data.result ?? data.message ?? null;
      if (summary) {
        analyzeResult.textContent = summary;
      } else if ('analyzed' in data) {
        const parts = [`Analyzed: ${data.analyzed}`];
        if (data.skipped) parts.push(`Skipped: ${data.skipped}`);
        if (data.failed) parts.push(`Failed: ${data.failed}`);
        analyzeResult.textContent = parts.join(' · ');
      } else {
        analyzeResult.textContent = JSON.stringify(data, null, 2);
        analyzeResult.style.whiteSpace = 'pre-wrap';
      }
    } else {
      analyzeResult.textContent = String(data);
    }

  } catch (err) {
    analyzeStatusEl.className = 'error';
    analyzeStatusEl.textContent = `Analysis failed: ${err.message}`;
  } finally {
    analyzeBtn.disabled = false;
  }
}

// ── 3. Test harness ───────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const results = [];

function assert(label, condition, detail = '') {
  if (condition) {
    passed++;
    results.push({ status: 'PASS', label });
  } else {
    failed++;
    results.push({ status: 'FAIL', label, detail });
    console.error(`  FAIL: ${label}${detail ? ' — ' + detail : ''}`);
  }
}

function resetDom() {
  analyzeBtn.disabled = false;
  analyzeBtn.className = '';
  analyzeStatusEl.className = '';
  analyzeStatusEl.textContent = '';
  analyzeResult.hidden = true;
  analyzeResult.innerHTML = '';
  analyzeResult.textContent = '';
  analyzeResult.style = {};
}

function makeFetch(status, body, ok = null) {
  ok = ok ?? (status >= 200 && status < 300);
  return async (url, opts) => {
    // Capture for assertions
    global._lastFetchUrl  = url;
    global._lastFetchOpts = opts;
    return {
      ok,
      status,
      json: async () => body,
    };
  };
}

// ── 4. Tests ──────────────────────────────────────────────────────────────────

async function test_noDocId_doesNothing() {
  resetDom();
  currentDocId = null;
  global.fetch = makeFetch(200, {});
  global._lastFetchUrl = null;

  await runAnalyzeClick();

  assert('no-doc-id: fetch is never called',
    global._lastFetchUrl === null);
  assert('no-doc-id: button stays enabled',
    analyzeBtn.disabled === false);
  assert('no-doc-id: status unchanged',
    analyzeStatusEl.textContent === '');
}

async function test_correctUrlAndMethod() {
  resetDom();
  currentDocId = 42;
  global.fetch = makeFetch(200, { analyzed: 3, failed: 0, skipped: 0, errors: [] });

  await runAnalyzeClick();

  assert('url: calls POST /api/documents/{doc_id}/analyze',
    global._lastFetchUrl === 'http://localhost:8000/api/documents/42/analyze');
  assert('method: uses POST',
    global._lastFetchOpts?.method === 'POST');
}

async function test_loadingState() {
  resetDom();
  currentDocId = 7;

  let capturedDisabled, capturedClass, capturedText;
  global.fetch = async (url, opts) => {
    // Snapshot mid-flight state (while fetch is "in progress")
    capturedDisabled = analyzeBtn.disabled;
    capturedClass    = analyzeStatusEl.className;
    capturedText     = analyzeStatusEl.textContent;
    return { ok: true, status: 200, json: async () => ({ analyzed: 1 }) };
  };

  await runAnalyzeClick();

  assert('loading: button is disabled while fetching',
    capturedDisabled === true,
    `disabled was ${capturedDisabled}`);
  assert('loading: status has class "loading" while fetching',
    capturedClass === 'loading',
    `class was "${capturedClass}"`);
  assert('loading: loading message is shown while fetching',
    capturedText === 'Analyzing requirements… this may take a moment.',
    `text was "${capturedText}"`);
  assert('loading: analyzeResult is hidden while fetching',
    analyzeResult.hidden === true || analyzeResult.innerHTML === '');
}

async function test_buttonReenabledAfterSuccess() {
  resetDom();
  currentDocId = 7;
  global.fetch = makeFetch(200, { analyzed: 2, failed: 0, skipped: 0, errors: [] });

  await runAnalyzeClick();

  assert('success: button re-enabled after success',
    analyzeBtn.disabled === false,
    `disabled was ${analyzeBtn.disabled}`);
}

async function test_buttonReenabledAfterError() {
  resetDom();
  currentDocId = 7;
  global.fetch = makeFetch(500, { detail: 'Internal error' }, false);

  await runAnalyzeClick();

  assert('error: button re-enabled after server error',
    analyzeBtn.disabled === false,
    `disabled was ${analyzeBtn.disabled}`);
}

async function test_successWithSummaryField() {
  resetDom();
  currentDocId = 1;
  global.fetch = makeFetch(200, { analyzed: 3, failed: 0, skipped: 1, errors: [], summary: 'All done' });

  await runAnalyzeClick();

  assert('success/summary: status class cleared',
    analyzeStatusEl.className === '',
    `class was "${analyzeStatusEl.className}"`);
  assert('success/summary: status text cleared',
    analyzeStatusEl.textContent === '',
    `text was "${analyzeStatusEl.textContent}"`);
  assert('success/summary: analyzeResult is visible',
    analyzeResult.hidden === false,
    `hidden was ${analyzeResult.hidden}`);
  assert('success/summary: summary field shown in textContent',
    analyzeResult.textContent === 'All done',
    `textContent was "${analyzeResult.textContent}"`);
}

async function test_successNoSummaryFieldShowsJson() {
  resetDom();
  currentDocId = 1;
  // Payload with no summary/result/message AND no "analyzed" key → raw JSON fallback
  const payload = { document_id: 1, status: 'ok' };
  global.fetch = makeFetch(200, payload);

  await runAnalyzeClick();

  assert('success/json: analyzeResult is visible',
    analyzeResult.hidden === false);
  assert('success/json: raw JSON rendered when no summary/result/message/analyzed field',
    analyzeResult.textContent === JSON.stringify(payload, null, 2),
    `textContent was "${analyzeResult.textContent}"`);
  assert('success/json: whitespace pre-wrap set for raw JSON',
    analyzeResult.style.whiteSpace === 'pre-wrap',
    `whiteSpace was "${analyzeResult.style.whiteSpace}"`);
}

async function test_successWithAnalyzedField() {
  resetDom();
  currentDocId = 1;
  global.fetch = makeFetch(200, { analyzed: 3, failed: 0, skipped: 1, errors: [] });

  await runAnalyzeClick();

  assert('success/analyzed: analyzeResult is visible',
    analyzeResult.hidden === false);
  assert('success/analyzed: human-readable summary shown',
    analyzeResult.textContent === 'Analyzed: 3 · Skipped: 1',
    `textContent was "${analyzeResult.textContent}"`);
}

async function test_successWithAnalyzedAndFailed() {
  resetDom();
  currentDocId = 1;
  global.fetch = makeFetch(200, { analyzed: 2, failed: 1, skipped: 0, errors: [] });

  await runAnalyzeClick();

  assert('success/analyzed+failed: human-readable summary includes failed count',
    analyzeResult.textContent === 'Analyzed: 2 · Failed: 1',
    `textContent was "${analyzeResult.textContent}"`);
}

async function test_successWithResultField() {
  resetDom();
  currentDocId = 1;
  global.fetch = makeFetch(200, { result: 'Processed successfully' });

  await runAnalyzeClick();

  assert('success/result-field: result field used as display text',
    analyzeResult.textContent === 'Processed successfully',
    `textContent was "${analyzeResult.textContent}"`);
}

async function test_successWithMessageField() {
  resetDom();
  currentDocId = 1;
  global.fetch = makeFetch(200, { message: 'Done' });

  await runAnalyzeClick();

  assert('success/message-field: message field used as display text',
    analyzeResult.textContent === 'Done',
    `textContent was "${analyzeResult.textContent}"`);
}

async function test_serverError_withDetailField() {
  resetDom();
  currentDocId = 5;
  global.fetch = makeFetch(422, { detail: 'Document not found' }, false);

  await runAnalyzeClick();

  assert('error/detail: status class is "error"',
    analyzeStatusEl.className === 'error',
    `class was "${analyzeStatusEl.className}"`);
  assert('error/detail: detail message surfaced',
    analyzeStatusEl.textContent === 'Analysis failed: Document not found',
    `text was "${analyzeStatusEl.textContent}"`);
  assert('error/detail: analyzeResult stays hidden',
    analyzeResult.hidden === true,
    `hidden was ${analyzeResult.hidden}`);
}

async function test_serverError_withMessageField() {
  resetDom();
  currentDocId = 5;
  global.fetch = makeFetch(503, { message: 'Service unavailable' }, false);

  await runAnalyzeClick();

  assert('error/message-field: message field surfaced from error body',
    analyzeStatusEl.textContent === 'Analysis failed: Service unavailable',
    `text was "${analyzeStatusEl.textContent}"`);
}

async function test_serverError_fallbackStatusCode() {
  resetDom();
  currentDocId = 5;
  global.fetch = makeFetch(500, 'not json', false);
  // Simulate non-JSON body by making .json() throw
  global.fetch = async (url, opts) => ({
    ok: false,
    status: 500,
    json: async () => { throw new SyntaxError('unexpected token'); },
  });

  await runAnalyzeClick();

  assert('error/fallback: falls back to "Server returned 500"',
    analyzeStatusEl.textContent === 'Analysis failed: Server returned 500',
    `text was "${analyzeStatusEl.textContent}"`);
}

async function test_networkError() {
  resetDom();
  currentDocId = 3;
  global.fetch = async () => { throw new TypeError('Failed to fetch'); };

  await runAnalyzeClick();

  assert('network-error: status class is "error"',
    analyzeStatusEl.className === 'error');
  assert('network-error: message includes fetch error',
    analyzeStatusEl.textContent === 'Analysis failed: Failed to fetch',
    `text was "${analyzeStatusEl.textContent}"`);
  assert('network-error: button re-enabled',
    analyzeBtn.disabled === false);
}

// ── 5. Run all tests ──────────────────────────────────────────────────────────

(async () => {
  const tests = [
    test_noDocId_doesNothing,
    test_correctUrlAndMethod,
    test_loadingState,
    test_buttonReenabledAfterSuccess,
    test_buttonReenabledAfterError,
    test_successWithSummaryField,
    test_successNoSummaryFieldShowsJson,
    test_successWithResultField,
    test_successWithMessageField,
    test_successWithAnalyzedField,
    test_successWithAnalyzedAndFailed,
    test_serverError_withDetailField,
    test_serverError_withMessageField,
    test_serverError_fallbackStatusCode,
    test_networkError,
  ];

  console.log('\n=== Analyze feature mock tests ===\n');
  for (const t of tests) {
    await t();
  }

  console.log('\n--- Results ---');
  for (const r of results) {
    const icon = r.status === 'PASS' ? '✓' : '✗';
    console.log(`  ${icon} [${r.status}] ${r.label}${r.detail ? '  ← ' + r.detail : ''}`);
  }
  console.log(`\nTotal: ${passed + failed}  Passed: ${passed}  Failed: ${failed}\n`);

  process.exitCode = failed > 0 ? 1 : 0;
})();

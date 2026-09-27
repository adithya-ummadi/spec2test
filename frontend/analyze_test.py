"""
analyze_test.py
===============
In-memory mock tests for the Analyze feature in frontend/app.js.

Tests the exact handler logic extracted verbatim from app.js lines 486-533.
No real network calls, no backend changes, no saved state, no extra dependencies
(uses only the Python stdlib – asyncio + unittest).

Run:  python frontend/analyze_test.py
"""

import asyncio
import json
import unittest

# ── Minimal DOM element stub ──────────────────────────────────────────────────

class El:
    def __init__(self, id_):
        self.id       = id_
        self.hidden   = False
        self.disabled = False
        self.className = ''
        self.textContent = ''
        self.innerHTML   = ''
        self.style       = {}


# ── Shared state (mirrors app.js module globals) ──────────────────────────────

API_BASE = 'http://localhost:8000/api/documents'


# ── Handler extracted verbatim from app.js lines 486-533 ─────────────────────
# The only substitutions:
#   - JS `fetch(url, {method:'POST'})` → `await self._fetch(url, 'POST')`
#   - DOM refs → passed-in stubs
#   - `currentDocId` → `self._current_doc_id`

class AnalyzeHandler:
    """Thin Python wrapper around the JS click handler logic."""

    def __init__(self):
        self.analyze_btn      = El('analyze-btn')
        self.analyze_status   = El('analyze-status')
        self.analyze_result   = El('analyze-result')
        self._current_doc_id  = None
        self._fetch           = None          # injected per test
        self._last_fetch_url  = None
        self._last_fetch_opts = None

    def reset(self):
        self.analyze_btn.disabled      = False
        self.analyze_btn.className     = ''
        self.analyze_status.className  = ''
        self.analyze_status.textContent = ''
        self.analyze_result.hidden     = True
        self.analyze_result.innerHTML  = ''
        self.analyze_result.textContent = ''
        self.analyze_result.style      = {}
        self._last_fetch_url  = None
        self._last_fetch_opts = None

    async def click(self):
        """Verbatim translation of app.js analyzeBtn click handler."""
        analyzeBtn      = self.analyze_btn
        analyzeStatusEl = self.analyze_status
        analyzeResult   = self.analyze_result
        currentDocId    = self._current_doc_id

        if not currentDocId:
            return

        analyzeBtn.disabled = True
        analyzeStatusEl.className   = 'loading'
        analyzeStatusEl.textContent = 'Analyzing requirements… this may take a moment.'
        analyzeResult.hidden    = True
        analyzeResult.innerHTML = ''
        analyzeResult.style['whiteSpace'] = ''

        try:
            url  = f'{API_BASE}/{currentDocId}/analyze'
            opts = {'method': 'POST'}
            self._last_fetch_url  = url
            self._last_fetch_opts = opts
            response = await self._fetch(url, opts)

            if not response['ok']:
                detail = f"Server returned {response['status']}"
                try:
                    err    = await response['json']()
                    detail = err.get('detail') or err.get('message') or err.get('error') or detail
                except Exception:
                    pass
                raise Exception(detail)

            data = await response['json']()
            analyzeStatusEl.className   = ''
            analyzeStatusEl.textContent = ''

            analyzeResult.hidden = False
            if isinstance(data, dict) and data is not None:
                summary = data.get('summary') or data.get('result') or data.get('message') or None
                if summary:
                    analyzeResult.textContent = summary
                else:
                    analyzeResult.textContent = json.dumps(data, indent=2)
                    analyzeResult.style['whiteSpace'] = 'pre-wrap'
            else:
                analyzeResult.textContent = str(data)

        except Exception as err:
            analyzeStatusEl.className   = 'error'
            analyzeStatusEl.textContent = f'Analysis failed: {err}'
        finally:
            analyzeBtn.disabled = False


# ── Fetch mock helpers ────────────────────────────────────────────────────────

def make_fetch(status, body, ok=None):
    if ok is None:
        ok = 200 <= status < 300

    async def _json():
        return body

    async def fetch(url, opts):
        return {'ok': ok, 'status': status, 'json': _json}

    return fetch


def make_fetch_json_error(status):
    """Simulates a non-JSON error body (json() raises)."""
    async def _json():
        raise ValueError('unexpected token')

    async def fetch(url, opts):
        return {'ok': False, 'status': status, 'json': _json}

    return fetch


def make_fetch_network_error():
    async def fetch(url, opts):
        raise OSError('Failed to fetch')
    return fetch


# ── Test suite ────────────────────────────────────────────────────────────────

class TestAnalyzeFeature(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.h = AnalyzeHandler()

    # ── 1. No document selected ────────────────────────────────────────────────

    async def test_no_doc_id_does_nothing(self):
        self.h.reset()
        self.h._current_doc_id = None
        self.h._fetch = make_fetch(200, {})

        await self.h.click()

        self.assertIsNone(self.h._last_fetch_url,
            'fetch must NOT be called when currentDocId is None')
        self.assertFalse(self.h.analyze_btn.disabled,
            'button must stay enabled')
        self.assertEqual(self.h.analyze_status.textContent, '',
            'status must be unchanged')

    # ── 2. Correct URL and HTTP method ────────────────────────────────────────

    async def test_correct_url_and_method(self):
        self.h.reset()
        self.h._current_doc_id = 42
        self.h._fetch = make_fetch(200, {'analyzed': 3, 'failed': 0, 'skipped': 0, 'errors': []})

        await self.h.click()

        self.assertEqual(self.h._last_fetch_url,
            'http://localhost:8000/api/documents/42/analyze',
            'URL must match POST /api/documents/{doc_id}/analyze')
        self.assertEqual(self.h._last_fetch_opts.get('method'), 'POST',
            'HTTP method must be POST')

    # ── 3. Loading state while in-flight ─────────────────────────────────────

    async def test_loading_state_during_fetch(self):
        self.h.reset()
        self.h._current_doc_id = 7

        captured = {}

        async def fetch_spy(url, opts):
            # Capture mid-flight state
            captured['disabled'] = self.h.analyze_btn.disabled
            captured['class']    = self.h.analyze_status.className
            captured['text']     = self.h.analyze_status.textContent
            captured['hidden']   = self.h.analyze_result.hidden
            async def _json(): return {'analyzed': 1}
            return {'ok': True, 'status': 200, 'json': _json}

        self.h._fetch = fetch_spy
        await self.h.click()

        self.assertTrue(captured['disabled'],
            'button must be disabled while fetch is in progress')
        self.assertEqual(captured['class'], 'loading',
            'status className must be "loading" while fetching')
        self.assertEqual(captured['text'],
            'Analyzing requirements… this may take a moment.',
            'loading message must be shown')
        self.assertTrue(captured['hidden'],
            'analyzeResult must be hidden while fetching')

    # ── 4. Button re-enabled after success ────────────────────────────────────

    async def test_button_reenabled_after_success(self):
        self.h.reset()
        self.h._current_doc_id = 7
        self.h._fetch = make_fetch(200, {'analyzed': 2, 'failed': 0, 'skipped': 0, 'errors': []})

        await self.h.click()

        self.assertFalse(self.h.analyze_btn.disabled,
            'button must be re-enabled after a successful response')

    # ── 5. Button re-enabled after server error ───────────────────────────────

    async def test_button_reenabled_after_error(self):
        self.h.reset()
        self.h._current_doc_id = 7
        self.h._fetch = make_fetch(500, {'detail': 'Internal error'}, ok=False)

        await self.h.click()

        self.assertFalse(self.h.analyze_btn.disabled,
            'button must be re-enabled after a server error')

    # ── 6. Success: `summary` field is displayed ──────────────────────────────

    async def test_success_summary_field(self):
        self.h.reset()
        self.h._current_doc_id = 1
        self.h._fetch = make_fetch(200, {
            'analyzed': 3, 'failed': 0, 'skipped': 1, 'errors': [], 'summary': 'All done'
        })

        await self.h.click()

        self.assertEqual(self.h.analyze_status.className, '',
            'status className must be cleared on success')
        self.assertEqual(self.h.analyze_status.textContent, '',
            'status text must be cleared on success')
        self.assertFalse(self.h.analyze_result.hidden,
            'analyzeResult must be visible')
        self.assertEqual(self.h.analyze_result.textContent, 'All done',
            'summary field must be the displayed text')

    # ── 7. Success: no summary/result/message → raw JSON ─────────────────────

    async def test_success_raw_json_fallback(self):
        self.h.reset()
        self.h._current_doc_id = 1
        payload = {'analyzed': 3, 'failed': 0, 'skipped': 1, 'errors': []}
        self.h._fetch = make_fetch(200, payload)

        await self.h.click()

        self.assertFalse(self.h.analyze_result.hidden,
            'analyzeResult must be visible')
        self.assertEqual(self.h.analyze_result.textContent,
            json.dumps(payload, indent=2),
            'raw JSON must be rendered when no summary/result/message key exists')
        self.assertEqual(self.h.analyze_result.style.get('whiteSpace'), 'pre-wrap',
            'whiteSpace must be set to pre-wrap for raw JSON')

    # ── 8. Success: `result` field is preferred over raw JSON ─────────────────

    async def test_success_result_field(self):
        self.h.reset()
        self.h._current_doc_id = 1
        self.h._fetch = make_fetch(200, {'result': 'Processed successfully'})

        await self.h.click()

        self.assertEqual(self.h.analyze_result.textContent, 'Processed successfully',
            '"result" field must be used as display text')

    # ── 9. Success: `message` field is preferred over raw JSON ───────────────

    async def test_success_message_field(self):
        self.h.reset()
        self.h._current_doc_id = 1
        self.h._fetch = make_fetch(200, {'message': 'Done'})

        await self.h.click()

        self.assertEqual(self.h.analyze_result.textContent, 'Done',
            '"message" field must be used as display text')

    # ── 10. Server error: `detail` field surfaced ─────────────────────────────

    async def test_server_error_detail_field(self):
        self.h.reset()
        self.h._current_doc_id = 5
        self.h._fetch = make_fetch(422, {'detail': 'Document not found'}, ok=False)

        await self.h.click()

        self.assertEqual(self.h.analyze_status.className, 'error',
            'status className must be "error"')
        self.assertEqual(self.h.analyze_status.textContent,
            'Analysis failed: Document not found',
            '"detail" from error body must be surfaced')
        self.assertTrue(self.h.analyze_result.hidden,
            'analyzeResult must stay hidden on error')

    # ── 11. Server error: `message` field surfaced ────────────────────────────

    async def test_server_error_message_field(self):
        self.h.reset()
        self.h._current_doc_id = 5
        self.h._fetch = make_fetch(503, {'message': 'Service unavailable'}, ok=False)

        await self.h.click()

        self.assertEqual(self.h.analyze_status.textContent,
            'Analysis failed: Service unavailable',
            '"message" from error body must be surfaced')

    # ── 12. Server error: non-JSON body → fallback to status code ────────────

    async def test_server_error_non_json_fallback(self):
        self.h.reset()
        self.h._current_doc_id = 5
        self.h._fetch = make_fetch_json_error(500)

        await self.h.click()

        self.assertEqual(self.h.analyze_status.textContent,
            'Analysis failed: Server returned 500',
            'must fall back to "Server returned <status>" when body is not JSON')

    # ── 13. Network failure (fetch itself throws) ─────────────────────────────

    async def test_network_error(self):
        self.h.reset()
        self.h._current_doc_id = 3
        self.h._fetch = make_fetch_network_error()

        await self.h.click()

        self.assertEqual(self.h.analyze_status.className, 'error',
            'status className must be "error" on network failure')
        self.assertIn('Failed to fetch', self.h.analyze_status.textContent,
            'network error message must be surfaced')
        self.assertFalse(self.h.analyze_btn.disabled,
            'button must be re-enabled even after network failure')

    # ── 14. BUG CHECK: analyzeResult not cleared between runs ─────────────────
    # If the user clicks Analyze twice and the second call fails,
    # the old success content from the first call must not still be visible.

    async def test_stale_result_cleared_on_new_click(self):
        """analyzeResult must be emptied at the start of every new click."""
        self.h.reset()
        self.h._current_doc_id = 1

        # First successful call
        self.h._fetch = make_fetch(200, {'summary': 'First run'})
        await self.h.click()
        self.assertEqual(self.h.analyze_result.textContent, 'First run')

        # Second call – server errors
        self.h._fetch = make_fetch(500, {'detail': 'Oops'}, ok=False)
        await self.h.click()

        # Handler sets analyzeResult.hidden=True and innerHTML='' at the start
        # and never sets hidden=False on error, so old content should not show
        self.assertTrue(self.h.analyze_result.hidden,
            'analyzeResult must be hidden when the second call fails')
        # innerHTML is cleared at start
        self.assertEqual(self.h.analyze_result.innerHTML, '',
            'analyzeResult.innerHTML must be emptied at the start of each click')

    # ── 15. BUG CHECK: priority of display-field selection ───────────────────
    # When the backend returns all three optional display fields,
    # `summary` must win over `result` and `message`.

    async def test_display_field_priority(self):
        self.h.reset()
        self.h._current_doc_id = 1
        self.h._fetch = make_fetch(200, {
            'summary': 'summary-value',
            'result':  'result-value',
            'message': 'message-value',
        })

        await self.h.click()

        self.assertEqual(self.h.analyze_result.textContent, 'summary-value',
            '"summary" must take priority over "result" and "message"')

    # ── 16. BUG CHECK: `analyzed` key in real backend response ───────────────
    # The real backend returns {document_id, analyzed, failed, skipped, errors}.
    # None of these match summary/result/message → raw JSON must be rendered
    # (currently the handler falls into the raw-JSON branch — good behavior).

    async def test_real_backend_payload_rendered_as_json(self):
        self.h.reset()
        self.h._current_doc_id = 99
        payload = {'document_id': 99, 'analyzed': 5, 'failed': 0, 'skipped': 0, 'errors': []}
        self.h._fetch = make_fetch(200, payload)

        await self.h.click()

        self.assertFalse(self.h.analyze_result.hidden,
            'analyzeResult must be visible for the real backend payload')
        self.assertEqual(self.h.analyze_result.textContent,
            json.dumps(payload, indent=2),
            'real backend payload must be pretty-printed as JSON since it has '
            'no summary/result/message key')
        self.assertEqual(self.h.analyze_result.style.get('whiteSpace'), 'pre-wrap',
            'pre-wrap style must be set for the raw-JSON path')

    # ── 17. BUG: stale whiteSpace style after raw-JSON → summary transition ──
    # First click hits raw-JSON path → sets style.whiteSpace = 'pre-wrap'.
    # Second click returns a summary string → whiteSpace must be reset to ''
    # otherwise the summary text renders in pre-wrap mode unintentionally.

    async def test_whitespace_style_reset_before_summary(self):
        """whiteSpace must be cleared at the start of each click (or before
        writing to textContent in the summary branch)."""
        self.h.reset()
        self.h._current_doc_id = 1

        # First call → raw-JSON path sets pre-wrap
        payload = {'analyzed': 2, 'failed': 0, 'skipped': 0, 'errors': []}
        self.h._fetch = make_fetch(200, payload)
        await self.h.click()
        self.assertEqual(self.h.analyze_result.style.get('whiteSpace'), 'pre-wrap',
            'pre-condition: first call must set pre-wrap')

        # Second call → summary path must clear pre-wrap
        self.h._fetch = make_fetch(200, {'summary': 'Done'})
        await self.h.click()

        self.assertEqual(self.h.analyze_result.style.get('whiteSpace', ''), '',
            'BUG: whiteSpace style is not cleared when switching from '
            'raw-JSON path to summary path — stale pre-wrap persists')


if __name__ == '__main__':
    unittest.main(verbosity=2)

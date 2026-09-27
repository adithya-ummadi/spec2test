'use strict';

const API_BASE     = 'http://localhost:8000/api/documents';
const REQ_API_BASE = 'http://localhost:8000/api/requirements';
const UPLOAD_URL   = `${API_BASE}/upload`;
const ALLOWED_TYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
]);
const ALLOWED_EXTS = /\.(pdf|docx|txt|md)$/i;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const form               = document.getElementById('upload-form');
const dropZone           = document.getElementById('drop-zone');
const fileInput          = document.getElementById('file-input');
const selectedFile       = document.getElementById('selected-file');
const selectedName       = document.getElementById('selected-name');
const clearBtn           = document.getElementById('clear-file');
const uploadBtn          = document.getElementById('upload-btn');
const statusEl           = document.getElementById('status');
const resultCard         = document.getElementById('result-card');
const resultFilename     = document.getElementById('result-filename');
const resultCount        = document.getElementById('result-count');
const viewReqsBtn        = document.getElementById('view-reqs-btn');
const requirementsSection = document.getElementById('requirements-section');
const reqStatus          = document.getElementById('req-status');
const reqList            = document.getElementById('req-list');
const analyzeBtn         = document.getElementById('analyze-btn');
const demoModeBtn        = document.getElementById('demo-mode-btn');
const analyzeStatusEl    = document.getElementById('analyze-status');
const analyzeResult      = document.getElementById('analyze-result');
const traceabilityBtn        = document.getElementById('traceability-btn');
const traceabilitySection    = document.getElementById('traceability-section');
const traceabilityStatus     = document.getElementById('traceability-status');
const traceabilityTableWrap  = document.getElementById('traceability-table-wrap');
const traceabilityTbody      = document.getElementById('traceability-tbody');
const traceabilityBackBtn    = document.getElementById('traceability-back-btn');
const reqDetail            = document.getElementById('req-detail');
const reqDetailStatus      = document.getElementById('req-detail-status');
const reqDetailBody        = document.getElementById('req-detail-body');
const reqDetailBadge       = document.getElementById('req-detail-badge');
const reqDetailText        = document.getElementById('req-detail-text');
const reqDetailFindings    = document.getElementById('req-detail-findings');
const reqDetailClose       = document.getElementById('req-detail-close');
const reqRefinementStatus  = document.getElementById('req-refinement-status');
const reqRefinementBody    = document.getElementById('req-refinement-body');
const refinementReqText    = document.getElementById('refinement-req-text');
const refinementCriteriaList = document.getElementById('refinement-criteria-list');
const refinementTestCases  = document.getElementById('refinement-test-cases');
const demoPanel            = document.getElementById('demo-panel');
const demoPanelClose       = document.getElementById('demo-panel-close');

// ── State ─────────────────────────────────────────────────────────────────────
let currentDocId  = null;
let selectedReqEl = null;

// ── Theme toggle ──────────────────────────────────────────────────────────────
const themeToggleBtn = document.getElementById('theme-toggle');

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  themeToggleBtn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  themeToggleBtn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
  themeToggleBtn.textContent = theme === 'dark' ? '☀' : '☾';
}

;(function initTheme() {
  const saved = localStorage.getItem('s2t-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved ?? (prefersDark ? 'dark' : 'light'));
})();

themeToggleBtn.addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  localStorage.setItem('s2t-theme', next);
  applyTheme(next);
});

// ── Nav / view switching ──────────────────────────────────────────────────────
const sidebarItems = document.querySelectorAll('.sidebar-item');
const views = document.querySelectorAll('.view');

function switchNav(viewName) {
  // Update sidebar active state
  sidebarItems.forEach((item) => {
    const isActive = item.dataset.view === viewName;
    item.classList.toggle('sidebar-item--active', isActive);
    item.setAttribute('aria-current', isActive ? 'page' : 'false');
  });

  // Show/hide views
  views.forEach((view) => {
    const isTarget = view.id === `view-${viewName}`;
    view.classList.toggle('view--hidden', !isTarget);
  });
}

sidebarItems.forEach((item) => {
  item.addEventListener('click', () => switchNav(item.dataset.view));
});

// ── Dismissible error helper ──────────────────────────────────────────────────
/**
 * Sets an element to display an error with a × dismiss button.
 * @param {HTMLElement} el   The status element to populate
 * @param {string}      msg  The error message text
 */
function setDismissibleError(el, msg) {
  el.className = 'error';

  // Text node for the message
  const msgNode = document.createTextNode(msg);

  // Dismiss button
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'error-dismiss';
  btn.setAttribute('aria-label', 'Dismiss error');
  btn.textContent = '×';
  btn.addEventListener('click', () => {
    el.className = '';
    el.textContent = '';
  });

  el.textContent = '';
  el.appendChild(msgNode);
  el.appendChild(btn);
}

// ── File selection ────────────────────────────────────────────────────────────
function isValidFile(file) {
  return ALLOWED_TYPES.has(file.type) || ALLOWED_EXTS.test(file.name);
}

function setFile(file) {
  if (!isValidFile(file)) {
    showError('Unsupported file type. Please upload a PDF, DOCX, TXT, or Markdown file.');
    return;
  }
  const dt = new DataTransfer();
  dt.items.add(file);
  fileInput.files = dt.files;

  selectedName.textContent = file.name;
  selectedFile.hidden = false;
  uploadBtn.disabled = false;
  clearStatus();
  resultCard.hidden = true;
}

function clearFile() {
  fileInput.value = '';
  selectedFile.hidden = true;
  uploadBtn.disabled = true;
  clearStatus();
  resultCard.hidden = true;
  requirementsSection.hidden = true;
  reqList.hidden = true;
  reqList.innerHTML = '';
  analyzeBtn.hidden = true;
  demoModeBtn.hidden = true;
  traceabilityBtn.hidden = true;
  analyzeStatusEl.className = '';
  analyzeStatusEl.textContent = '';
  analyzeResult.hidden = true;
  analyzeResult.innerHTML = '';
  closeReqDetail();
  closeDemoPanel();
  currentDocId = null;
}

// ── Drag-and-drop ─────────────────────────────────────────────────────────────
dropZone.addEventListener('click', (e) => {
  if (e.target.tagName !== 'LABEL') fileInput.click();
});

dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
  dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files.length) setFile(fileInput.files[0]);
});

clearBtn.addEventListener('click', clearFile);

// ── Status helpers ────────────────────────────────────────────────────────────
function showLoading(msg) {
  statusEl.className = 'loading';
  statusEl.textContent = msg;
}

function showError(msg) {
  setDismissibleError(statusEl, msg);
}

function clearStatus() {
  statusEl.className = '';
  statusEl.textContent = '';
}

// ── Upload ────────────────────────────────────────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();

  const file = fileInput.files[0];
  if (!file) return;

  resultCard.hidden = true;
  clearStatus();

  uploadBtn.disabled = true;
  showLoading('Uploading and processing… please wait.');

  const body = new FormData();
  body.append('file', file);

  try {
    const response = await fetch(UPLOAD_URL, {
      method: 'POST',
      body,
    });

    if (!response.ok) {
      let detail = `Server returned ${response.status}`;
      try {
        const err = await response.json();
        if (err.detail || err.message || err.error) {
          detail = err.detail ?? err.message ?? err.error;
        }
      } catch (_) { /* ignore JSON parse errors */ }
      throw new Error(detail);
    }

    const data = await response.json();

    clearStatus();
    currentDocId = data.id ?? data.doc_id ?? data.document_id ?? null;
    resultFilename.textContent = data.filename ?? '—';
    resultCount.textContent    = data.requirement_count ?? data.requirementCount ?? '—';
    resultCard.hidden = false;
    requirementsSection.hidden = true;
    reqList.hidden = true;
    reqList.innerHTML = '';
    analyzeBtn.hidden = true;
    demoModeBtn.hidden = true;
    analyzeStatusEl.className = '';
    analyzeStatusEl.textContent = '';
    analyzeResult.hidden = true;
    analyzeResult.innerHTML = '';

  } catch (err) {
    showError(`Upload failed: ${err.message}`);
  } finally {
    uploadBtn.disabled = false;
  }
});

// ── View requirements ─────────────────────────────────────────────────────────
viewReqsBtn.addEventListener('click', async () => {
  if (!currentDocId) return;

  // Auto-switch to Requirements view
  switchNav('requirements');

  requirementsSection.hidden = false;
  reqList.hidden = true;
  reqList.innerHTML = '';
  analyzeBtn.hidden = true;
  demoModeBtn.hidden = true;
  analyzeStatusEl.className = '';
  analyzeStatusEl.textContent = '';
  analyzeResult.hidden = true;
  analyzeResult.innerHTML = '';
  closeReqDetail();
  closeDemoPanel();

  reqStatus.className = 'loading';
  reqStatus.textContent = 'Loading requirements…';

  try {
    const response = await fetch(`${API_BASE}/${currentDocId}/requirements`);

    if (!response.ok) {
      let detail = `Server returned ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail ?? err.message ?? err.error ?? detail;
      } catch (_) { /* ignore */ }
      throw new Error(detail);
    }

    const requirements = await response.json();
    reqStatus.className = '';
    reqStatus.textContent = '';

    if (!Array.isArray(requirements) || requirements.length === 0) {
      reqStatus.className = 'info';
      reqStatus.textContent = 'No requirements found for this document.';
      return;
    }

    requirements.forEach((req) => {
      const li = document.createElement('li');
      li.className = 'req-item';

      const reqId = req.id ?? req.req_id ?? req.requirement_id ?? null;
      if (reqId !== null) {
        li.setAttribute('role', 'button');
        li.tabIndex = 0;
        li.dataset.reqId = reqId;
        li.addEventListener('click', () => openReqDetail(li, reqId));
        li.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openReqDetail(li, reqId); }
        });
      }

      const text = document.createElement('span');
      text.className = 'req-text';
      text.textContent = req.text ?? req.requirement ?? req.content ?? JSON.stringify(req);

      const badge = document.createElement('span');
      const status = (req.status ?? req.state ?? '').toLowerCase();
      badge.className = `req-badge req-badge--${status || 'unknown'}`;
      badge.textContent = req.status ?? req.state ?? 'unknown';

      li.appendChild(text);
      li.appendChild(badge);
      reqList.appendChild(li);
    });

    reqList.hidden = false;
    analyzeBtn.hidden = false;
    demoModeBtn.hidden = false;
    traceabilityBtn.hidden = false;

  } catch (err) {
    setDismissibleError(reqStatus, `Failed to load requirements: ${err.message}`);
  }
});

// ── Requirement detail ────────────────────────────────────────────────────────
function closeReqDetail() {
  reqDetail.hidden = true;
  reqDetailStatus.className = '';
  reqDetailStatus.textContent = '';
  reqDetailBody.hidden = true;
  reqDetailFindings.innerHTML = '';
  reqRefinementStatus.className = '';
  reqRefinementStatus.textContent = '';
  reqRefinementBody.hidden = true;
  refinementReqText.textContent = '';
  refinementCriteriaList.innerHTML = '';
  refinementTestCases.innerHTML = '';
  if (selectedReqEl) {
    selectedReqEl.classList.remove('req-item--selected');
    selectedReqEl = null;
  }
}

reqDetailClose.addEventListener('click', closeReqDetail);

async function openReqDetail(li, reqId) {
  if (selectedReqEl === li) { closeReqDetail(); return; }

  if (selectedReqEl) selectedReqEl.classList.remove('req-item--selected');
  selectedReqEl = li;
  li.classList.add('req-item--selected');

  // Close any open demo panel when a real detail is opened
  closeDemoPanel();

  reqDetail.hidden = false;
  reqDetailBody.hidden = true;
  reqRefinementBody.hidden = true;
  reqRefinementStatus.className = '';
  reqRefinementStatus.textContent = '';
  reqDetailFindings.innerHTML = '';
  reqDetailStatus.className = 'loading';
  reqDetailStatus.textContent = 'Loading…';

  try {
    const response = await fetch(`${REQ_API_BASE}/${reqId}`);

    if (!response.ok) {
      let detail = `Server returned ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail ?? err.message ?? err.error ?? detail;
      } catch (_) { /* ignore */ }
      throw new Error(detail);
    }

    const data = await response.json();
    reqDetailStatus.className = '';
    reqDetailStatus.textContent = '';

    const req = data.requirement ?? data;

    // Status badge
    const status = (req.status ?? req.state ?? '').toLowerCase();
    reqDetailBadge.className = `req-badge req-badge--${status || 'unknown'}`;
    reqDetailBadge.textContent = req.status ?? req.state ?? 'unknown';

    // Requirement text
    reqDetailText.textContent = req.text ?? req.content ?? '—';

    // Findings
    const findings = data.findings ?? data.analyses ?? data.results ?? null;
    if (!Array.isArray(findings) || findings.length === 0) {
      reqDetailFindings.innerHTML = '<p class="req-detail-empty">Not analyzed yet.</p>';
    } else {
      findings.forEach((f) => {
        const card = document.createElement('div');
        card.className = 'finding-card';

        const dl = document.createElement('dl');
        dl.className = 'finding-dl';

        function addRow(label, value) {
          if (value == null || value === '') return;
          const dt = document.createElement('dt');
          dt.textContent = label;
          const dd = document.createElement('dd');
          dd.textContent = value;
          dl.appendChild(dt);
          dl.appendChild(dd);
        }

        const confidence = f.confidence ?? f.score ?? null;
        addRow('Type', f.type ?? null);
        addRow('Confidence', confidence != null ? String(confidence) : null);
        addRow('Evidence', f.evidence ?? f.supporting_text ?? null);
        addRow('Missing information', f.missing_info ?? f.missing_information ?? f.gaps ?? null);
        addRow('Suggested clarification', f.suggested_clarification ?? f.clarification ?? f.suggestion ?? null);

        if (dl.children.length > 0) card.appendChild(dl);
        reqDetailFindings.appendChild(card);
      });
    }

    reqDetailBody.hidden = false;

    // ── Refinement results ──────────────────────────────────────────────────
    reqRefinementStatus.className = 'loading';
    reqRefinementStatus.textContent = 'Loading refinement results…';
    reqRefinementBody.hidden = true;

    try {
      const refResponse = await fetch(`${REQ_API_BASE}/${reqId}/refined`);

      if (!refResponse.ok) {
        if (refResponse.status === 404) {
          reqRefinementStatus.className = '';
          reqRefinementStatus.textContent = '';
          refinementReqText.textContent = '';
          refinementCriteriaList.innerHTML = '';
          refinementTestCases.innerHTML = '';
          reqRefinementBody.hidden = false;
          renderRefinementEmpty();
        } else {
          let detail = `Server returned ${refResponse.status}`;
          try {
            const err = await refResponse.json();
            detail = err.detail ?? err.message ?? err.error ?? detail;
          } catch (_) { /* ignore */ }
          throw new Error(detail);
        }
      } else {
        const refData = await refResponse.json();
        reqRefinementStatus.className = '';
        reqRefinementStatus.textContent = '';

        renderRefinementData(refData);
        reqRefinementBody.hidden = false;
      }
    } catch (refErr) {
      setDismissibleError(reqRefinementStatus, `Failed to load refinement results: ${refErr.message}`);
    }

  } catch (err) {
    setDismissibleError(reqDetailStatus, `Failed to load requirement: ${err.message}`);
  }
}

function renderRefinementEmpty() {
  refinementReqText.innerHTML = '<em class="req-detail-empty">Not refined yet.</em>';
  refinementCriteriaList.innerHTML = '<li class="req-detail-empty">None.</li>';
  refinementTestCases.innerHTML = '<p class="req-detail-empty">None.</p>';
}

function renderRefinementData(data) {
  const refinedObj = data.refined_requirement ?? null;
  const refinedText = (refinedObj && typeof refinedObj === 'object')
    ? (refinedObj.text ?? null)
    : (refinedObj ?? data.refined_text ?? null);
  if (refinedText) {
    refinementReqText.textContent = refinedText;
  } else {
    refinementReqText.innerHTML = '<em class="req-detail-empty">Not refined yet.</em>';
  }

  refinementCriteriaList.innerHTML = '';
  const acRaw = data.acceptance_criteria ?? data.criteria ?? [];
  const criteriaStrings = [];
  if (Array.isArray(acRaw)) {
    acRaw.forEach((item) => {
      if (typeof item === 'string') {
        criteriaStrings.push(item);
      } else if (item && Array.isArray(item.criteria)) {
        item.criteria.forEach((c) => criteriaStrings.push(c));
      } else if (item && (item.text || item.description)) {
        criteriaStrings.push(item.text ?? item.description);
      }
    });
  }
  if (criteriaStrings.length > 0) {
    criteriaStrings.forEach((c) => {
      const li = document.createElement('li');
      li.textContent = c;
      refinementCriteriaList.appendChild(li);
    });
  } else {
    refinementCriteriaList.innerHTML = '<li class="req-detail-empty">None.</li>';
  }

  refinementTestCases.innerHTML = '';
  const testCases = data.test_cases ?? data.tests ?? [];
  if (Array.isArray(testCases) && testCases.length > 0) {
    testCases.forEach((tc, i) => {
      const card = document.createElement('div');
      card.className = 'test-case-card';

      if (typeof tc === 'string') {
        card.textContent = tc;
      } else {
        const title = tc.title ?? tc.name ?? tc.summary ?? `Test case ${i + 1}`;
        const heading = document.createElement('p');
        heading.className = 'test-case-title';
        heading.textContent = title;
        card.appendChild(heading);

        const dl = document.createElement('dl');
        dl.className = 'finding-dl';

        function addTcRow(label, value) {
          if (value == null || value === '') return;
          const dt = document.createElement('dt');
          dt.textContent = label;
          const dd = document.createElement('dd');
          dd.textContent = typeof value === 'string' ? value : JSON.stringify(value);
          dl.appendChild(dt);
          dl.appendChild(dd);
        }

        addTcRow('Preconditions', tc.preconditions ?? tc.precondition ?? tc.given ?? null);
        addTcRow('Steps', tc.steps ?? (Array.isArray(tc.steps) ? tc.steps.join('; ') : null));
        addTcRow('Expected result', tc.expected_result ?? tc.then ?? tc.expected ?? null);
        addTcRow('Classification', tc.classification ?? null);

        if (dl.children.length > 0) card.appendChild(dl);
      }

      refinementTestCases.appendChild(card);
    });
  } else {
    refinementTestCases.innerHTML = '<p class="req-detail-empty">None.</p>';
  }
}

// ── Analyze requirements ──────────────────────────────────────────────────────
analyzeBtn.addEventListener('click', async () => {
  if (!currentDocId) return;

  // Auto-switch to Analysis view
  switchNav('analysis');

  analyzeBtn.disabled = true;
  analyzeStatusEl.className = 'loading';
  analyzeStatusEl.textContent = 'Analyzing requirements… this may take a moment.';
  analyzeResult.hidden = true;
  analyzeResult.innerHTML = '';
  analyzeResult.style.whiteSpace = '';

  // Also update analysis view body with a loading state
  const analysisViewBody = document.getElementById('analysis-view-body');
  if (analysisViewBody) {
    analysisViewBody.innerHTML = '';
  }

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

    // ── Detect partial-success: HTTP 200 but analyzed=0 and failed>0 ──────
    if (
      typeof data === 'object' && data !== null &&
      'analyzed' in data &&
      Number(data.analyzed) === 0 &&
      Number(data.failed ?? 0) > 0
    ) {
      const errMsgs = Array.isArray(data.errors) && data.errors.length > 0
        ? data.errors.join('; ')
        : `${data.failed} requirement(s) failed.`;
      setDismissibleError(analyzeStatusEl, `Analysis failed: ${errMsgs}`);
      renderRealAnalysisFailure(data);
      return;
    }

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
        if (data.failed)  parts.push(`Failed: ${data.failed}`);
        analyzeResult.textContent = parts.join(' · ');
      } else {
        analyzeResult.textContent = JSON.stringify(data, null, 2);
        analyzeResult.style.whiteSpace = 'pre-wrap';
      }
    } else {
      analyzeResult.textContent = String(data);
    }

    // Mirror result into analysis view
    if (analysisViewBody) {
      analysisViewBody.innerHTML = '';
      const mirror = analyzeResult.cloneNode(true);
      mirror.removeAttribute('hidden');
      mirror.style.whiteSpace = analyzeResult.style.whiteSpace;
      analysisViewBody.appendChild(mirror);
    }

  } catch (err) {
    // Network / service unavailable — show a clear error and suggest Demo mode
    setDismissibleError(analyzeStatusEl, `Analysis failed: ${err.message}`);
    renderAnalysisUnavailableHint();
  } finally {
    analyzeBtn.disabled = false;
  }
});

/** Creates a dismissible analysis-failure-box element. */
function makeFailureBox(titleText, bodyNodes) {
  const box = document.createElement('div');
  box.className = 'analysis-failure-box';

  // Dismiss (×) button — keyboard accessible
  const dismissBtn = document.createElement('button');
  dismissBtn.type = 'button';
  dismissBtn.className = 'analysis-failure-dismiss';
  dismissBtn.setAttribute('aria-label', 'Dismiss error');
  dismissBtn.textContent = '×';
  dismissBtn.addEventListener('click', () => {
    // Remove from wherever it lives (analyzeResult or analysisViewBody)
    const parent = box.parentElement;
    if (parent) parent.innerHTML = '';
  });
  box.appendChild(dismissBtn);

  const title = document.createElement('strong');
  title.textContent = titleText;
  box.appendChild(title);

  bodyNodes.forEach((n) => box.appendChild(n));
  return box;
}

/** Renders the partial-success failure card (HTTP 200, analyzed=0, failed>0). */
function renderRealAnalysisFailure(data) {
  analyzeResult.innerHTML = '';
  analyzeResult.hidden = false;

  const errMsgs = Array.isArray(data.errors) && data.errors.length > 0
    ? data.errors.join('; ')
    : `${data.failed} requirement(s) could not be analyzed.`;

  const detail = document.createElement('p');
  detail.textContent = errMsgs;

  const nodes = [detail];

  if (data.skipped) {
    const skip = document.createElement('p');
    skip.className = 'analysis-failure-meta';
    skip.textContent = `Skipped: ${data.skipped}`;
    nodes.push(skip);
  }

  const hint = document.createElement('p');
  hint.className = 'analysis-failure-hint';
  hint.textContent = 'Use "Demo mode" below to see illustrative example findings without calling the AI service.';
  nodes.push(hint);

  const box = makeFailureBox('✗ Real analysis failed', nodes);
  analyzeResult.appendChild(box);

  // Mirror into analysis view
  const analysisViewBody = document.getElementById('analysis-view-body');
  if (analysisViewBody) {
    analysisViewBody.innerHTML = '';
    // Clone gets its own dismiss wiring
    analysisViewBody.appendChild(makeFailureBox('✗ Real analysis failed', nodes.map((n) => n.cloneNode(true))));
  }
}

/** Renders a hint to use Demo mode when the service is completely unreachable. */
function renderAnalysisUnavailableHint() {
  analyzeResult.innerHTML = '';
  analyzeResult.hidden = false;

  const hint = document.createElement('p');
  hint.className = 'analysis-failure-hint';
  hint.textContent = 'The AI analysis service could not be reached. Use "Demo mode" below to see illustrative example findings without calling any API.';

  const box = makeFailureBox('✗ AI service unavailable', [hint]);
  analyzeResult.appendChild(box);

  // Mirror into analysis view
  const analysisViewBody = document.getElementById('analysis-view-body');
  if (analysisViewBody) {
    analysisViewBody.innerHTML = '';
    const hintClone = document.createElement('p');
    hintClone.className = 'analysis-failure-hint';
    hintClone.textContent = hint.textContent;
    analysisViewBody.appendChild(makeFailureBox('✗ AI service unavailable', [hintClone]));
  }
}

// ── Demo mode ─────────────────────────────────────────────────────────────────
/**
 * All demo content is generated purely from the loaded requirement text.
 * No API calls are made. All output is labelled "Demo — illustrative, not AI-verified."
 */

function closeDemoPanel() {
  if (demoPanel) demoPanel.hidden = true;
}

if (demoPanelClose) {
  demoPanelClose.addEventListener('click', closeDemoPanel);
}

demoModeBtn.addEventListener('click', () => {
  // Close the real req-detail panel so they don't overlap
  closeReqDetail();

  demoPanel.hidden = false;
  demoPanel.innerHTML = '';

  // ── Header ────────────────────────────────────────────────────────────────
  const panelHeader = document.createElement('div');
  panelHeader.className = 'demo-panel-header';

  const panelTitle = document.createElement('h3');
  panelTitle.className = 'demo-panel-title';
  panelTitle.textContent = 'Demo mode';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'req-detail-close';
  closeBtn.setAttribute('aria-label', 'Close demo panel');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', closeDemoPanel);

  panelHeader.appendChild(panelTitle);
  panelHeader.appendChild(closeBtn);
  demoPanel.appendChild(panelHeader);

  // ── Notice banner ──────────────────────────────────────────────────────────
  const banner = document.createElement('div');
  banner.className = 'demo-notice';
  banner.innerHTML =
    '<strong>⚠ Demo — illustrative, not AI-verified</strong>' +
    '<p>All content below is generated locally from your loaded requirement text. ' +
    'No AI endpoints are called. These findings, refined requirements, acceptance criteria, ' +
    'and test cases are <em>examples only</em> and have not been saved or submitted anywhere.</p>';
  demoPanel.appendChild(banner);

  // ── Resolve target requirement: selected one, or fall back to first in list ─
  const listItems = Array.from(reqList.querySelectorAll('.req-item'));
  const targetEl  = selectedReqEl ?? listItems[0] ?? null;
  if (!targetEl) return; // list is empty — nothing to show

  const reqText = targetEl.querySelector('.req-text')?.textContent ?? 'Requirement';
  const rawId   = targetEl.dataset.reqId;
  const reqId   = rawId ? `REQ-${String(rawId).padStart(3, '0')}` : 'REQ-001';
  const idx     = listItems.indexOf(targetEl);

  const section = buildDemoSection(reqId, reqText, idx >= 0 ? idx : 0);
  demoPanel.appendChild(section);
});

/**
 * Builds a full demo section for one requirement.
 * @param {string} reqId   Display ID label
 * @param {string} reqText The raw requirement text
 * @param {number} idx     Index used to vary templates
 */
function buildDemoSection(reqId, reqText, idx) {
  const wrap = document.createElement('div');
  wrap.className = 'demo-req-section';

  // ── Requirement heading ──────────────────────────────────────────────────
  const heading = document.createElement('h4');
  heading.className = 'demo-req-heading';
  heading.textContent = reqId;
  wrap.appendChild(heading);

  const reqPara = document.createElement('p');
  reqPara.className = 'demo-req-text';
  reqPara.textContent = reqText;
  wrap.appendChild(reqPara);

  // ── Findings ─────────────────────────────────────────────────────────────
  const findingsHeading = document.createElement('h5');
  findingsHeading.className = 'demo-sub-heading';
  findingsHeading.textContent = 'Findings (example)';
  wrap.appendChild(findingsHeading);

  const findings = buildDemoFindings(reqText, idx);
  findings.forEach((f) => {
    const card = document.createElement('div');
    card.className = 'demo-finding-card';

    const header = document.createElement('div');
    header.className = 'demo-finding-header';

    const typeEl = document.createElement('span');
    typeEl.className = 'demo-finding-type';
    typeEl.textContent = f.type;

    const confBadge = document.createElement('span');
    confBadge.className = `req-badge req-badge--conf-${f.confidence.toLowerCase()} demo-conf-badge`;
    confBadge.textContent = f.confidence;

    header.appendChild(typeEl);
    header.appendChild(confBadge);

    const dl = document.createElement('dl');
    dl.className = 'finding-dl';

    function addRow(label, value) {
      const dt = document.createElement('dt'); dt.textContent = label;
      const dd = document.createElement('dd'); dd.textContent = value;
      dl.appendChild(dt); dl.appendChild(dd);
    }
    addRow('Evidence (example)', f.evidence);
    addRow('Suggested clarification (example)', f.suggestion);

    card.appendChild(header);
    card.appendChild(dl);
    wrap.appendChild(card);
  });

  // ── Refined requirement ───────────────────────────────────────────────────
  const refHeading = document.createElement('h5');
  refHeading.className = 'demo-sub-heading';
  refHeading.textContent = 'Refined requirement (example)';
  wrap.appendChild(refHeading);

  const refBlock = document.createElement('div');
  refBlock.className = 'refinement-block';

  const refText = document.createElement('p');
  refText.className = 'refinement-text';
  refText.textContent = buildDemoRefinedReq(reqText, idx);
  refBlock.appendChild(refText);
  wrap.appendChild(refBlock);

  // ── Acceptance criteria ───────────────────────────────────────────────────
  const acHeading = document.createElement('h5');
  acHeading.className = 'demo-sub-heading';
  acHeading.textContent = 'Acceptance criteria (example)';
  wrap.appendChild(acHeading);

  const acBlock = document.createElement('div');
  acBlock.className = 'refinement-block';

  const acList = document.createElement('ul');
  acList.className = 'refinement-list';
  buildDemoAcceptanceCriteria(reqText, idx).forEach((c) => {
    const li = document.createElement('li');
    li.textContent = c;
    acList.appendChild(li);
  });
  acBlock.appendChild(acList);
  wrap.appendChild(acBlock);

  // ── Test cases ────────────────────────────────────────────────────────────
  const tcHeading = document.createElement('h5');
  tcHeading.className = 'demo-sub-heading';
  tcHeading.textContent = 'Test cases (example)';
  wrap.appendChild(tcHeading);

  buildDemoTestCases(reqText, idx).forEach((tc) => {
    const card = document.createElement('div');
    card.className = `test-case-card test-case-card--${tc.classification.toLowerCase()}`;

    const tcTitle = document.createElement('p');
    tcTitle.className = 'test-case-title';

    const classTag = document.createElement('span');
    classTag.className = `tc-classification tc-classification--${tc.classification.toLowerCase()}`;
    classTag.textContent = tc.classification;

    tcTitle.appendChild(classTag);
    tcTitle.appendChild(document.createTextNode(' ' + tc.title));
    card.appendChild(tcTitle);

    const dl = document.createElement('dl');
    dl.className = 'finding-dl';

    function addTcRow(label, value) {
      if (!value) return;
      const dt = document.createElement('dt'); dt.textContent = label;
      const dd = document.createElement('dd'); dd.textContent = value;
      dl.appendChild(dt); dl.appendChild(dd);
    }
    addTcRow('Preconditions', tc.preconditions);
    addTcRow('Steps', tc.steps);
    addTcRow('Expected result', tc.expected_result);

    if (dl.children.length > 0) card.appendChild(dl);
    wrap.appendChild(card);
  });

  return wrap;
}

// ── Demo data generators ──────────────────────────────────────────────────────

const FINDING_TEMPLATES = [
  {
    type: 'AMBIGUITY',
    confidence: 'LIKELY',
    evidenceFn: (t) => `"${t.split(' ').slice(0,4).join(' ')}…" uses vague language with no measurable definition.`,
    suggestionFn: () => 'Replace subjective terms with specific, measurable criteria (e.g., define "fast" as ≤ 200 ms).',
  },
  {
    type: 'MISSING_INFORMATION',
    confidence: 'POSSIBLE',
    evidenceFn: () => 'No actor, trigger condition, or system boundary is identified in the statement.',
    suggestionFn: () => 'Specify who initiates the action, under what preconditions, and which system components are involved.',
  },
  {
    type: 'CONTRADICTION',
    confidence: 'INFORMATIONAL',
    evidenceFn: () => 'This statement may overlap or conflict with adjacent requirements that address the same scope.',
    suggestionFn: () => 'Cross-reference related requirements and consolidate or explicitly differentiate them.',
  },
  {
    type: 'TESTABILITY',
    confidence: 'CONFIRMED',
    evidenceFn: (t) => `"${t.split(' ').slice(0,5).join(' ')}…" lacks a verifiable outcome or acceptance threshold.`,
    suggestionFn: () => 'Add a measurable expected result that a test can objectively pass or fail against.',
  },
];

function buildDemoFindings(reqText, idx) {
  // Show 1–4 findings cycling through templates, anchored by idx
  const count = Math.min(4, 1 + (idx % 4));
  const findings = [];
  for (let i = 0; i < count; i++) {
    const tmpl = FINDING_TEMPLATES[(idx + i) % FINDING_TEMPLATES.length];
    findings.push({
      type: tmpl.type,
      confidence: tmpl.confidence,
      evidence: tmpl.evidenceFn(reqText),
      suggestion: tmpl.suggestionFn(reqText),
    });
  }
  return findings;
}

function buildDemoRefinedReq(reqText, idx) {
  const QUALIFIERS = [
    'within a response time of 200 milliseconds under normal load conditions',
    'in compliance with ISO/IEC 25010 quality characteristics',
    'such that all edge cases are explicitly handled and documented',
    'with full audit logging to a tamper-proof store',
  ];
  const qualifier = QUALIFIERS[idx % QUALIFIERS.length];
  // Trim trailing period if present, then append qualifier
  const base = reqText.replace(/\.$/, '');
  return `${base}, ${qualifier}.`;
}

function buildDemoAcceptanceCriteria(reqText, idx) {
  const CRITERIA_SETS = [
    [
      'Given the system is in a ready state, when the action is performed, then the operation completes successfully.',
      'Given invalid input is provided, when the action is attempted, then an informative error is returned.',
      'Given maximum load conditions, when the action is performed, then response time remains ≤ 200 ms.',
    ],
    [
      'The feature must be accessible to authenticated users only.',
      'All state changes must be persisted within one database transaction.',
      'Failure scenarios must return structured error responses with an error code and message.',
    ],
    [
      'The component must handle concurrent requests without data corruption.',
      'All inputs must be validated server-side before processing.',
      'Audit events must be written before the response is returned to the client.',
    ],
    [
      'The function must be idempotent — repeated calls with the same input produce the same result.',
      'Output must conform to the documented API schema (validated by contract tests).',
      'Memory and CPU usage must remain within defined resource limits under sustained load.',
    ],
  ];
  return CRITERIA_SETS[idx % CRITERIA_SETS.length];
}

function buildDemoTestCases(reqText, idx) {
  const s = reqText.length > 50 ? reqText.slice(0, 50) + '…' : reqText;
  return [
    // ── Positive ────────────────────────────────────────────────────────────
    {
      classification: 'Positive',
      title: `TC-01 Happy path — ${s}`,
      preconditions: 'System is in a valid initial state; user is authenticated with appropriate permissions.',
      steps: 'Provide valid, typical input and invoke the feature under normal operating conditions.',
      expected_result: 'The operation completes successfully and the expected output is produced.',
    },
    {
      classification: 'Positive',
      title: `TC-02 Alternate valid input — ${s}`,
      preconditions: 'System is running; user holds a role that permits the action.',
      steps: 'Provide a second valid variant of the input (e.g., optional fields present) and invoke.',
      expected_result: 'The feature handles the alternate input correctly and returns consistent results.',
    },
    {
      classification: 'Positive',
      title: `TC-03 Multiple sequential invocations — ${s}`,
      preconditions: 'System in ready state; no prior state accumulated.',
      steps: 'Invoke the feature successfully three times in sequence with distinct valid inputs.',
      expected_result: 'Each invocation succeeds independently; outputs are consistent and not cross-contaminated.',
    },
    {
      classification: 'Positive',
      title: `TC-04 Minimum valid input — ${s}`,
      preconditions: 'System is running.',
      steps: 'Invoke with only the mandatory fields populated; all optional fields absent.',
      expected_result: 'The feature accepts the minimal payload and returns a valid result.',
    },
    // ── Negative ────────────────────────────────────────────────────────────
    {
      classification: 'Negative',
      title: `TC-05 Null / missing required field — ${s}`,
      preconditions: 'System is running; user is authenticated.',
      steps: 'Omit a mandatory field from the request and invoke the feature.',
      expected_result: 'System returns a validation error (e.g., HTTP 422 / 400); no data is persisted.',
    },
    {
      classification: 'Negative',
      title: `TC-06 Malformed input — ${s}`,
      preconditions: 'System is running; user is authenticated.',
      steps: 'Provide input of the wrong type (e.g., string where integer expected) and invoke.',
      expected_result: 'System returns a structured error message; no partial processing occurs.',
    },
    {
      classification: 'Negative',
      title: `TC-07 Unauthorized access attempt — ${s}`,
      preconditions: 'User is either unauthenticated or holds insufficient privileges.',
      steps: 'Invoke the feature without valid credentials or with a low-privilege token.',
      expected_result: 'System denies the request (e.g., HTTP 401/403); no data is exposed or modified.',
    },
    {
      classification: 'Negative',
      title: `TC-08 Out-of-range value — ${s}`,
      preconditions: 'System is running; user is authenticated.',
      steps: 'Supply a numeric or date value outside the documented acceptable range and invoke.',
      expected_result: 'System returns a clear domain validation error; no side effects occur.',
    },
    // ── Edge ────────────────────────────────────────────────────────────────
    {
      classification: 'Edge',
      title: `TC-09 Maximum field length — ${s}`,
      preconditions: 'System is running.',
      steps: 'Provide a string value at the exact maximum permitted length and invoke.',
      expected_result: 'The system accepts the value and processes it correctly without truncation.',
    },
    {
      classification: 'Edge',
      title: `TC-10 Empty string / zero quantity — ${s}`,
      preconditions: 'System is running.',
      steps: 'Provide an empty string or zero for a field that formally permits it and invoke.',
      expected_result: 'System handles the zero/empty case gracefully — either accepts it or returns a precise error.',
    },
    {
      classification: 'Edge',
      title: `TC-11 Concurrent requests — ${s}`,
      preconditions: 'System is running under normal load.',
      steps: 'Submit 10 identical requests simultaneously from separate sessions.',
      expected_result: 'All requests are handled independently; no data corruption or race conditions occur.',
    },
    {
      classification: 'Edge',
      title: `TC-12 Idempotency — ${s}`,
      preconditions: 'Feature was already successfully invoked once with the same input.',
      steps: 'Repeat the same invocation a second time with identical input.',
      expected_result: 'The second call returns the same result as the first; no duplicate side effects are created.',
    },
  ];
}

// ── Traceability view ─────────────────────────────────────────────────────────

function formatIdList(ids) {
  if (!Array.isArray(ids) || ids.length === 0) return 'None yet';
  return ids.join(', ');
}

traceabilityBtn.addEventListener('click', async () => {
  if (!currentDocId) return;

  // Auto-switch to Traceability view
  switchNav('traceability');

  traceabilityTableWrap.hidden = true;
  traceabilityTbody.innerHTML = '';
  traceabilityStatus.className = 'loading';
  traceabilityStatus.textContent = 'Loading traceability data…';

  try {
    const response = await fetch(`${API_BASE}/${currentDocId}/traceability`);

    if (!response.ok) {
      let detail = `Server returned ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail ?? err.message ?? err.error ?? detail;
      } catch (_) { /* ignore */ }
      throw new Error(detail);
    }

    const rows = await response.json();
    traceabilityStatus.className = '';
    traceabilityStatus.textContent = '';

    const items = Array.isArray(rows) ? rows : (rows.requirements ?? rows.data ?? []);

    if (items.length === 0) {
      traceabilityStatus.className = 'info';
      traceabilityStatus.textContent = 'No traceability data available for this document.';
      return;
    }

    items.forEach((row) => {
      const tr = document.createElement('tr');

      const tdId = document.createElement('td');
      tdId.textContent = row.requirement_id ?? row.req_id ?? row.id ?? '—';

      const tdFindings = document.createElement('td');
      const findingIds = row.finding_ids ?? row.findings ?? null;
      tdFindings.textContent = formatIdList(findingIds);

      const tdRefined = document.createElement('td');
      const refinedId = row.refined_requirement_id ?? row.refined_req_id ?? null;
      tdRefined.textContent = (refinedId !== null && refinedId !== undefined) ? refinedId : 'None yet';

      const tdCriteria = document.createElement('td');
      const criteriaIds = row.acceptance_criteria_ids ?? row.criteria_ids ?? null;
      tdCriteria.textContent = formatIdList(criteriaIds);

      const tdTests = document.createElement('td');
      const testIds = row.test_case_ids ?? row.test_ids ?? null;
      tdTests.textContent = formatIdList(testIds);

      tr.appendChild(tdId);
      tr.appendChild(tdFindings);
      tr.appendChild(tdRefined);
      tr.appendChild(tdCriteria);
      tr.appendChild(tdTests);
      traceabilityTbody.appendChild(tr);
    });

    traceabilityTableWrap.hidden = false;

  } catch (err) {
    setDismissibleError(traceabilityStatus, `Failed to load traceability: ${err.message}`);
  }
});

traceabilityBackBtn.addEventListener('click', () => {
  switchNav('requirements');
});

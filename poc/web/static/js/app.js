/* ═══════════════════════════════════════════════════════
   DataBridge PoC — Frontend App
   ═══════════════════════════════════════════════════════ */

const API = '';   // same origin

// ── State ────────────────────────────────────────────────
let treQueue       = [];   // [{file, tre, sst, status, hangers}]
let currentTREFile = null; // last selected (for single-file submit)
let _selectedTREIdx = -1;  // index of currently highlighted queue item
let currentIFCFile = null;
let currentTRE     = null;
let currentSST     = null;
let ifcViewer      = null;

// ── DOM refs ─────────────────────────────────────────────
const inputTRE        = document.getElementById('inputTRE');
const inputIFC        = document.getElementById('inputIFC');
const inputMMDL       = document.getElementById('inputMMDL');
const btnPickTRE      = document.getElementById('btnPickTRE');
const btnPickIFC      = document.getElementById('btnPickIFC');
const btnPickMMDL     = document.getElementById('btnPickMMDL');
const dropTRE         = document.getElementById('dropTRE');
const dropIFC         = document.getElementById('dropIFC');
const dropMMDL        = document.getElementById('dropMMDL');
const treFileName     = document.getElementById('treFileName');
const ifcFileName     = document.getElementById('ifcFileName');
const mmdlFileName    = document.getElementById('mmdlFileName');
const cardTREQueue    = document.getElementById('cardTREQueue');
const treQueueList    = document.getElementById('treQueueList');
const treQueueBadge   = document.getElementById('treQueueBadge');
const btnSubmitAllSST = document.getElementById('btnSubmitAllSST');
const uploadStatus    = document.getElementById('uploadStatus');
const cardTRE         = document.getElementById('cardTRE');
const treDataGrid     = document.getElementById('treDataGrid');
const cardSST         = document.getElementById('cardSST');
const sstInputGrid    = document.getElementById('sstInputGrid');
// Overlay controls
const cardOverlay     = document.getElementById('cardOverlay');
const overlayMark     = document.getElementById('overlayMark');
const ovSpecies       = document.getElementById('ovSpecies');
const ovWidth         = document.getElementById('ovWidth');
const ovDepth         = document.getElementById('ovDepth');
const ovPly           = document.getElementById('ovPly');
const ovKH            = document.getElementById('ovKH');
const btnOverlayLoad  = document.getElementById('btnOverlayLoad');
const btnOverlayApply = document.getElementById('btnOverlayApply');
const btnSubmitSST    = document.getElementById('btnSubmitSST');
const cardIFC         = document.getElementById('cardIFC');
const ifcMetaGrid     = document.getElementById('ifcMetaGrid');
const ifcElementsTable= document.getElementById('ifcElementsTable');
const cardMMDLParsed   = document.getElementById('cardMMDLParsed');
const mmdlDataGrid     = document.getElementById('mmdlDataGrid');
const mmdlMarksTable   = document.getElementById('mmdlMarksTable');
const mmdlEntriesTable = document.getElementById('mmdlEntriesTable');
const mmdlOverlayTable = document.getElementById('mmdlOverlayTable');
const mmdlStrJob       = document.getElementById('mmdlStrJob');
const mmdlStrJobProps  = document.getElementById('mmdlStrJobProps');
const mmdlStrTrusses   = document.getElementById('mmdlStrTrusses');
const mmdlStrDesign    = document.getElementById('mmdlStrDesign');
const cardResults     = document.getElementById('cardResults');
const resultsBadge    = document.getElementById('resultsBadge');
const resultsSpinner  = document.getElementById('resultsSpinner');
const resultsTable    = document.getElementById('resultsTable');
const btnLoadBatch    = document.getElementById('btnLoadBatch');
const batchTable      = document.getElementById('batchTable');
const toast           = document.getElementById('toast');
// Track MMDL context availability heuristically
let _hasMMDL = false;

// ── Toast ─────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = 'info', ms = 3500) {
  toast.textContent = msg;
  toast.className = `toast ${type}`;
  toast.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.display = 'none'; }, ms);
}

// ── Status bar ────────────────────────────────────────────
function setStatus(msg, type = 'info') {
  uploadStatus.textContent = msg;
  uploadStatus.className = `status-bar ${type}`;
  uploadStatus.style.display = 'block';
}

// ── Data grid builder ─────────────────────────────────────
function buildGrid(container, rows) {
  container.innerHTML = '';
  rows.forEach(({ label, value, wide, cls }) => {
    const item = document.createElement('div');
    item.className = 'data-grid__item' + (wide ? ' data-grid__item--wide' : '');
    item.innerHTML = `
      <div class="data-grid__label">${label}</div>
      <div class="data-grid__value ${cls || ''}">${value ?? '—'}</div>`;
    container.appendChild(item);
  });
}

// ── Table builder ─────────────────────────────────────────
function buildTable(container, headers, rows, emptyMsg = 'No results.') {
  if (!rows.length) {
    container.innerHTML = `<div class="empty-state">${emptyMsg}</div>`;
    return;
  }
  const thead = headers.map(h => `<th>${h}</th>`).join('');
  const tbody = rows.map(cells =>
    `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`
  ).join('');
  container.innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
}

// ── Token management ──────────────────────────────────────
const inputToken       = document.getElementById('inputToken');
const btnSetToken      = document.getElementById('btnSetToken');
const tokenStatus      = document.getElementById('tokenStatus');
const btnSubmitSSTPlay = document.getElementById('btnSubmitSSTPlaywright');
const submitHint       = document.getElementById('submitHint');

let _hasToken = false;

async function checkTokenStatus() {
  try {
    const res  = await fetch(`${API}/api/token-status`);
    const data = await res.json();
    _hasToken = data.has_token;
    if (_hasToken) {
      tokenStatus.textContent = `✓ Token set (${data.preview})`;
      tokenStatus.className = 'token-status token-status--ok';
      if (submitHint) submitHint.textContent = 'Fast API mode active';
    } else {
      tokenStatus.textContent = 'No token';
      tokenStatus.className = 'token-status token-status--err';
      if (submitHint) submitHint.textContent = 'Set Bearer token above to enable fast API submit';
    }
    _updateSubmitButtons();
  } catch(e) {}
}

function _updateSubmitButtons() {
  const hasTRE = !!currentTREFile;
  if (btnSubmitSST)   btnSubmitSST.disabled   = !hasTRE || !_hasToken;
  if (btnSubmitAllSST) btnSubmitAllSST.disabled = treQueue.length === 0 || !_hasToken;
}

btnSetToken?.addEventListener('click', async () => {
  const raw = inputToken?.value?.trim();
  if (!raw) { showToast('Paste a token first', 'error'); return; }
  btnSetToken.disabled = true;
  try {
    const res  = await fetch(`${API}/api/set-token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: raw }),
    });
    const data = await res.json();
    if (data.ok) {
      showToast(`Token set (${data.token_length} chars)`, 'ok');
      inputToken.value = '';
      await checkTokenStatus();
    } else {
      showToast('Failed to set token', 'error');
    }
  } catch(e) {
    showToast('Error: ' + e.message, 'error');
  } finally {
    btnSetToken.disabled = false;
  }
});

// ── File pick buttons ─────────────────────────────────────
btnPickTRE.addEventListener('click', () => { inputTRE.click(); });
btnPickIFC.addEventListener('click', () => { inputIFC.click(); });
btnPickMMDL.addEventListener('click', () => { inputMMDL.click(); });

inputTRE.addEventListener('change', () => {
  if (inputTRE.files.length) handleTREFiles(Array.from(inputTRE.files));
});
inputIFC.addEventListener('change', () => {
  if (inputIFC.files[0]) handleIFCFile(inputIFC.files[0]);
});
inputMMDL?.addEventListener('change', () => {
  if (inputMMDL.files[0]) handleMMDLFile(inputMMDL.files[0]);
});

// ── Drag & drop for TRE slot ──────────────────────────────
dropTRE.addEventListener('click', () => inputTRE.click());
dropTRE.addEventListener('dragover', e => { e.preventDefault(); dropTRE.classList.add('drag-over'); });
dropTRE.addEventListener('dragleave', () => dropTRE.classList.remove('drag-over'));
dropTRE.addEventListener('drop', e => {
  e.preventDefault(); dropTRE.classList.remove('drag-over');
  const files = Array.from(e.dataTransfer.files).filter(f => !f.name.toLowerCase().endsWith('.ifc'));
  if (files.length) handleTREFiles(files);
});

// ── Drag & drop for IFC slot ──────────────────────────────
dropIFC.addEventListener('click', () => inputIFC.click());
dropIFC.addEventListener('dragover', e => { e.preventDefault(); dropIFC.classList.add('drag-over'); });
dropIFC.addEventListener('dragleave', () => dropIFC.classList.remove('drag-over'));
dropIFC.addEventListener('drop', e => {
  e.preventDefault(); dropIFC.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleIFCFile(e.dataTransfer.files[0]);
});

// Drag & drop for MMDL slot
dropMMDL.addEventListener('click', () => inputMMDL.click());
dropMMDL.addEventListener('dragover', e => { e.preventDefault(); dropMMDL.classList.add('drag-over'); });
dropMMDL.addEventListener('dragleave', () => dropMMDL.classList.remove('drag-over'));
dropMMDL.addEventListener('drop', e => {
  e.preventDefault(); dropMMDL.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleMMDLFile(e.dataTransfer.files[0]);
});

// ── TRE file handler (multi-file) ────────────────────────
async function handleTREFiles(files) {
  if (!files.length) return;

  // Add new files to queue (skip duplicates by name)
  const existing = new Set(treQueue.map(q => q.file.name));
  const added = [];
  for (const f of files) {
    if (!existing.has(f.name)) {
      treQueue.push({ file: f, tre: null, sst: null, status: 'pending', hangers: [] });
      added.push(f);
    }
  }
  if (!added.length) { showToast('Files already in queue', 'info'); return; }

  // Update drop zone label
  treFileName.textContent = treQueue.length === 1
    ? treQueue[0].file.name
    : `${treQueue.length} files selected`;
  dropTRE.classList.add('loaded');

  // Show queue card
  cardTREQueue.style.display = 'block';
  renderTREQueue();

  // Parse all new files
  setStatus(`Parsing ${added.length} TRE file(s)…`, 'info');
  for (const f of added) {
    await parseTREQueued(f);
  }
  setStatus(`Parsed ${treQueue.length} TRE file(s)`, 'ok');

  // Auto-select last file for detail view
  const last = treQueue[treQueue.length - 1];
  if (last.tre) showTREDetail(last);
}

function renderTREQueue() {
  treQueueList.innerHTML = '';
  treQueueBadge.textContent = treQueue.length;

  const allParsed = treQueue.every(q => q.status !== 'pending');
  btnSubmitAllSST.disabled = !allParsed || treQueue.length === 0 || !_hasToken;

  treQueue.forEach((item, idx) => {
    const div = document.createElement('div');
    const selectedCls = idx === _selectedTREIdx ? ' selected' : '';
    div.className = 'tre-queue-item' + (item.status === 'parsing' ? ' active' : item.status === 'done' ? ' done' : item.status === 'error' ? ' error' : '') + selectedCls;
    div.dataset.idx = idx;

    const r1 = item.tre?.reaction1_lbs ?? '—';
    const ct = item.sst?.connection_type ?? '—';
    const hangerCount = item.hangers?.length ?? 0;

    const statusHtml = item.status === 'parsing'
      ? '<div class="spinner" style="width:14px;height:14px;border-width:2px"></div>'
      : item.status === 'done'
        ? `<span class="tag tag--ok">${hangerCount} hangers</span>`
        : item.status === 'error'
          ? '<span class="tag tag--fail">Error</span>'
          : '<span class="tag" style="background:rgba(100,116,139,.15);color:var(--text3)">Pending</span>';

    const canSubmit = item.status === 'parsed' || item.status === 'done';
    div.innerHTML = `
      <div>
        <div class="tre-queue-item__name">${item.file.name}</div>
        <div class="tre-queue-item__meta">R1: ${r1} lbs &nbsp;·&nbsp; ${ct}</div>
      </div>
      <div class="tre-queue-item__status">${statusHtml}</div>
      <div style="display:flex;gap:4px">
        <button class="btn btn--ghost btn--sm" onclick="selectTREItem(${idx})">View</button>
        <button class="btn btn--accent btn--sm" onclick="findHangersForItem(${idx})" ${!canSubmit || !_hasToken ? 'disabled' : ''}>⚡</button>
      </div>`;

    treQueueList.appendChild(div);
  });
}

async function findHangersForItem(idx) {
  const item = treQueue[idx];
  if (!item || !_hasToken) return;
  selectTREItem(idx);
  await _doSubmitSST('/api/submit-sst-api', `Finding hangers for ${item.file.name}…`);
}

function selectTREItem(idx) {
  const item = treQueue[idx];
  if (!item) return;
  _selectedTREIdx = idx;
  renderTREQueue();   // re-render immediately so highlight applies before async work
  currentTREFile = item.file;
  currentTRE = item.tre;
  currentSST = item.sst;
  if (item.tre) showTREDetail(item);
  if (item.hangers?.length) {
    renderHangerResults({ hanger_count: item.hangers.length, hangers: item.hangers, connection_type: item.sst?.connection_type });
  }
  // Populate Analyzer with this item
  openAnalyzer(item);
  _updateSubmitButtons();
}

async function showTREDetail(item) {
  if (item.tre) {
    renderTREData(item.tre);
    cardTRE.style.display = 'block';
  }
  if (item.sst) {
    renderSSTInputs(item.sst);
    cardSST.style.display = 'block';
    btnSubmitSST.disabled = false;
    currentTREFile = item.file;
  }
  // Show Overlay panel when have MMDL mark
  if (item.tre?.mmdl_mark) {
    if (cardOverlay) cardOverlay.style.display = 'block';
    if (overlayMark) { overlayMark.style.display = ''; overlayMark.textContent = item.tre.mmdl_mark; }
  } else {
    if (cardOverlay) cardOverlay.style.display = 'none';
  }
  // Load 2D diagram (Diagram tab)
  loadTrussDiagram(item.file);
  // If MMDL source selected, try load plan image as diagram
  if (typeof diagramSource !== 'undefined' && diagramSource?.value === 'mmdl') {
    try {
      const img = document.getElementById('mmdlPlanImg2');
      const wrap = document.getElementById('mmdlDiagram');
      const svg  = document.getElementById('trussDiagramSVG');
      const ping = await fetch(`${API}/api/mmdl-plan.png`, { method: 'GET' });
      if (ping.ok && img && wrap && svg) {
        const blob = await ping.blob(); const url = URL.createObjectURL(blob);
        img.onload = () => { try { URL.revokeObjectURL(url); } catch(e) {} };
        img.src = url; svg.style.display = 'none'; wrap.style.display = '';
      }
    } catch(e) { /* ignore */ }
  }
}

async function parseTREQueued(file) {
  const item = treQueue.find(q => q.file === file);
  if (!item) return;
  item.status = 'parsing';
  renderTREQueue();

  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`${API}/api/parse-tre`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.detail || data.error || 'Parse failed');
    item.tre = data.tre;
    item.sst = data.sst_input;
    item.status = 'parsed';
  } catch(e) {
    item.status = 'error';
    item.error = e.message;
  }
  renderTREQueue();
  renderBatchFromQueue();
}

// ── IFC file handler ──────────────────────────────────────
async function handleIFCFile(file) {
  currentIFCFile = file;
  ifcFileName.textContent = file.name;
  dropIFC.classList.add('loaded');
  setStatus(`Loading IFC ${file.name}…`, 'info');
  showToast(`Loading IFC ${file.name}…`, 'info');
  cardIFC.style.display = 'none';
  await parseIFC(file);
}

// ── MMDL file handler ───────────────────────────────────────────────────────
async function handleMMDLFile(file) {
  mmdlFileName.textContent = file.name;
  dropMMDL.classList.add('loaded');
  setStatus(`Parsing MMDL ${file.name}…`, 'info');

  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch(`${API}/api/parse-mmdl`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      setStatus(`MMDL Error: ${data.detail || data.error}`, 'error');
      showToast('MMDL parse failed', 'error');
      return;
    }
    // Show a brief toast + console dump for now (diagnostic)
    showToast(`MMDL parsed: ${data.entries?.length || 0} entries`, 'ok');
    console.groupCollapsed('MMDL Summary');
    console.log('zip_offset', data.zip_offset);
    console.table(data.entries || []);
    console.log('suggested_marks', data.suggested_marks || []);
    console.log('truss_candidates', data.truss_candidates || []);
    if (data.overlay_suggested) {
      console.table(Object.entries(data.overlay_suggested).map(([k,v]) => ({ mark:k, ...v })));
    }
    console.groupEnd();
    setStatus(`MMDL parsed: ${data.entries?.length || 0} entries`, 'ok');
    _hasMMDL = true;
    // Render parsed card
    try {
      if (cardMMDLParsed && mmdlDataGrid && mmdlMarksTable) {
        const rows = [
          { label: 'Filename', value: data.filename || file.name, wide: true },
          { label: 'ZIP Offset', value: typeof data.zip_offset === 'number' ? data.zip_offset : '—' },
          { label: 'Entries', value: Array.isArray(data.entries) ? data.entries.length : '—' },
          { label: 'Has Plan PNG', value: (data.entries||[]).some(e => (e.name||'').toLowerCase().includes('plan')) ? 'Yes' : '—' },
        ];
        buildGrid(mmdlDataGrid, rows);
        const marks = (data.truss_candidates || []).map((m, i) => [String(i+1), `<code>${m}</code>`]);
        buildTable(mmdlMarksTable, ['#', 'Mark'], marks.slice(0, 100), 'No marks found.');
        // Entries table
        if (mmdlEntriesTable) {
          const ents = (data.entries || []).map(e => [
            `<code>${e.name || e.filename || '—'}</code>`,
            e.size != null ? e.size : (e.length != null ? e.length : '—'),
          ]);
          buildTable(mmdlEntriesTable, ['Name', 'Size (bytes)'], ents, 'No entries.');
        }
        // Overlay suggestions table (if provided by backend)
        if (mmdlOverlayTable) {
          const ov = data.overlay_suggested || {};
          const rowsOv = Object.keys(ov).map(k => [
            `<code>${k}</code>`, ov[k]?.girder_width || '—', ov[k]?.girder_depth || '—', ov[k]?.girder_ply ?? '—', ov[k]?.king_height ?? '—'
          ]);
          buildTable(mmdlOverlayTable, ['Mark', 'Width', 'Depth', 'Ply', 'King Height'], rowsOv, 'No suggestions.');
        }
        // String samples
        const fmt = (arr) => (Array.isArray(arr) ? arr.slice(0, 30).join('\n') : '');
        if (mmdlStrJob)      mmdlStrJob.textContent      = fmt(data.strings?.job || data.job_strings);
        if (mmdlStrJobProps) mmdlStrJobProps.textContent = fmt(data.strings?.jobProps || data.jobprops_strings);
        if (mmdlStrTrusses)  mmdlStrTrusses.textContent  = fmt(data.strings?.trusses || data.trusses_strings);
        if (mmdlStrDesign)   mmdlStrDesign.textContent   = fmt(data.strings?.trussdesignresults || data.design_strings);
        cardMMDLParsed.style.display = 'block';
      }
    } catch(_) {}
    // If we already have TRE files parsed, call join to annotate
    try {
      const names = treQueue.map(q => q.file?.name).filter(Boolean);
      if (names.length) {
        const resj = await fetch(`${API}/api/mmdl-join`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filenames: names })
        });
        const dj = await resj.json();
        if (resj.ok && dj.ok) {
          const map = new Map(dj.matches.map(m => [m.filename, m.mmdl_mark]));
          for (const item of treQueue) {
            const mk = map.get(item.file?.name);
            if (mk && item.tre) item.tre.mmdl_mark = mk;
          }
          renderTREQueue();
          const cur = treQueue.find(q => q.file === currentTREFile);
          if (cur?.tre) renderTREData(cur.tre);
        }
      }
    } catch(e) { /* silent */ }
    // Try to load plan image
    try {
      const imgEl = document.getElementById('mmdlPlanImg');
      const card = document.getElementById('cardMMDLPlan');
      const ping = await fetch(`${API}/api/mmdl-plan.png`, { method: 'GET' });
      if (ping.ok && imgEl && card) {
        const blob = await ping.blob();
        const url = URL.createObjectURL(blob);
        imgEl.onload = () => { try { URL.revokeObjectURL(url); } catch(e) {} };
        imgEl.src = url;
        card.style.display = 'block';
      } else if (card) {
        card.style.display = 'none';
      }
    } catch(e) { /* ignore */ }
  } catch (err) {
    setStatus(`MMDL network error: ${err.message}`, 'error');
  }
}

// ── Parse TRE ─────────────────────────────────────────────
async function parseTRE(file) {
  const fd = new FormData();
  fd.append('file', file);

  try {
    const res = await fetch(`${API}/api/parse-tre`, { method: 'POST', body: fd });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      setStatus(`Error: ${data.detail || data.error || 'Unknown error'}`, 'error');
      showToast('Parse failed', 'error');
      return;
    }

    currentTRE = data.tre;
    currentSST = data.sst_input;

    setStatus(`Parsed ${file.name} successfully`, 'ok');
    showToast('TRE parsed OK', 'ok');

    renderTREData(data.tre);
    renderSSTInputs(data.sst_input);

    cardTRE.style.display = 'block';
    cardSST.style.display = 'block';
    btnSubmitSST.disabled = false;

  } catch (err) {
    setStatus(`Network error: ${err.message}`, 'error');
    showToast('Network error', 'error');
  }
}

// ── Render TRE data grid ──────────────────────────────────
function renderTREData(t) {
  const pitchStr = t.pitch_degrees != null
    ? `${t.pitch_degrees.toFixed(2)}° (tan ${t.pitch_tan.toFixed(4)})`
    : '—';

  const rows = [
    { label: 'Filename',        value: t.filename,          wide: true },
    { label: 'MMDL Mark',       value: t.mmdl_mark || '—' },
    { label: 'Truss Type',      value: `${t.truss_type_label} (${t.truss_type_code})`, wide: true },
    { label: 'Span',            value: `${t.span_inches}"  (${(t.span_inches/12).toFixed(3)}')` },
    { label: 'Pitch',           value: pitchStr },
    { label: 'Left Heel Ht',    value: `${t.left_heel_height}"` },
    { label: 'Right Heel Ht',   value: `${t.right_heel_height}"` },
    { label: 'Overall Height',  value: t.overall_height_str ? `${t.overall_height_str}  (${t.heel_height_inches.toFixed(4)}")` : '—' },
    { label: 'Girder?',         value: t.is_girder ? 'Yes' : 'No', cls: t.is_girder ? 'data-grid__value--yellow' : '' },
    { label: 'Ply',             value: t.ply },
    { label: 'Reaction 1',      value: `${t.reaction1_lbs} lbs`, cls: 'data-grid__value--accent' },
    { label: 'Reaction 2',      value: `${t.reaction2_lbs} lbs`, cls: 'data-grid__value--accent' },
    { label: 'Uplift 1',        value: t.uplift1_lbs ? `${t.uplift1_lbs} lbs` : '—' },
    { label: 'Uplift 2',        value: t.uplift2_lbs ? `${t.uplift2_lbs} lbs` : '—' },
    { label: 'Skew',            value: t.skew_degrees != null ? `${t.skew_degrees}°` : '—' },
    { label: 'Bottom Chord',    value: t.bottom_chord ? `${t.bottom_chord.size} ${t.bottom_chord.grade} ${t.bottom_chord.species}` : '—' },
    { label: 'Top Chord',       value: t.top_chord    ? `${t.top_chord.size} ${t.top_chord.grade} ${t.top_chord.species}` : '—' },
    { label: 'Code Standard',   value: t.code_standard || '—' },
    { label: 'Date',            value: t.date || '—' },
  ];
  buildGrid(treDataGrid, rows);
}

// ── Render SST inputs grid ────────────────────────────────
function renderSSTInputs(sst) {
  if (!sst) { sstInputGrid.innerHTML = '<div class="empty-state">No SST inputs mapped.</div>'; return; }

  const ct = sst.connection_type || '—';
  const rows = [
    { label: 'Connection Type', value: ct.toUpperCase(), wide: true, cls: ct === 'joist' ? 'data-grid__value--green' : 'data-grid__value--accent' },
  ];

  // Flatten nested objects for display
  function flattenObj(obj, prefix = '') {
    Object.entries(obj).forEach(([k, v]) => {
      if (k === 'connection_type') return;
      const label = (prefix ? prefix + ' › ' : '') + k.replace(/_/g, ' ');
      if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
        flattenObj(v, prefix ? prefix + ' › ' + k : k);
      } else {
        rows.push({ label, value: v ?? '—' });
      }
    });
  }
  flattenObj(sst);
  buildGrid(sstInputGrid, rows);
}

// ── Overlay helpers ─────────────────────────────────────────────────────────
async function loadOverlayForCurrent() {
  const mark = _analyzerItem?.tre?.mmdl_mark;
  if (!mark) { showToast('No MMDL mark for current TRE', 'error'); return; }
  try {
    const res = await fetch(`${API}/api/mmdl-overlay`);
    const data = await res.json();
    if (!res.ok || !data.ok) return;
    const ov = data.overlay?.[mark.toLowerCase()] || {};
    if (ovSpecies) ovSpecies.value = ov.girder_species || '';
    if (ovWidth)   ovWidth.value   = ov.girder_width   || '';
    if (ovDepth)   ovDepth.value   = ov.girder_depth   || '';
    if (ovPly)     ovPly.value     = ov.girder_ply     ?? '';
    if (ovKH)      ovKH.value      = ov.king_height    ?? '';
    showToast('Overlay loaded', 'ok');
  } catch(e) {
    showToast('Overlay load failed', 'error');
  }
}

async function applyOverlayForCurrent() {
  const mark = _analyzerItem?.tre?.mmdl_mark;
  if (!mark) { showToast('No MMDL mark for current TRE', 'error'); return; }
  const body = {
    mark,
    girder_species: ovSpecies?.value || null,
    girder_width:   ovWidth?.value   || null,
    girder_depth:   ovDepth?.value   || null,
    girder_ply:     ovPly?.value ? Number(ovPly.value) : null,
    king_height:    ovKH?.value  ? Number(ovKH.value)  : null,
  };
  try {
    const res = await fetch(`${API}/api/mmdl-set-props`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) { showToast('Overlay apply failed', 'error'); return; }
    showToast('Overlay applied', 'ok');
  } catch(e) {
    showToast('Overlay apply failed', 'error');
  }
}

// ── Submit to SST ─────────────────────────────────────────
async function _doSubmitSST(endpoint, toastMsg) {
  if (!currentTREFile) return;
  btnSubmitSST.disabled = true;
  if (btnSubmitSSTPlay) btnSubmitSSTPlay.disabled = true;
  resultsSpinner.style.display = 'flex';
  resultsTable.innerHTML = '';
  resultsBadge.textContent = '';
  switchRightTab('tabResults');
  showToast(toastMsg, 'info', 40000);

  const fd = new FormData();
  fd.append('file', currentTREFile);

  try {
    const res  = await fetch(`${API}${endpoint}`, { method: 'POST', body: fd });
    const data = await res.json();
    resultsSpinner.style.display = 'none';

    if (!res.ok || !data.ok) {
      resultsTable.innerHTML = `<div class="empty-state" style="color:var(--red)">Error: ${data.detail || data.error || 'Unknown'}</div>`;
      resultsBadge.textContent = 'Error';
      resultsBadge.className = 'badge badge--red';
      showToast('SST submission failed', 'error');
    } else {
      renderHangerResults(data);
      // Update queue item hangers
      const item = treQueue.find(q => q.file === currentTREFile);
      if (item) { item.hangers = data.hangers || []; item.status = 'done'; renderTREQueue(); }
      renderBatchFromQueue();
      showToast(`${data.hanger_count} hanger(s) found`, data.hanger_count > 0 ? 'ok' : 'info');
    }
  } catch (err) {
    resultsSpinner.style.display = 'none';
    resultsTable.innerHTML = `<div class="empty-state" style="color:var(--red)">Network error: ${err.message}</div>`;
    showToast('Network error', 'error');
  } finally {
    _updateSubmitButtons();
  }
}

// Fast API submit (Bearer token)
btnSubmitSST?.addEventListener('click', () =>
  _doSubmitSST('/api/submit-sst-api', 'Submitting to SST API…')
);

// Playwright fallback
btnSubmitSSTPlay?.addEventListener('click', () =>
  _doSubmitSST('/api/submit-sst', 'Submitting via Playwright… ~30s')
);

// ── Render hanger results ─────────────────────────────────
function renderHangerResults(data) {
  const count = data.hanger_count || 0;
  resultsBadge.textContent = `${count} result${count !== 1 ? 's' : ''}`;
  resultsBadge.className = `badge ${count > 0 ? 'badge--green' : ''}`;

  if (!count) {
    resultsTable.innerHTML = `<div class="empty-state">No qualifying hangers returned by SST.<br><small style="color:var(--text3)">This is expected for heavy girder trusses (R1 &gt; ~2000 lbs) and gable end trusses.</small></div>`;
    return;
  }

  const headers = ['Model', 'Cost', 'Width', 'Height', 'Bearing', 'DL (lbs)', 'UL (lbs)'];
  const rows = data.hangers.map(h => [
    `<span class="model-name">${h.model_name || '—'}</span>`,
    h.cost || '—',
    h.width || '—',
    h.height || '—',
    h.bearing || '—',
    h.download_load != null ? h.download_load : '—',
    h.uplift_load   != null ? h.uplift_load   : '—',
  ]);
  buildTable(resultsTable, headers, rows);
}

// ── Parse IFC ─────────────────────────────────────────────
async function parseIFC(file) {
  const fd = new FormData();
  fd.append('file', file);

  try {
    const res = await fetch(`${API}/api/parse-ifc`, { method: 'POST', body: fd });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      setStatus(`IFC Error: ${data.detail || data.error}`, 'error');
      return;
    }

    setStatus(`Parsed IFC: ${data.element_count} elements (${(data.ifc_bytes/1024).toFixed(1)} KB)`, 'ok');
    showToast('IFC parsed OK', 'ok');

    // Metadata grid
    buildGrid(ifcMetaGrid, [
      { label: 'Filename',      value: file.name, wide: true },
      { label: 'Schema',        value: data.schema },
      { label: 'File Size',     value: `${(data.ifc_bytes/1024).toFixed(1)} KB` },
      { label: 'Total Elements',value: data.element_count },
      { label: 'Shown (cap)',   value: data.elements.length },
      { label: 'Note',          value: data.note || '', wide: true },
    ]);

    // Elements table (first 200)
    const headers = ['ID', 'Type', 'Name', 'GlobalId'];
    const rows = data.elements.map(el => [
      el.id,
      `<span class="tag tag--truss">${el.type}</span>`,
      el.name || '—',
      `<small style="color:var(--text3)">${el.global_id}</small>`,
    ]);
    buildTable(ifcElementsTable, headers, rows, 'No elements found.');

    cardIFC.style.display = 'block';

    // Load IFC.js viewer
    loadIFCViewer(file);

  } catch (err) {
    setStatus(`Network error: ${err.message}`, 'error');
  }
}

// ── IFC.js Viewer ─────────────────────────────────────
let ifcModelID   = null;
let hoverRAF     = null;
let lastHoverKey = null;
let propCache    = new Map();
let gridOn       = true;
let axesOn       = true;

const btnFitView    = document.getElementById('btnFitView');
const btnGrid       = document.getElementById('btnGrid');
const btnAxes       = document.getElementById('btnAxes');
const ifcTooltip    = document.getElementById('ifcTooltip');
const ifcTipTitle   = document.getElementById('ifcTooltipTitle');
const ifcTipBody    = document.getElementById('ifcTooltipBody');
const ifcLoading    = document.getElementById('ifcLoading');
const ifcLoadTxt    = document.getElementById('ifcLoadingText');
const ifcProps      = document.getElementById('ifcPropsPanel');
const ifcPropsCt    = document.getElementById('ifcPropsContent');
const btnCloseProps = document.getElementById('btnCloseProps');

btnCloseProps?.addEventListener('click', () => {
  ifcProps.classList.add('hidden');
  try { ifcViewer?.IFC?.selector?.unpickIfcItems?.(); } catch(e) {}
});

function setViewerLoading(msg) {
  if (ifcLoadTxt) ifcLoadTxt.textContent = msg;
  ifcLoading?.classList.remove('hidden');
}
function clearViewerLoading() {
  ifcLoading?.classList.add('hidden');
}
function hideTooltip() {
  ifcTooltip?.classList.add('hidden');
}
function positionTooltip(x, y) {
  if (!ifcTooltip) return;
  const tw = ifcTooltip.offsetWidth  || 200;
  const th = ifcTooltip.offsetHeight || 80;
  ifcTooltip.style.left = Math.min(x + 14, window.innerWidth  - tw - 8) + 'px';
  ifcTooltip.style.top  = Math.min(y + 14, window.innerHeight - th - 8) + 'px';
}

async function getElementProps(modelID, expressID) {
  const key = `${modelID}:${expressID}`;
  if (propCache.has(key)) return propCache.get(key);
  try {
    const raw = await ifcViewer.IFC.getProperties(modelID, expressID, true, false);
    const rows = [];
    const str = v => {
      if (v == null) return null;
      if (typeof v === 'object' && 'value' in v) return String(v.value);
      if (typeof v === 'object' && 'wrappedValue' in v) return String(v.wrappedValue);
      return String(v);
    };
    const nm = str(raw?.Name);       if (nm)  rows.push(['Name', nm]);
    const ot = str(raw?.ObjectType); if (ot)  rows.push(['Object Type', ot]);
    const tg = str(raw?.Tag);        if (tg)  rows.push(['Tag', tg]);
    if (raw?.type) rows.push(['IFC Type', String(raw.type).replace(/^IFC/, 'Ifc')]);
    const psets = raw?.psets ?? [];
    const seen = new Set();
    for (const ps of psets) {
      for (const p of (ps.HasProperties ?? ps.hasProperties ?? [])) {
        const label = str(p.Name) ?? p.name;
        const val   = str(p.NominalValue) ?? str(p.value);
        if (!label || val == null || val === '') continue;
        const dedup = `${label}:${val}`;
        if (!seen.has(dedup)) { seen.add(dedup); rows.push([label, val]); }
      }
    }
    rows.push(['Express ID', expressID]);
    propCache.set(key, rows);
    return rows;
  } catch(e) { return [['Express ID', expressID]]; }
}

async function loadIFCViewer(file) {
  const container = document.getElementById('ifcViewerContainer');
  const placeholder = document.getElementById('viewerPlaceholder');

  if (!window.IfcViewerAPI || !window.WebIFC) {
    if (placeholder) placeholder.innerHTML = '<div class="viewer-placeholder__icon">&#9888;</div><div>IFC viewer not loaded</div>';
    return;
  }

  if (placeholder) placeholder.remove();
  setViewerLoading('Initializing viewer…');

  try {
    if (ifcViewer) {
      try { ifcViewer.dispose(); } catch(e) {}
      ifcViewer = null;
      ifcModelID = null;
      propCache.clear();
    }

    ifcViewer = new window.IfcViewerAPI({
      container,
      backgroundColor: new THREE.Color(0x0f1117),
    });

    ifcViewer.IFC.loader.ifcManager.state.api.SetWasmPath('/static/js/vendor/', true);

    ifcViewer.axes.setAxes();
    ifcViewer.grid.setGrid();

    if (btnFitView) { btnFitView.disabled = false; btnFitView.onclick = () => ifcViewer.context.fitToFrame(); }
    if (btnGrid) {
      btnGrid.disabled = false; btnGrid.classList.add('active');
      btnGrid.onclick = ev => { gridOn = !gridOn; ev.currentTarget.classList.toggle('active', gridOn); gridOn ? ifcViewer.grid.setGrid() : ifcViewer.grid.dispose(); };
    }
    if (btnAxes) {
      btnAxes.disabled = false; btnAxes.classList.add('active');
      btnAxes.onclick = ev => { axesOn = !axesOn; ev.currentTarget.classList.toggle('active', axesOn); axesOn ? ifcViewer.axes.setAxes() : ifcViewer.axes.dispose(); };
    }

    setViewerLoading(`Loading ${file.name}…`);
    const url = URL.createObjectURL(file);
    const model = await ifcViewer.IFC.loadIfcUrl(url, true);
    URL.revokeObjectURL(url);

    if (!model) throw new Error('Model returned null — wasm parse failed');
    ifcModelID = model.modelID;

    clearViewerLoading();
    showToast('IFC model loaded', 'ok');
    switchRightTab('tabIFC');

    // Hover
    const canvas = ifcViewer.context.getDomElement();
    canvas.addEventListener('mousemove', ev => {
      if (hoverRAF) cancelAnimationFrame(hoverRAF);
      hoverRAF = requestAnimationFrame(() => onHover(ev));
    });
    canvas.addEventListener('mouseleave', () => {
      hideTooltip(); lastHoverKey = null;
      try { ifcViewer.IFC.selector?.unPrepickIfcItems?.(); } catch(e) {}
    });
    canvas.addEventListener('dblclick', async () => {
      try {
        const picked = await ifcViewer.IFC.selector.pickIfcItem(true);
        if (!picked) { ifcProps?.classList.add('hidden'); return; }
        const rows = await getElementProps(picked.modelID, picked.id);
        renderPropsPanel(rows);
      } catch(e) {}
    });
    window.addEventListener('keydown', ev => {
      if (ev.code === 'Escape') {
        ifcProps?.classList.add('hidden');
        hideTooltip();
        try { ifcViewer.IFC.selector?.unpickIfcItems?.(); } catch(e) {}
      }
    });

  } catch (err) {
    clearViewerLoading();
    showToast('IFC viewer error: ' + err.message, 'error');
    console.error('IFC viewer error:', err);
    if (container) container.innerHTML += `<div class="viewer-placeholder" style="position:absolute;inset:0"><div class="viewer-placeholder__icon">&#9888;</div><div>${err.message}</div></div>`;
  }
}

async function onHover(ev) {
  if (!ifcViewer || ifcModelID === null) { hideTooltip(); return; }
  try {
    await ifcViewer.IFC.selector.prePickIfcItem();
    const hit = ifcViewer.context.castRayIfc();
    if (!hit || hit.faceIndex == null) { hideTooltip(); lastHoverKey = null; return; }
    const expressID = ifcViewer.IFC.loader.ifcManager.getExpressId(hit.object.geometry, hit.faceIndex);
    if (expressID == null) { hideTooltip(); return; }
    const key = `${ifcModelID}:${expressID}`;
    if (key !== lastHoverKey) {
      lastHoverKey = key;
      if (ifcTipTitle) ifcTipTitle.textContent = 'Loading…';
      if (ifcTipBody)  ifcTipBody.innerHTML = '';
      ifcTooltip?.classList.remove('hidden');
      positionTooltip(ev.clientX, ev.clientY);
      const rows = await getElementProps(ifcModelID, expressID);
      const name = rows.find(([k]) => k === 'Name')?.[1] || 'Element';
      const type = rows.find(([k]) => k === 'IFC Type')?.[1] || '';
      if (ifcTipTitle) ifcTipTitle.textContent = name;
      if (ifcTipBody) {
        ifcTipBody.innerHTML = '';
        const show = [[`Type`, type], ...rows.filter(([k]) => !['Name','IFC Type','Express ID'].includes(k)).slice(0,4)];
        for (const [k, v] of show) {
          if (!v) continue;
          const dt = document.createElement('dt'); dt.textContent = k;
          const dd = document.createElement('dd'); dd.textContent = v;
          ifcTipBody.append(dt, dd);
        }
      }
    }
    positionTooltip(ev.clientX, ev.clientY);
    ifcTooltip?.classList.remove('hidden');
  } catch(e) { hideTooltip(); }
}

function renderPropsPanel(rows) {
  if (!ifcPropsCt || !ifcProps) return;
  ifcPropsCt.innerHTML = '';
  for (const [k, v] of rows) {
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = String(v);
    ifcPropsCt.append(dt, dd);
  }
  ifcProps.classList.remove('hidden');
}
// ── Batch Results ─────────────────────────────────────────
btnLoadBatch.addEventListener('click', () => {
  if (treQueue.length > 0) {
    renderBatchFromQueue();
  } else {
    loadBatchResults();
  }
});

async function loadBatchResults() {
  batchTable.innerHTML = '<div class="empty-state"><div class="spinner" style="margin:0 auto 8px"></div>Loading…</div>';

  try {
    const res = await fetch(`${API}/api/batch-results`);
    const data = await res.json();

    if (!data.ok) {
      batchTable.innerHTML = `<div class="empty-state">${data.error}</div>`;
      return;
    }

    // Normalise field names from results.json → renderBatchTable schema
    const results = (data.results || []).map(r => ({
      filename:       r.filename  || r.file || '—',
      connection_type: r.connection_type || '—',
      reaction1_lbs:  r.reaction1_lbs ?? r.load_lbs   ?? '—',
      reaction2_lbs:  r.reaction2_lbs ?? '—',
      hangers: (r.hangers || []).map(h => ({
        ...h,
        model_name: h.model_name || h.model || '—',
      })),
      success: r.success,
      error:   r.error || null,
    }));

    renderBatchTable(results);
  } catch (err) {
    batchTable.innerHTML = `<div class="empty-state" style="color:var(--red)">Error: ${err.message}</div>`;
  }
}

function renderBatchTable(results) {
  if (!results || !results.length) {
    batchTable.innerHTML = '<div class="empty-state">No batch results found.</div>';
    return;
  }

  const headers = ['File', 'Type', 'R1 (lbs)', 'R2 (lbs)', 'Hangers', 'Top Model', 'Status'];

  const rows = results.map(r => {
    const ct = r.connection_type || '—';
    const tagCls = ct === 'joist' ? 'tag--joist' : ct === 'truss' ? 'tag--truss' : 'tag--none';
    const hangers = r.hangers || [];
    const topModel = hangers.length ? `<span class="model-name">${hangers[0].model_name}</span>` : '—';
    const statusCls = r.success ? 'tag--ok'
      : r._status === 'pending'  ? ''
      : r._status === 'parsing'  ? ''
      : r._status === 'error'    ? 'tag--fail'
      : r.success === false      ? 'tag--fail' : '';
    const statusTxt = r.success ? 'OK'
      : r._status === 'pending'  ? 'Pending'
      : r._status === 'parsing'  ? '…'
      : (r.error || 'Fail');

    return [
      `<strong>${r.filename || '—'}</strong>`,
      `<span class="tag ${tagCls}">${ct}</span>`,
      r.reaction1_lbs ?? '—',
      r.reaction2_lbs ?? '—',
      hangers.length,
      topModel,
      `<span class="tag ${statusCls}">${statusTxt}</span>`,
    ];
  });

  buildTable(batchTable, headers, rows);
}

// Render batch table from live treQueue (reflects current session submits)
function renderBatchFromQueue() {
  if (!treQueue.length) return;   // nothing in queue — keep existing table

  const results = treQueue.map(item => ({
    filename:        item.file.name,
    connection_type: item.sst?.connection_type ?? '—',
    reaction1_lbs:   item.tre?.reaction1_lbs ?? '—',
    reaction2_lbs:   item.tre?.reaction2_lbs ?? '—',
    hangers:         (item.hangers || []).map(h => ({ model_name: h.model || h.model_name || '—' })),
    success:         item.status === 'done',
    error:           item.error || null,
    _status:         item.status,
  }));

  renderBatchTable(results);
}

// ── Submit All to SST ─────────────────────────────────────
btnSubmitAllSST?.addEventListener('click', async () => {
  const toSubmit = treQueue.filter(q => q.status === 'parsed' || q.status === 'done');
  if (!toSubmit.length) return;

  const endpoint = _hasToken ? '/api/submit-sst-api' : '/api/submit-sst';
  const modeLabel = _hasToken ? 'API' : 'Playwright';

  btnSubmitAllSST.disabled = true;
  showToast(`Submitting ${toSubmit.length} files via ${modeLabel}…`, 'info', 120000);

  let doneCount = 0;
  let errorCount = 0;

  for (const item of toSubmit) {
    item.status = 'parsing';
    renderTREQueue();

    const fd = new FormData();
    fd.append('file', item.file);
    try {
      const res  = await fetch(`${API}${endpoint}`, { method: 'POST', body: fd });
      const data = await res.json();
      if (res.ok && data.ok) {
        item.hangers = data.hangers || [];
        item.status  = 'done';
        doneCount++;
      } else {
        item.status = 'error';
        item.error  = data.error || data.detail || 'Failed';
        // 401 = token expired — stop batch and notify
        if (res.status === 401 || (data.error || '').includes('401')) {
          renderTREQueue();
          showToast('Token expired — set a new token and retry', 'error', 8000);
          btnSubmitAllSST.disabled = false;
          return;
        }
        errorCount++;
      }
    } catch(e) {
      item.status = 'error';
      item.error  = e.message;
      errorCount++;
    }
    renderTREQueue();
  }

  const summary = `Done: ${doneCount} OK, ${errorCount} errors`;
  showToast(summary, errorCount > 0 ? 'info' : 'ok', 5000);
  btnSubmitAllSST.disabled = false;
  renderBatchFromQueue();


});

// ── Auto-load batch on page load ──────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  loadBatchResults();
  initRightTabs();
  initAnalyzerTabs();
  checkTokenStatus();
  // Overlay buttons
  btnOverlayLoad?.addEventListener('click', loadOverlayForCurrent);
  btnOverlayApply?.addEventListener('click', applyOverlayForCurrent);
});

// ═══════════════════════════════════════════════════════════
// Right Panel Tab System
// ═══════════════════════════════════════════════════════════
function initRightTabs() {
  document.querySelectorAll('.right-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.right-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.right-tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = document.getElementById(btn.dataset.tab);
      if (panel) panel.classList.add('active');
    });
  });
}

function switchRightTab(tabId) {
  document.querySelectorAll('.right-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.right-tab-panel').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.right-tab[data-tab="${tabId}"]`);
  if (btn) btn.classList.add('active');
  const panel = document.getElementById(tabId);
  if (panel) panel.classList.add('active');
}

// ═══════════════════════════════════════════════════════════
// Analyzer Sub-tabs
// ═══════════════════════════════════════════════════════════
function initAnalyzerTabs() {
  document.querySelectorAll('.analyzer-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.analyzer-tab').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.analyzer-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = document.getElementById(btn.dataset.atab);
      if (panel) panel.classList.add('active');
    });
  });

}

// ═══════════════════════════════════════════════════════════
// Truss Analyzer — main entry point
// ═══════════════════════════════════════════════════════════
let _analyzerItem = null;   // current item being analyzed
let _analyzerGeo  = null;   // geometry data for load diagram

function openAnalyzer(item) {
  _analyzerItem = item;
  switchRightTab('tabAnalyzer');

  const badge = document.getElementById('analyzerFileBadge');
  if (badge) { badge.textContent = item.file.name; badge.style.display = ''; }

  renderAnalyzerSummary(item);
  renderMappingSummary(item);
}

// ── Summary ───────────────────────────────────────────────
function renderAnalyzerSummary(item) {
  const empty   = document.getElementById('analyzerEmpty');
  const content = document.getElementById('analyzerSummaryContent');
  if (!item?.tre) {
    if (empty)   empty.style.display = '';
    if (content) content.style.display = 'none';
    return;
  }
  if (empty)   empty.style.display = 'none';
  if (content) content.style.display = '';

  const t = item.tre;

  // ── Stat cards ──
  const statsEl = document.getElementById('analyzerStats');
  if (statsEl) {
    const maxR = Math.max(t.reaction1_lbs || 0, t.reaction2_lbs || 0);
    const maxU = Math.max(t.uplift1_lbs   || 0, t.uplift2_lbs   || 0);
    const stats = [
      { label: 'Span',      value: (t.span_inches/12).toFixed(2), unit: 'ft',  cls: 'stat-card--accent' },
      { label: 'Pitch',     value: t.pitch_degrees?.toFixed(1) ?? '—', unit: '°', cls: '' },
      { label: 'Height',    value: t.overall_height_str || '—', unit: '',      cls: '' },
      { label: 'Max R↓',   value: maxR, unit: 'lbs',  cls: maxR > 2000 ? 'stat-card--red' : 'stat-card--green' },
      { label: 'Max Uplift',value: maxU || '—', unit: maxU ? 'lbs' : '', cls: maxU > 500 ? 'stat-card--yellow' : '' },
      { label: 'Skew',      value: t.skew_degrees ?? '—', unit: t.skew_degrees != null ? '°' : '', cls: t.skew_degrees > 0 ? 'stat-card--yellow' : '' },
      { label: 'Ply',       value: t.ply ?? 1, unit: '',  cls: t.ply > 1 ? 'stat-card--yellow' : '' },
      { label: 'Girder',    value: t.is_girder ? 'Yes' : 'No', unit: '', cls: t.is_girder ? 'stat-card--yellow' : '' },
    ];
    statsEl.innerHTML = stats.map(s => `
      <div class="stat-card ${s.cls}">
        <div class="stat-card__label">${s.label}</div>
        <div class="stat-card__value">${s.value}</div>
        ${s.unit ? `<div class="stat-card__unit">${s.unit}</div>` : ''}
      </div>`).join('');
  }

  // ── Members table ──
  const membersEl = document.getElementById('analyzerMembersTable');
  if (membersEl && t.members_detail) {
    // members_detail not in current API response — use what we have
  }
  // Build from known fields
  if (membersEl) {
    const rows = [];
    if (t.top_chord)    rows.push(['Top Chord',    t.top_chord.label,    t.top_chord.size,    t.top_chord.grade,    t.top_chord.species,    `${t.top_chord.width}" × ${t.top_chord.height}"`]);
    if (t.bottom_chord) rows.push(['Bottom Chord', t.bottom_chord.label, t.bottom_chord.size, t.bottom_chord.grade, t.bottom_chord.species, `${t.bottom_chord.width}" × ${t.bottom_chord.height}"`]);
    buildTable(membersEl,
      ['Role', 'Label', 'Size', 'Grade', 'Species', 'Actual Dims'],
      rows,
      'No member data.'
    );
  }

  // ── Bearings table ──
  const bearingsEl = document.getElementById('analyzerBearingsTable');
  if (bearingsEl) {
    const rows = [];
    // Bearing 0 = left, 1 = right
    const rLabels = ['Left', 'Right'];
    const reactions = [
      { dl: t.reaction1_lbs, ul: t.uplift1_lbs },
      { dl: t.reaction2_lbs, ul: t.uplift2_lbs },
    ];
    for (let i = 0; i < 2; i++) {
      const r = reactions[i];
      rows.push([
        rLabels[i],
        r.dl ? `${r.dl} lbs` : '—',
        r.ul ? `${r.ul} lbs` : '—',
        t.skew_degrees != null ? `${t.skew_degrees}°` : '—',
      ]);
    }
    buildTable(bearingsEl,
      ['Bearing', 'Download (R)', 'Uplift', 'Skew'],
      rows
    );
  }
}



// ═══════════════════════════════════════════════════════════
// TRE → SST Mapping Summary
// ═══════════════════════════════════════════════════════════

function renderMappingSummary(item) {
  const empty   = document.getElementById('mappingEmpty');
  const content = document.getElementById('mappingContent');
  if (!item?.tre || !item?.sst) {
    if (empty)   empty.style.display = '';
    if (content) content.style.display = 'none';
    return;
  }
  if (empty)   empty.style.display = 'none';
  if (content) content.style.display = '';

  const t = item.tre;
  const s = item.sst;
  const isJoist = s.connection_type === 'joist';

  // Connection type badge
  const connEl = document.getElementById('mappingConnType');
  if (connEl) {
    const connLabel = isJoist ? 'Joist (Flush Top)' : 'Truss (Flush Bottom)';
    const connCls   = isJoist ? 'tag--joist' : 'tag--truss';
    connEl.innerHTML = `Connection Type: <span class="tag ${connCls}" style="font-size:12px">${connLabel}</span>
      &nbsp; detected from truss type label: <code style="color:var(--text2)">"${t.truss_type_label}"</code>`;
  }

  // ── Helper: build a mapping table ──
  // rows: [{treField, treValue, rule, sstField, sstValue}]
  function buildMappingTable(containerId, rows) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!rows.length) { el.innerHTML = '<div class="empty-state" style="padding:8px 0">—</div>'; return; }

    const thead = `<tr>
      <th>TRE Source Field</th>
      <th>TRE Value</th>
      <th></th>
      <th>Mapping Rule</th>
      <th>SST Field</th>
      <th>SST Value</th>
    </tr>`;
    const tbody = rows.map(r => `<tr>
      <td class="map-col-tre">${r.treField}</td>
      <td class="map-col-val">${r.treValue ?? '—'}</td>
      <td class="map-col-arrow">→</td>
      <td class="map-col-rule">${r.rule}</td>
      <td class="map-col-sst-field">${r.sstField}</td>
      <td class="map-col-sst">${r.sstValue ?? '—'}</td>
    </tr>`).join('');

    el.innerHTML = `<div class="mapping-table"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`;
  }

  // ── 1. Connection & Job Settings ──
  const jobRows = [
    {
      treField:  'truss_type_label',
      treValue:  `"${t.truss_type_label}"`,
      rule:      'Contains "jack/joist/floor" → joist; else → truss',
      sstField:  'connection_type',
      sstValue:  s.connection_type,
    },
    {
      treField:  'truss_type_label',
      treValue:  `"${t.truss_type_label}"`,
      rule:      'Contains "jack/floor" → Floor (100); else → Roof (125)',
      sstField:  'job.download_duration',
      sstValue:  s.job?.download_duration,
    },
    {
      treField:  'filename',
      treValue:  t.filename,
      rule:      'Strip .tre extension',
      sstField:  'job.job_id',
      sstValue:  s.job?.job_id,
    },
    {
      treField:  '(fixed)',
      treValue:  '—',
      rule:      'Always "Quake/Wind (160)"',
      sstField:  'job.uplift_duration',
      sstValue:  s.job?.uplift_duration,
    },
    {
      treField:  '(fixed)',
      treValue:  '—',
      rule:      'Always "All Types"',
      sstField:  'job.hanger_type',
      sstValue:  s.job?.hanger_type,
    },
  ];
  if (!isJoist) {
    jobRows.push({
      treField:  '(fixed)',
      treValue:  '—',
      rule:      'Always "On (Interior Connection)"',
      sstField:  'ansitpi',
      sstValue:  s.ansitpi,
    });
  }
  buildMappingTable('mappingJobTable', jobRows);

  // ── 2. Carried member ──
  const carriedTitleEl = document.getElementById('mappingCarriedTitle');
  if (carriedTitleEl) carriedTitleEl.textContent = isJoist ? 'Carried Member (Joist)' : 'Carried Member (Truss)';

  const bc = t.bottom_chord;
  const carriedRows = isJoist ? [
    {
      treField:  '(fixed)',
      treValue:  '—',
      rule:      'Jack truss acts as solid sawn joist',
      sstField:  'joist_type',
      sstValue:  s.joist_type,
    },
    {
      treField:  'bottom_chord.species',
      treValue:  bc ? `"${bc.species}"` : '—',
      rule:      'SPECIES_MAP lookup (SP→"SP (Southern Pine)", etc.)',
      sstField:  'joist_species',
      sstValue:  s.joist_species,
    },
    {
      treField:  'bottom_chord.actual_width',
      treValue:  bc ? `${bc.width}"` : '—',
      rule:      'WIDTH_MAP: 1.5"→\'2x (1 1/2")\', 3.5"→\'4x (3 1/2")\', …',
      sstField:  'joist_width',
      sstValue:  s.joist_width,
    },
    {
      treField:  'bottom_chord.actual_height',
      treValue:  bc ? `${bc.height}"` : '—',
      rule:      'DEPTH_MAP: 3.5"→\'4 (3 1/2")\', 5.5"→\'6 (5 1/2")\', …',
      sstField:  'joist_depth',
      sstValue:  s.joist_depth,
    },
    {
      treField:  'ply',
      treValue:  t.ply,
      rule:      'Direct copy',
      sstField:  'joist_ply',
      sstValue:  s.joist_ply,
    },
  ] : [
    {
      treField:  '(fixed)',
      treValue:  '—',
      rule:      'All trusses in dataset are wood trusses',
      sstField:  'truss_type',
      sstValue:  s.truss_type,
    },
    {
      treField:  'bottom_chord.species',
      treValue:  bc ? `"${bc.species}"` : '—',
      rule:      'SPECIES_MAP lookup',
      sstField:  'truss_species',
      sstValue:  s.truss_species,
    },
    {
      treField:  'bottom_chord.actual_width',
      treValue:  bc ? `${bc.width}"` : '—',
      rule:      'WIDTH_MAP lookup',
      sstField:  'truss_width',
      sstValue:  s.truss_width,
    },
    {
      treField:  'bottom_chord.actual_height',
      treValue:  bc ? `${bc.height}"` : '—',
      rule:      'Direct: BC lumber depth = truss heel height for SST',
      sstField:  'truss_heel_height',
      sstValue:  s.truss_heel_height != null ? `${s.truss_heel_height}"` : '—',
    },
    {
      treField:  'ply',
      treValue:  t.ply,
      rule:      'Direct copy',
      sstField:  'truss_ply',
      sstValue:  s.truss_ply,
    },
  ];
  buildMappingTable('mappingCarriedTable', carriedRows);

  // ── 3. Carrying member ──
  const carryingTitleEl = document.getElementById('mappingCarryingTitle');
  if (carryingTitleEl) carryingTitleEl.textContent = isJoist ? 'Carrying Member (Header)' : 'Carrying Member (Girder)';

  const carryingRows = isJoist ? [
    {
      treField:  '(same as joist)',
      treValue:  '—',
      rule:      'Header assumed same species as joist BC',
      sstField:  'header_species',
      sstValue:  s.header_species,
    },
    {
      treField:  '(same as joist)',
      treValue:  '—',
      rule:      'Header assumed same width as joist BC',
      sstField:  'header_width',
      sstValue:  s.header_width,
    },
    {
      treField:  '(same as joist)',
      treValue:  '—',
      rule:      'Header assumed same depth as joist BC',
      sstField:  'header_depth',
      sstValue:  s.header_depth,
    },
    {
      treField:  'plies_on_girder',
      treValue:  t.plies_on_girder,
      rule:      'Direct copy',
      sstField:  'header_ply',
      sstValue:  s.header_ply,
    },
  ] : [
    {
      treField:  '(fixed)',
      treValue:  '—',
      rule:      'Girder is always a wood truss in this dataset',
      sstField:  'girder_type',
      sstValue:  s.girder_type,
    },
    {
      treField:  'bottom_chord.species',
      treValue:  bc ? `"${bc.species}"` : '—',
      rule:      'Girder BC species = carried truss BC species (same lumber)',
      sstField:  'girder_species',
      sstValue:  s.girder_species,
    },
    {
      treField:  'bottom_chord.actual_width',
      treValue:  bc ? `${bc.width}"` : '—',
      rule:      'WIDTH_MAP lookup (same as carried truss)',
      sstField:  'girder_width',
      sstValue:  s.girder_width,
    },
    {
      treField:  'bottom_chord.actual_height',
      treValue:  bc ? `${bc.height}"` : '—',
      rule:      'DEPTH_MAP lookup → girder BC depth',
      sstField:  'girder_depth',
      sstValue:  s.girder_depth,
    },
    {
      treField:  'plies_on_girder',
      treValue:  t.plies_on_girder,
      rule:      'Direct copy',
      sstField:  'girder_ply',
      sstValue:  s.girder_ply,
    },
    {
      treField:  'left_heel_height (ROOF BASICS pos 10)',
      treValue:  `${t.left_heel_height}"`,
      rule:      'Vertical heel height at left bearing = girder total height for SST king post clearance',
      sstField:  'girder_total_height',
      sstValue:  s.girder_total_height != null ? `${s.girder_total_height}"` : '—',
    },
  ];
  buildMappingTable('mappingCarryingTable', carryingRows);

  // ── 4. Loads ──
  const loadsRows = [
    {
      treField:  'reaction1_lbs',
      treValue:  `${t.reaction1_lbs} lbs`,
      rule:      'Max download at left bearing (bearing 0)',
      sstField:  isJoist ? 'joist_load' : 'truss_load',
      sstValue:  `${isJoist ? s.joist_load : s.truss_load} lbs`,
    },
    {
      treField:  'uplift1_lbs',
      treValue:  `${t.uplift1_lbs || 0} lbs`,
      rule:      'Max uplift at left bearing (stored positive from "Max Uplift1=" key)',
      sstField:  isJoist ? 'joist_uplift' : 'truss_uplift',
      sstValue:  `${isJoist ? s.joist_uplift : s.truss_uplift} lbs`,
    },
  ];
  buildMappingTable('mappingLoadsTable', loadsRows);

  // ── 5. Hanger Options ──
  const h = s.hanger || {};
  const hangerRows = [
    {
      treField:  'bearings[0].orientation_rad',
      treValue:  t.skew_degrees != null ? `${t.skew_degrees}°` : '—',
      rule:      'abs(degrees(orient) − 90°) = skew deviation from perpendicular',
      sstField:  'hanger.skew_angle',
      sstValue:  h.skew_angle != null ? `${h.skew_angle}°` : '—',
    },
    {
      treField:  isJoist ? 'pitch_degrees' : '(fixed 0)',
      treValue:  isJoist ? `${t.pitch_degrees?.toFixed(2)}°` : '0°',
      rule:      isJoist
        ? 'Joist (Flush Top): top flange follows roof slope → slope = pitch'
        : 'Truss (Flush Bottom): bottom chord is horizontal → slope = 0°',
      sstField:  'hanger.slope_angle',
      sstValue:  h.slope_angle != null ? `${h.slope_angle}°` : '—',
    },
    {
      treField:  '(fixed)',
      treValue:  '0°',
      rule:      'No top flange bend in this dataset',
      sstField:  'hanger.top_flange_bend',
      sstValue:  h.top_flange_bend != null ? `${h.top_flange_bend}°` : '—',
    },
    {
      treField:  '(fixed)',
      treValue:  '"Centered (No Offset)"',
      rule:      'Default — no lateral offset',
      sstField:  'hanger.offset_direction',
      sstValue:  h.offset_direction,
    },
    {
      treField:  '(fixed)',
      treValue:  '"Center"',
      rule:      'Default flush position',
      sstField:  'hanger.flush_position',
      sstValue:  h.flush_position,
    },
  ];
  buildMappingTable('mappingHangerTable', hangerRows);
}

function _heatColor(ratio, alpha) {
  // ratio 0→1: green→yellow→red
  const r = Math.round(ratio < 0.5 ? ratio * 2 * 245 : 245);
  const g = Math.round(ratio < 0.5 ? 197 : (1 - (ratio - 0.5) * 2) * 197);
  const b = Math.round(ratio < 0.5 ? 94  : 68);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ═══════════════════════════════════════════════════════════
// 2D Truss Diagram
// ═══════════════════════════════════════════════════════════

const cardDiagram    = document.getElementById('cardDiagram');
const trussDiagramSVG= document.getElementById('trussDiagramSVG');
const diagramLabel   = document.getElementById('diagramLabel');
const btnDiagramFit  = document.getElementById('btnDiagramFit');
const diagramSource  = document.getElementById('diagramSource');

// Pan/zoom state
let _diagramGeo  = null;   // last loaded geometry response
let _svgPan      = { x: 0, y: 0, scale: 1 };
let _svgDragging = false;
let _svgDragStart= { mx: 0, my: 0, px: 0, py: 0 };

const MEMBER_CLASS = {
  top_chord:    'td-top-chord',
  bottom_chord: 'td-bottom-chord',
  web:          'td-web',
  vertical:     'td-vertical',
};

function _memberClass(type) {
  return MEMBER_CLASS[type] || 'td-other';
}

// Fetch geometry from API and render
async function loadTrussDiagram(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res  = await fetch(`${API}/api/truss-geometry`, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok || !data.ok) { showToast('Diagram error: ' + (data.detail || data.error), 'error'); return; }
    _diagramGeo = data;
    renderTrussDiagram(data);
    cardDiagram.style.display = 'block';
  } catch(e) {
    showToast('Diagram fetch error: ' + e.message, 'error');
  }
}

function renderTrussDiagram(geo) {
  const svg = trussDiagramSVG;
  const placeholder = document.getElementById('diagramPlaceholder');
  svg.innerHTML = '';

  if (!geo.members || !geo.members.length) {
    svg.style.display = 'none';
    if (placeholder) placeholder.style.display = '';
    return;
  }

  if (placeholder) placeholder.style.display = 'none';
  svg.style.display = 'block';

  // Compute bounding box across all member coords
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const m of geo.members) {
    for (const [x, y] of m.coords) {
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
    }
  }
  // Add bearing markers to bbox
  for (const b of (geo.bearings || [])) {
    if (b.x < minX) minX = b.x; if (b.x > maxX) maxX = b.x;
  }

  const W = svg.clientWidth  || 800;
  const H = svg.clientHeight || 300;
  const PAD = 32;
  const geoW = maxX - minX || 1;
  const geoH = maxY - minY || 1;
  const scale = Math.min((W - PAD*2) / geoW, (H - PAD*2) / geoH);

  // TRE Y=0 is bottom; SVG Y increases downward → flip Y
  const tx = x => PAD + (x - minX) * scale;
  const ty = y => H - PAD - (y - minY) * scale;

  // Store transform for pan/zoom reset
  _svgPan = { x: 0, y: 0, scale: 1 };

  // Root group for pan/zoom
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.id = 'diagramRoot';
  svg.appendChild(g);

  // Draw members (bottom chord first so top chord renders on top)
  const ORDER = ['bottom_chord', 'web', 'vertical', 'top_chord'];
  const sorted = [...geo.members].sort((a, b) => {
    const ai = ORDER.indexOf(a.type); const bi = ORDER.indexOf(b.type);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });

  for (const m of sorted) {
    if (!m.coords.length) continue;
    const pts = m.coords.map(([x, y]) => `${tx(x).toFixed(1)},${ty(y).toFixed(1)}`).join(' ');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', pts);
    poly.setAttribute('class', _memberClass(m.type));
    poly.setAttribute('data-label', m.label);
    poly.setAttribute('data-type', m.type);
    g.appendChild(poly);

    // Label at centroid
    const cx = m.coords.reduce((s,[x])=>s+x,0)/m.coords.length;
    const cy = m.coords.reduce((s,[,y])=>s+y,0)/m.coords.length;
    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', tx(cx).toFixed(1));
    lbl.setAttribute('y', ty(cy).toFixed(1));
    lbl.setAttribute('text-anchor', 'middle');
    lbl.setAttribute('dominant-baseline', 'middle');
    lbl.setAttribute('class', 'td-label');
    lbl.textContent = m.label;
    g.appendChild(lbl);
  }

  // Draw bearing markers (triangles pointing up)
  for (const b of (geo.bearings || [])) {
    const bx = tx(b.x);
    const by = ty(b.y);
    const bw = Math.max(b.width * scale, 8);
    const bh = 10;
    const pts = `${bx},${by} ${bx - bw/2},${by + bh} ${bx + bw/2},${by + bh}`;
    const tri = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    tri.setAttribute('points', pts);
    tri.setAttribute('class', 'td-bearing');
    g.appendChild(tri);
  }

  // Update label
  if (diagramLabel) diagramLabel.textContent = `${geo.truss_type_label}  ·  span ${(geo.span_inches/12).toFixed(2)}'`;

  // Fit button
  if (btnDiagramFit) btnDiagramFit.onclick = () => {
    _svgPan = { x: 0, y: 0, scale: 1 };
    _applyDiagramTransform();
  };

  // Pan/zoom
  _setupDiagramInteraction(svg);
}

function _applyDiagramTransform() {
  const root = document.getElementById('diagramRoot');
  if (!root) return;
  root.setAttribute('transform', `translate(${_svgPan.x},${_svgPan.y}) scale(${_svgPan.scale})`);
}

function _setupDiagramInteraction(svg) {
  const wrap = svg.parentElement;

  // Mouse wheel zoom
  wrap.addEventListener('wheel', e => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    _svgPan.scale = Math.max(0.2, Math.min(10, _svgPan.scale * factor));
    _applyDiagramTransform();
  }, { passive: false });

  // Pan drag
  wrap.addEventListener('mousedown', e => {
    _svgDragging = true;
    _svgDragStart = { mx: e.clientX, my: e.clientY, px: _svgPan.x, py: _svgPan.y };
  });
  window.addEventListener('mousemove', e => {
    if (!_svgDragging) return;
    _svgPan.x = _svgDragStart.px + (e.clientX - _svgDragStart.mx);
    _svgPan.y = _svgDragStart.py + (e.clientY - _svgDragStart.my);
    _applyDiagramTransform();
  });
  window.addEventListener('mouseup', () => { _svgDragging = false; });

  // Tooltip on hover
  wrap.addEventListener('mousemove', e => {
    const el = e.target.closest('polygon[data-label]');
    if (el) {
      showToast(`${el.dataset.label}  (${el.dataset.type?.replace('_',' ')})`, 'info', 1200);
    }
  });
}

/**
 * form_builder.js – Éditeur de formulaire interactif
 * Dépendances : Sortable.js (CDN), Bootstrap 5 (CDN)
 *
 * Variables globales attendues dans la page :
 *   FORM_ID   : int
 *   INIT_DATA : array  (questions initiales)
 *   QTYPE_ICONS : object
 */

'use strict';

let editModal  = null;  // instance Bootstrap Modal
let sortable   = null;

// ── Point d'entrée ──────────────────────────────────────────────────────────

function initBuilder(formId, initData) {
  editModal = new bootstrap.Modal(document.getElementById('editModal'));

  // Rendu initial des questions
  const list = document.getElementById('questions-list');
  list.innerHTML = '';
  initData.forEach(q => appendCard(q));
  updateEmpty();

  // Drag & drop
  sortable = Sortable.create(list, {
    handle:       '.drag-handle',
    animation:    150,
    ghostClass:   'sortable-ghost',
    onEnd: async () => {
      const ids = [...list.querySelectorAll('.q-card')].map(el => +el.dataset.qid);
      await api('POST', `questions/reorder`, { order: ids });
    },
  });
}

// ── Ajouter une question ────────────────────────────────────────────────────

async function addQuestion(qtype) {
  const q = await api('POST', 'questions', { qtype, label: 'Nouvelle question' });
  if (!q) return;
  appendCard(q);
  updateEmpty();
  openEditModal(q);
}

// ── Ouvrir le modal d'édition ───────────────────────────────────────────────

function openEditModal(q) {
  document.getElementById('modal-qid').value    = q.id;
  document.getElementById('modal-label').value  = q.label;
  document.getElementById('modal-desc').value   = q.description || '';
  document.getElementById('modal-required').checked = q.required;
  document.getElementById('modal-qtype').value  = q.qtype;
  renderModalSections(q.qtype, q);
  editModal.show();
  setTimeout(() => document.getElementById('modal-label').focus(), 300);
}

// ── Changer le type dans le modal ───────────────────────────────────────────

function onQtypeChange() {
  const qtype = document.getElementById('modal-qtype').value;
  renderModalSections(qtype, null);
}

// ── Rendu conditionnel des sections du modal ────────────────────────────────

function renderModalSections(qtype, q) {
  const hasOptions = ['select', 'radio', 'checkbox'].includes(qtype);
  const isNumber   = qtype === 'number';
  const isText     = ['text', 'textarea'].includes(qtype);
  const isGroupe   = qtype === 'groupe';

  show('options-section',       hasOptions);
  show('config-number-section', isNumber);
  show('config-text-section',   isText);
  show('groupe-section',        isGroupe);

  if (hasOptions) {
    renderOptionsEditor(q ? q.options : []);
  }
  if (isNumber && q) {
    setVal('cfg-min',  q.config.min != null ? q.config.min : '');
    setVal('cfg-max',  q.config.max != null ? q.config.max : '');
    setVal('cfg-step', q.config.step != null ? q.config.step : '');
  }
  if (isText && q) {
    setVal('cfg-placeholder', q.config.placeholder || '');
  }
  if (isGroupe) {
    setVal('cfg-max-wishes', q ? (q.config.max_wishes != null ? q.config.max_wishes : 3) : 3);
    var allowExteEl = document.getElementById('cfg-allow-exte');
    if (allowExteEl) allowExteEl.checked = q ? (q.config.allow_exte != null ? q.config.allow_exte : true) : true;
    // Afficher le lien vers la page groupes si GROUPE_ADMIN_URL est défini
    const linkDiv = document.getElementById('groupe-participants-link');
    if (linkDiv && typeof GROUPE_ADMIN_URL !== 'undefined') {
      linkDiv.style.display = '';
      const a = document.getElementById('groupe-admin-link');
      if (a) a.href = GROUPE_ADMIN_URL;
    }
  }
}

// ── Éditeur d'options ───────────────────────────────────────────────────────

function renderOptionsEditor(options = []) {
  const container = document.getElementById('options-list');
  container.innerHTML = '';
  (options.length ? options : ['']).forEach(opt => addOptionField(opt));
}

function addOptionField(value = '') {
  const container = document.getElementById('options-list');
  const row = document.createElement('div');
  row.className = 'input-group mb-1';
  row.innerHTML = `
    <span class="input-group-text text-muted" style="cursor:grab">
      <i class="bi bi-grip-vertical"></i>
    </span>
    <input type="text" class="form-control option-input" value="${escHtml(value)}"
           placeholder="Option…"/>
    <button class="btn btn-outline-danger" type="button"
            onclick="removeOptionRow(this)">
      <i class="bi bi-x-lg"></i>
    </button>`;
  container.appendChild(row);
}

function removeOptionRow(btn) {
  const rows = document.querySelectorAll('#options-list .input-group');
  if (rows.length <= 1) return;
  btn.closest('.input-group').remove();
}

function collectOptions() {
  return [...document.querySelectorAll('#options-list .option-input')]
    .map(i => i.value.trim())
    .filter(Boolean);
}

// ── Enregistrer la question ─────────────────────────────────────────────────

async function saveQuestion() {
  const qid   = +document.getElementById('modal-qid').value;
  const qtype = document.getElementById('modal-qtype').value;

  const payload = {
    label:       document.getElementById('modal-label').value.trim() || 'Question',
    description: document.getElementById('modal-desc').value.trim(),
    qtype,
    required:    document.getElementById('modal-required').checked,
    options:     ['select', 'radio', 'checkbox'].includes(qtype) ? collectOptions() : [],
    config:      buildConfig(qtype),
  };

  const updated = await api('PUT', `questions/${qid}`, payload);
  if (!updated) return;

  updateCard(updated);
  editModal.hide();
}

function buildConfig(qtype) {
  if (qtype === 'number') {
    return {
      min:  parseFloatOrNull(document.getElementById('cfg-min').value),
      max:  parseFloatOrNull(document.getElementById('cfg-max').value),
      step: parseFloatOrNull(document.getElementById('cfg-step').value),
    };
  }
  if (['text', 'textarea'].includes(qtype)) {
    return { placeholder: document.getElementById('cfg-placeholder').value };
  }
  if (qtype === 'groupe') {
    var mwEl = document.getElementById('cfg-max-wishes');
    var mw = parseInt(mwEl ? mwEl.value : '3', 10);
    var aeEl = document.getElementById('cfg-allow-exte');
    var allowExte = aeEl ? aeEl.checked : true;
    return { max_wishes: isNaN(mw) ? 3 : Math.max(1, mw), allow_exte: allowExte };
  }
  return {};
}

// ── Supprimer une question ──────────────────────────────────────────────────

async function deleteQuestion(qid) {
  if (!confirm('Supprimer cette question ?')) return;
  const ok = await api('DELETE', `questions/${qid}`);
  if (ok === null) return;
  var cardEl = document.getElementById('q-card-' + qid);
  if (cardEl) cardEl.remove();
  updateEmpty();
}

// ── Rendu HTML des cartes ───────────────────────────────────────────────────

function appendCard(q) {
  const list = document.getElementById('questions-list');
  const el   = buildCard(q);
  list.appendChild(el);
}

function updateCard(q) {
  const existing = document.getElementById(`q-card-${q.id}`);
  if (!existing) return;
  existing.replaceWith(buildCard(q));
}

function buildCard(q) {
  const div = document.createElement('div');
  div.className   = 'q-card shadow-sm';
  div.id          = `q-card-${q.id}`;
  div.dataset.qid = q.id;

  const icon = (typeof QTYPE_ICONS !== 'undefined' ? QTYPE_ICONS[q.qtype] : null)
    || 'question-circle';

  const reqBadge = q.required
    ? '<span class="badge bg-danger ms-1 py-0 px-1" style="font-size:.65rem">requis</span>'
    : '';

  const optPreview = q.options && q.options.length
    ? `<span class="q-desc">${q.options.slice(0, 4).map(escHtml).join(' · ')}${q.options.length > 4 ? ' · …' : ''}</span>`
    : '';

  div.innerHTML = `
    <span class="drag-handle mt-1">
      <i class="bi bi-grip-vertical fs-5"></i>
    </span>
    <div class="q-card-body">
      <div class="q-type-badge">
        <i class="bi bi-${escHtml(icon)} me-1"></i>${escHtml(q.type_label)}
      </div>
      <div class="q-label">${escHtml(q.label)}${reqBadge}</div>
      ${q.description ? `<span class="q-desc">${escHtml(q.description)}</span>` : ''}
      ${optPreview}
    </div>
    <div class="d-flex gap-1 align-items-start mt-1">
      <button class="btn btn-sm btn-outline-primary" onclick="openEditModal(${JSON.stringify(q).replace(/"/g,'&quot;')})">
        <i class="bi bi-pencil"></i>
      </button>
      <button class="btn btn-sm btn-outline-danger" onclick="deleteQuestion(${q.id})">
        <i class="bi bi-trash3"></i>
      </button>
    </div>`;
  return div;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function updateEmpty() {
  const list  = document.getElementById('questions-list');
  const empty = document.getElementById('questions-empty');
  if (!empty) return;
  const hasCards = list.querySelectorAll('.q-card').length > 0;
  empty.style.display = hasCards ? 'none' : 'block';
}

function show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? '' : 'none';
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val != null ? val : '';
}

function parseFloatOrNull(s) {
  const v = parseFloat(s);
  return isNaN(v) ? null : v;
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── API fetch helper ─────────────────────────────────────────────────────────

async function api(method, path, body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== null) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(`/api/forms/${FORM_ID}/${path}`, opts);
    if (method === 'DELETE') return res.ok ? {} : null;
    const data = await res.json();
    if (!res.ok) { console.error('API error', data); return null; }
    return data;
  } catch (e) {
    console.error('Fetch error', e);
    return null;
  }
}

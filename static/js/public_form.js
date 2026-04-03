/**
 * public_form.js
 * – Menus déroulants avec recherche (type "select")
 * – Champ de type "groupe" : identité, téléphone, N souhaits, option Exté
 */

'use strict';

// ════════════════════════════════════════════════════════════════════════════
// Composant : Searchable Select
// ════════════════════════════════════════════════════════════════════════════

class SearchableSelect {
  /**
   * @param {HTMLElement} wrap      – conteneur .ss-wrap
   * @param {string[]}    options   – liste des options
   * @param {string}      name      – nom du champ caché
   * @param {string}      initial   – valeur initiale
   * @param {string}      placeholder
   * @param {boolean}     hasError
   * @param {string[]}    [exclude] – valeurs à ne pas proposer (ex. l'identité)
   */
  constructor(wrap, options, name, initial = '', placeholder = 'Rechercher…', hasError = false, exclude = []) {
    this.wrap     = wrap;
    this.options  = options;
    this.name     = name;
    this.selected = initial;
    this.exclude  = exclude;
    this.activeIdx = -1;
    this._build(placeholder, hasError);
    if (initial) this.input.value = initial;
  }

  _build(placeholder, hasError) {
    this.wrap.innerHTML = `
      <input type="text"
             class="form-control${hasError ? ' is-invalid' : ''}"
             placeholder="${esc(placeholder)}"
             autocomplete="off"/>
      <ul class="autocomplete-list" style="display:none"></ul>
      <input type="hidden" name="${esc(this.name)}" value="${esc(this.selected)}"/>`;

    this.input  = this.wrap.querySelector('input[type=text]');
    this.list   = this.wrap.querySelector('.autocomplete-list');
    this.hidden = this.wrap.querySelector('input[type=hidden]');

    this.input.addEventListener('input', () => this._render());

    // Vide le champ au clic/focus pour permettre la saisie immédiate
    this.input.addEventListener('focus', () => {
      this.input.value = '';
      this._render();
    });

    // Si l'utilisateur quitte sans rien choisir, restaure la valeur précédente
    this.input.addEventListener('blur', () => {
      setTimeout(() => {
        if (this.list.style.display !== 'none') return; // sélection en cours
        if (!this.input.value.trim()) {
          this.input.value = this.selected;
        }
      }, 180);
    });

    this.input.addEventListener('keydown', e => this._onKey(e));

    document.addEventListener('click', e => {
      if (!this.wrap.contains(e.target)) {
        this.list.style.display = 'none';
        // Restaure la valeur affichée si on clique ailleurs sans sélectionner
        if (!this.input.value.trim()) {
          this.input.value = this.selected;
        }
      }
    });
  }

  _filtered() {
    const q = this.input.value.toLowerCase();
    return this.options.filter(o =>
      !this.exclude.includes(o) && o.toLowerCase().includes(q)
    );
  }

  _render() {
    const filtered = this._filtered();
    this.list.innerHTML = '';
    this.activeIdx = -1;
    if (!filtered.length) { this.list.style.display = 'none'; return; }
    filtered.forEach(opt => {
      const li = document.createElement('li');
      li.textContent = opt;
      li.addEventListener('mousedown', e => { e.preventDefault(); this.select(opt); });
      this.list.appendChild(li);
    });
    this.list.style.display = 'block';
  }

  _onKey(e) {
    const lis = this.list.querySelectorAll('li');
    if (!lis.length) return;
    if (e.key === 'ArrowDown') {
      this.activeIdx = Math.min(this.activeIdx + 1, lis.length - 1);
      this._highlight(lis); e.preventDefault();
    } else if (e.key === 'ArrowUp') {
      this.activeIdx = Math.max(this.activeIdx - 1, 0);
      this._highlight(lis); e.preventDefault();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (this.activeIdx >= 0 && lis[this.activeIdx]) lis[this.activeIdx].click();
    } else if (e.key === 'Escape') {
      this.list.style.display = 'none';
    }
  }

  _highlight(lis) {
    lis.forEach((li, i) => li.classList.toggle('ac-active', i === this.activeIdx));
  }

  select(value) {
    this.selected   = value;
    this.input.value = value;
    this.hidden.value = value;
    this.list.style.display = 'none';
    this.wrap.dispatchEvent(new CustomEvent('ss:select', { detail: { value }, bubbles: true }));
  }

  updateExclude(exclude) {
    this.exclude = exclude;
  }

  getValue() { return this.hidden.value; }
}


// ════════════════════════════════════════════════════════════════════════════
// Composant : Champ Groupe
// ════════════════════════════════════════════════════════════════════════════

class GroupeField {
  constructor(container) {
    this.container  = container;
    this.qid        = container.dataset.qid;
    this.allPart    = JSON.parse(container.dataset.participants || '[]');
    this.maxWishes  = parseInt(container.dataset.maxWishes || '3', 10);
    this.allowExte  = container.dataset.allowExte !== 'false';
    this.prevType   = container.dataset.prevIdentityType || '';
    this.prevName   = container.dataset.prevIdentityName || '';
    this.prevExte   = container.dataset.prevExteName     || '';
    this.prevPhone  = container.dataset.prevPhone        || '';
    this.errIdent   = container.dataset.errorIdentity    || '';
    this.errExte    = container.dataset.errorExte        || '';
    this.errPhone   = container.dataset.errorPhone       || '';

    this._identityType = this.prevType;
    this._identityName = this.prevName;
    this._wishSS       = [];

    this._render();
  }

  _render() {
    const identityOptions = this.allowExte
      ? ['Exté (personne extérieure)', ...this.allPart]
      : [...this.allPart];

    this.container.innerHTML = `
      <!-- Identité -->
      <div class="mb-3">
        <label class="form-label fw-semibold text-muted small text-uppercase">
          Votre identité <span class="text-danger">*</span>
        </label>
        <div class="ss-wrap" id="g-${this.qid}-ident-wrap"></div>
        ${this.errIdent ? `<div class="invalid-feedback d-block">${esc(this.errIdent)}</div>` : ''}
      </div>

      <!-- Téléphone — commun aux deux cas, affiché dès qu'une identité est choisie -->
      <div id="g-${this.qid}-phone-sec" style="display:none" class="mb-3">
        <label class="form-label fw-semibold">
          Téléphone <span class="text-danger">*</span>
        </label>
        <input type="tel" name="g_${this.qid}_phone" id="g-${this.qid}-phone"
               class="form-control${this.errPhone ? ' is-invalid' : ''}"
               placeholder="06 XX XX XX XX"
               value="${esc(this.prevPhone)}"/>
        ${this.errPhone ? `<div class="invalid-feedback d-block">${esc(this.errPhone)}</div>` : ''}
      </div>

      <!-- Section : personne extérieure -->
      <div id="g-${this.qid}-exte-sec" style="display:none" class="groupe-section mb-3">
        <div class="mb-2">
          <label class="form-label fw-semibold">
            Votre nom et prénom <span class="text-danger">*</span>
            <span class="text-muted fw-normal small">(format : Prénom Nom)</span>
          </label>
          <input type="text" name="g_${this.qid}_exte_name" id="g-${this.qid}-exte-name"
                 class="form-control${this.errExte ? ' is-invalid' : ''}"
                 placeholder="ex : Marie Dupont"
                 value="${esc(this.prevExte)}"/>
          ${this.errExte ? `<div class="invalid-feedback d-block">${esc(this.errExte)}</div>` : ''}
        </div>
        <div class="alert alert-info py-2 px-3 mb-0 small">
          <i class="bi bi-info-circle me-1"></i>
          En tant que personne extérieure, vous ne pouvez pas exprimer de souhaits.
        </div>
      </div>

      <!-- Section : participant de la liste -->
      <div id="g-${this.qid}-member-sec" style="display:none" class="groupe-section mb-3">
        <div id="g-${this.qid}-wishes-container"></div>
      </div>

      <!-- Champs cachés d'état -->
      <input type="hidden" name="g_${this.qid}_identity_type" id="g-${this.qid}-ident-type"/>
      <input type="hidden" name="g_${this.qid}_identity_name" id="g-${this.qid}-ident-name"/>
    `;

    const identWrap = this.container.querySelector(`#g-${this.qid}-ident-wrap`);
    new SearchableSelect(
      identWrap,
      identityOptions,
      `__ss_g_${this.qid}_ident`,
      this.prevType === 'exte' ? 'Exté (personne extérieure)' : this.prevName,
      this.allowExte ? 'Rechercher Prénom Nom ou sélectionner Exté…' : 'Rechercher votre Prénom Nom…',
      !!this.errIdent,
    );

    identWrap.addEventListener('ss:select', e => this._onIdentitySelect(e.detail.value));

    if (this.prevType === 'exte') {
      this._showExte();
    } else if (this.prevType === 'list' && this.prevName) {
      this._showMember(this.prevName);
    }
  }

  _onIdentitySelect(value) {
    if (value === 'Exté (personne extérieure)') {
      this._identityType = 'exte';
      this._identityName = '';
      this._showExte();
    } else {
      this._identityType = 'list';
      this._identityName = value;
      this._showMember(value);
    }
  }

  _showExte() {
    this._setHidden('exte', '');
    document.getElementById(`g-${this.qid}-phone-sec`).style.display  = '';
    document.getElementById(`g-${this.qid}-exte-sec`).style.display   = '';
    document.getElementById(`g-${this.qid}-member-sec`).style.display = 'none';
  }

  _showMember(name) {
    this._setHidden('list', name);
    document.getElementById(`g-${this.qid}-phone-sec`).style.display  = '';
    document.getElementById(`g-${this.qid}-exte-sec`).style.display   = 'none';
    document.getElementById(`g-${this.qid}-member-sec`).style.display = '';
    this._renderWishes(name);
  }

  _setHidden(type, name) {
    document.getElementById(`g-${this.qid}-ident-type`).value = type;
    document.getElementById(`g-${this.qid}-ident-name`).value = name;
  }

  _renderWishes(selfName) {
    const container = document.getElementById(`g-${this.qid}-wishes-container`);
    container.innerHTML = '';
    this._wishSS = [];

    // Options pour les souhaits : tout le monde sauf soi + "Exté" + "Personne"
    const wishOptions    = this.allPart.filter(n => n !== selfName);
    const EXTE_LABEL     = 'Exté (préciser ci-dessous)';
    const PERSONNE_LABEL = 'Personne';
    const allWishOpts    = this.allowExte
      ? [PERSONNE_LABEL, EXTE_LABEL, ...wishOptions]
      : [PERSONNE_LABEL, ...wishOptions];

    for (let i = 0; i < this.maxWishes; i++) {
      const prevWishType = this._getPrevWishType(i);
      const prevWishName = this._getPrevWishName(i);
      const prevWishExte = this._getPrevWishExteName(i);

      const wishExteError = this._getWishExteError(i);
      const row = document.createElement('div');
      row.className = 'wish-row';
      row.innerHTML = `
        <div class="wish-num">${i + 1}</div>
        <div class="wish-body">
          <div class="ss-wrap" id="g-${this.qid}-wish-${i}-wrap"></div>
          <input type="hidden" name="g_${this.qid}_wish_${i}_type"  id="g-${this.qid}-wish-${i}-type"
                 value="${esc(prevWishType || 'personne')}"/>
          <input type="hidden" name="g_${this.qid}_wish_${i}_name"  id="g-${this.qid}-wish-${i}-name"
                 value="${esc(prevWishName)}"/>
          <div id="g-${this.qid}-wish-${i}-exte-sec" style="display:${prevWishType === 'exte' ? '' : 'none'}">
            <label class="form-label form-label-sm mt-1 mb-1">
              Prénom et nom de la personne extérieure <span class="text-danger">*</span>
              <span class="text-muted fw-normal">(format : Prénom Nom)</span>
            </label>
            <input type="text"
                   name="g_${this.qid}_wish_${i}_exte_name"
                   id="g-${this.qid}-wish-${i}-exte-name"
                   class="form-control form-control-sm${wishExteError ? ' is-invalid' : ''}"
                   placeholder="ex : Marie Dupont"
                   value="${esc(prevWishExte)}"/>
            ${wishExteError ? `<div class="invalid-feedback d-block">${esc(wishExteError)}</div>` : ''}
          </div>
        </div>`;
      container.appendChild(row);

      // SearchableSelect pour ce souhait
      const wishWrap = container.querySelector(`#g-${this.qid}-wish-${i}-wrap`);
      const initialWish = prevWishType === 'exte' ? EXTE_LABEL
                        : prevWishType === 'list'  ? prevWishName
                        : PERSONNE_LABEL;
      const wss = new SearchableSelect(
        wishWrap, allWishOpts,
        `__ss_g_${this.qid}_wish_${i}`,
        initialWish,
        'Choisir un souhait…',
      );
      this._wishSS.push(wss);

      // Mettre à jour les champs cachés à chaque sélection
      const capturedI = i;
      wishWrap.addEventListener('ss:select', e => {
        this._onWishSelect(capturedI, e.detail.value, EXTE_LABEL, PERSONNE_LABEL);
      });
    }
  }

  _onWishSelect(i, value, EXTE_LABEL, PERSONNE_LABEL) {
    const typeEl     = document.getElementById(`g-${this.qid}-wish-${i}-type`);
    const nameEl     = document.getElementById(`g-${this.qid}-wish-${i}-name`);
    const exteSec    = document.getElementById(`g-${this.qid}-wish-${i}-exte-sec`);

    if (value === EXTE_LABEL) {
      typeEl.value = 'exte';
      nameEl.value = '';
      exteSec.style.display = '';
    } else if (value === PERSONNE_LABEL || !value) {
      typeEl.value = 'personne';
      nameEl.value = '';
      exteSec.style.display = 'none';
    } else {
      typeEl.value = 'list';
      nameEl.value = value;
      exteSec.style.display = 'none';
    }
  }

  _getPrevWishType(i)     { return this.container.dataset[`prevWish${i}Type`]     || ''; }
  _getPrevWishName(i)     { return this.container.dataset[`prevWish${i}Name`]     || ''; }
  _getPrevWishExteName(i) { return this.container.dataset[`prevWish${i}ExteName`] || ''; }
  _getWishExteError(i)    { return this.container.dataset[`errorWish${i}Exte`]    || ''; }
}


// ════════════════════════════════════════════════════════════════════════════
// Initialisation globale
// ════════════════════════════════════════════════════════════════════════════

function initPublicForm() {

  // ── Menus déroulants avec recherche (type select) ────────────────────────
  document.querySelectorAll('[data-type="searchable-select"]').forEach(wrap => {
    const options     = JSON.parse(wrap.dataset.options || '[]');
    const name        = wrap.dataset.name        || '';
    const initial     = wrap.dataset.initial     || '';
    const placeholder = wrap.dataset.placeholder || 'Rechercher…';
    const hasError    = wrap.dataset.error === 'true';
    new SearchableSelect(wrap, options, name, initial, placeholder, hasError);
  });

  // ── Champs Groupe ────────────────────────────────────────────────────────
  document.querySelectorAll('.groupe-field').forEach(container => {
    new GroupeField(container);
  });
}


// ════════════════════════════════════════════════════════════════════════════
// Utilitaires
// ════════════════════════════════════════════════════════════════════════════

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

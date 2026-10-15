'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    status: null, docs: [], activeId: null, details: null, page: 0, current: -1,
    manual: false, polling: false, previewTimer: null, previewSeq: 0, originalSeq: 0, filter: '',
    analysisSignature: null, view: 'compare', panelCollapsed: false, savedIds: new Set(),
    manualEditId: null, batch: null, analyzing: false, autoPicked: false,
  };
  let api = null;

  // ------------------------------------------------------------ helpers
  function setError(message) {
    $('errMsg').textContent = message || '';
    $('errMsg').hidden = !message;
  }
  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.assign(node, props);
    for (const child of [].concat(children)) node.append(child);
    return node;
  }
  function options() {
    return {
      categories: [...document.querySelectorAll('#catGrid input:checked')].map((input) => input.dataset.cat),
      ocr: $('optOcr').checked, ai: $('optAi').checked,
      handwriting: $('optHandwriting').checked && state.status?.advancedInstalled,
      llmReview: $('optReview').checked && state.status?.advancedInstalled,
      faces: $('optFaces').checked, signatures: $('optSignatures').checked, propagate: $('optPropagate').checked,
      maxSecurity: $('optMaxSecurity').checked, textLayer: $('optTextLayer').checked, mode: $('optMode').value,
      uniform: $('optUniform').checked, keepName: $('optKeepName').checked, dpi: Number($('optDpi').value),
      advancedMode: $('optAdvancedMode').value,
      previewWidth: Math.min(3300, Math.max(1100, Math.round(1100 * (Number($('pageZoom').value) || 1)))),
    };
  }
  function detectionSignature(settings = null) {
    const selected = settings || options();
    return JSON.stringify({
      categories: [...selected.categories].filter((category) => category !== 'manual').sort(), ocr: selected.ocr, ai: selected.ai,
      handwriting: selected.handwriting, llmReview: selected.llmReview,
      faces: selected.faces, signatures: selected.signatures,
      propagate: selected.propagate, dpi: selected.dpi,
      advancedMode: selected.advancedMode,
    });
  }
  function renderSettingsSummary() {
    if (!state.status) return;
    $('advancedSummary').textContent = state.status.advancedInstalled ? '(instalada).' : '(opcional).';
    $('textLayerOption').hidden = !$('optMaxSecurity').checked;
    $('destinationSummary').textContent = state.analyzing ? 'Podrás guardar cuando termine el análisis del lote.'
      : $('optMaxSecurity').checked ? 'Destino: compartir fuera · máxima seguridad' : 'Destino: uso interno · se elige al guardar';
    const hasResults = state.docs.some((doc) => doc.status === 'ready');
    // Pending or failed documents are analysed first; with none left the button re-analyses everything.
    const pending = state.docs.filter((doc) => ['pending', 'failed'].includes(doc.status)).length;
    $('btnRun').dataset.scope = pending ? 'pending' : 'all';
    $('btnRun').textContent = state.polling ? 'Analizando…' : pending ? `Analizar ${pending} ${pending === 1 ? 'documento' : 'documentos'}`
      : state.docs.length ? 'Volver a analizar todo' : 'Analizar';
    const analyzedSettings = activeDoc()?.analysisSettings;
    $('settingsChangeNotice').hidden = !hasResults || !analyzedSettings || !Object.keys(analyzedSettings).length ||
      detectionSignature(analyzedSettings) === detectionSignature();
    $('sidebar').classList.toggle('reviewing', hasResults);
  }
  // Finished documents stay editable while the rest of a batch is analysed; saving or installing locks everything.
  function editLocked() { return state.saving || (state.polling && !state.analyzing); }
  function activeDoc() { return state.docs.find((doc) => doc.id === state.activeId) || null; }
  // Findings below this confidence are flagged for a closer look and get their own filter.
  const LOW_CONFIDENCE = 0.8;
  const REVIEW_FILTER = '__review';
  function visibleFindings() {
    const all = state.details?.findings || [];
    if (state.filter === REVIEW_FILTER) return all.filter((f) => f.confidence < LOW_CONFIDENCE);
    return state.filter ? all.filter((f) => f.type === state.filter) : all;
  }

  // ------------------------------------------------------------ status & options
  function renderStatus() {
    const s = state.status;
    renderSetup();
    const host = $('engineStatus');
    const advancedStatus = s.advancedInstalled
      ? el('span', { className: 'pill ok', textContent: 'IA avanzada lista' })
      : el('button', {
        className: 'pill warn status-action', type: 'button', textContent: 'Instalar IA avanzada',
        onclick: () => openSettings('tabAdvanced'),
      });
    host.replaceChildren(
      el('span', { className: 'pill', textContent: s.services.gpu ? 'GPU disponible' : 'Modo CPU',
        title: Object.entries(s.services.backends || {}).map(([key, value]) => `${key}: ${value}`).join(' · ') }),
      advancedStatus,
    );
    // Engines cannot load before the first-launch download; the setup banner explains that instead.
    const errors = s.modelsMissing ? [] : Object.entries(s.errors || {});
    const banner = $('engineErrors');
    banner.hidden = !errors.length;
    const labels = { integrity: 'Integridad', ocr: 'OCR', pii: 'IA de datos personales', faces: 'Rostros', llm: 'IA avanzada', engine: 'Motor', gpu: 'GPU' };
    banner.replaceChildren(
      el('strong', { textContent: s.blocked ? 'Procesamiento bloqueado por seguridad. ' : 'Atención: ' }),
      ...errors.map(([key, message]) => el('span', { textContent: `${labels[key] || key}: ${message}. ` })),
    );
    if (s.blocked) banner.append(el('button', { type: 'button', className: 'btn ghost small', textContent: 'Volver a comprobar',
      disabled: state.polling || state.saving, onclick: async () => { if (await api.recheck_integrity()) startPolling(); } }));
    $('btnRun').dataset.blocked = s.blocked ? '1' : '';
    for (const label of document.querySelectorAll('.toggle.advanced')) {
      label.classList.toggle('unavailable', !s.advancedInstalled);
      label.querySelector('input').disabled = !s.advancedInstalled;
    }
    renderSettingsSummary();
    const box = $('advancedBox');
    if (s.advancedInstalled) {
      box.textContent = `IA avanzada instalada (${s.advancedLabel}): lectura de manuscritos y revisión contextual.`;
      return;
    }
    box.replaceChildren(
      el('p', { textContent: `La IA avanzada (${s.advancedLabel}) lee letra manuscrita y hace una revisión contextual. Solo se descargan modelos; ningún documento sale del equipo.` }),
      el('button', { className: 'btn ghost small', id: 'btnInstall', textContent: 'Descargar IA avanzada', onclick: installAdvanced }),
      el('button', { className: 'btn ghost small', textContent: 'Importar paquete sin conexión (.zip)', onclick: importAdvanced }),
      el('div', { className: 'progress-track', id: 'installTrack', hidden: true }, [el('div', { className: 'progress-fill', id: 'installFill' })]),
      el('p', { id: 'installText' }),
    );
  }

  // ------------------------------------------------------------ first-launch model download
  function renderSetup() {
    const s = state.status;
    const setup = s.setup || {};
    const banner = $('setupBanner');
    banner.hidden = !s.modelsMissing && !setup.running;
    if (banner.hidden) return;
    const failed = Boolean(setup.error);
    $('setupText').replaceChildren(
      el('span', { textContent: setup.message || 'Faltan los modelos de IA necesarios (≈ 700 MB). Solo se descargan modelos; ningún documento sale del equipo.' }),
      ...(setup.running ? [] : [
        el('button', { type: 'button', className: 'btn ghost small', textContent: 'Reintentar la descarga', onclick: retrySetup }),
        el('button', { type: 'button', className: 'btn ghost small', textContent: 'Importar paquete sin conexión (.zip)', onclick: importSetup }),
      ]),
    );
    $('setupFill').style.width = `${setup.percent || 0}%`;
    banner.classList.toggle('failed', failed);
    if (setup.running) watchSetup();
  }
  async function importSetup() {
    const result = await api.import_advanced();
    if (result.ok) await refreshStatus();
    else if (result.message) setError(result.message);
  }
  async function retrySetup() {
    await api.install_required();
    await refreshStatus();
  }
  function watchSetup() {
    if (state.watchingSetup) return;
    state.watchingSetup = true;
    const tick = async () => {
      const info = await api.poll();
      state.status.setup = info.setup || {};
      if (state.status.setup.running) { renderSetup(); setTimeout(tick, 500); return; }
      state.watchingSetup = false;
      await refreshStatus();
    };
    setTimeout(tick, 500);
  }

  function buildCategories() {
    const grid = $('catGrid');
    grid.replaceChildren();
    for (const category of state.status.categories) {
      const input = el('input', { type: 'checkbox', checked: category.default });
      input.dataset.cat = category.key;
      grid.append(el('label', { className: 'cat' }, [input, el('span', { textContent: category.label })]));
    }
    renderSettingsSummary();
    const filter = $('typeFilter');
    filter.append(el('option', { value: REVIEW_FILTER, textContent: 'Por revisar' }));
    filter.options[1].dataset.label = 'Por revisar';
    for (const category of state.status.categories) {
      const option = el('option', { value: category.key, textContent: category.label });
      option.dataset.label = category.label;
      filter.append(option);
    }
  }

  async function installAdvanced() {
    await api.install_advanced();
    $('installTrack').hidden = false;
    startPolling();
  }
  async function importAdvanced() {
    const result = await api.import_advanced();
    if (result.ok) { state.status = await api.status(); renderStatus(); }
    else if (result.message) setError(result.message);
  }

  // ------------------------------------------------------------ documents
  function renderQueue() {
    const queue = $('documentQueue');
    // The queue is rebuilt on every poll; keep a password being typed and its focus.
    const drafts = new Map([...queue.querySelectorAll('.unlock-row input')].map((input) => [input.dataset.doc, input.value]));
    const focused = document.activeElement?.closest?.('.unlock-row') ? document.activeElement : null;
    const focusedDoc = focused?.dataset.doc;
    const caret = focused?.selectionStart;
    queue.replaceChildren();
    for (const doc of state.docs) {
      const advanced = doc.advanced === 'running' ? ' · IA avanzada en curso' : doc.advanced === 'pending' ? ' · IA avanzada pendiente' : '';
      const status = doc.status === 'ready' ? `${doc.pages} pág. · ${doc.findings} hallazgos${advanced}${doc.saved ? ' · guardado' : ''}${doc.error ? ' · último análisis fallido' : ''}`
        : doc.status === 'processing' ? 'Analizando…'
          : doc.status === 'failed' ? `Error: ${doc.error}`
            : doc.status === 'locked' ? 'Protegido con contraseña' : `${Math.round(doc.size / 1024)} KB · pendiente`;
      const select = el('button', { className: 'document-select', type: 'button', disabled: false }, [
        el('span', { className: 'document-name', textContent: doc.name }),
        el('span', { className: `document-status ${doc.status}`, textContent: status }),
      ]);
      select.addEventListener('click', () => selectDoc(doc.id));
      const remove = el('button', { className: 'document-remove', type: 'button', textContent: 'Quitar', disabled: state.saving || state.polling });
      remove.setAttribute('aria-label', `Quitar ${doc.name}`);
      remove.addEventListener('click', async () => {
        if (doc.reviewed && !doc.saved && !window.confirm('Este documento tiene una revisión sin guardar. ¿Quieres quitarlo y descartarla?')) return;
        if (await api.remove(doc.id)) {
          if (state.activeId === doc.id) { state.activeId = null; state.details = null; }
          await refreshDocuments();
        }
      });
      const item = el('div', { className: 'document-item' + (doc.id === state.activeId ? ' active' : '') }, [select, remove]);
      if (doc.status === 'locked') {
        const input = el('input', { type: 'password', placeholder: 'Contraseña del PDF', className: 'password' });
        input.setAttribute('aria-label', `Contraseña de ${doc.name}`);
        input.dataset.doc = doc.id;
        input.value = drafts.get(String(doc.id)) || '';
        const unlock = el('button', { className: 'btn ghost small', type: 'button', textContent: 'Abrir' });
        const submit = async () => {
          const result = await api.unlock(doc.id, input.value);
          input.value = '';
          if (!result.ok) { setError(result.message); return; }
          setError('');
          await refreshDocuments();
        };
        unlock.addEventListener('click', submit);
        input.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
        item.append(el('div', { className: 'unlock-row' }, [input, unlock]));
      }
      queue.append(item);
      if (focusedDoc === String(doc.id)) {
        const input = item.querySelector('.unlock-row input');
        input.focus();
        if (caret !== undefined && caret !== null) input.setSelectionRange(caret, caret);
      }
    }
    $('btnRun').disabled = !state.docs.length || state.polling || $('btnRun').dataset.blocked === '1';
    renderSettingsSummary();
  }

  async function refreshDocuments() {
    state.docs = await api.documents();
    if (!state.activeId && state.docs.length) state.activeId = state.docs[0].id;
    renderQueue();
    await showActive();
  }

  async function addDocuments(picker) {
    setError('');
    try { await picker(); }
    catch (error) { setError(error.message || String(error)); }
    finally { await refreshDocuments(); }
  }

  async function selectDoc(id) {
    state.activeId = id;
    state.details = null;
    state.page = 0;
    state.current = -1;
    state.manualEditId = null;
    $('btnCoordinates').textContent = 'Crear zona';
    renderQueue();
    await showActive();
  }

  async function showActive() {
    const doc = activeDoc();
    const ready = doc?.status === 'ready';
    $('emptyPreview').hidden = ready;
    $('resultsCard').hidden = !ready;
    if (!ready) {
      const heading = $('emptyPreview').querySelector('h2');
      const text = $('emptyPreview').querySelector('p');
      if (doc?.status === 'failed') { heading.textContent = 'No se pudo procesar'; text.textContent = doc.error; }
      else if (state.analyzing && ['processing', 'pending'].includes(doc?.status)) {
        heading.textContent = 'Analizando documentos…';
        text.textContent = 'Cada documento se puede revisar en cuanto termina; elígelo en la lista.';
      }
      else if (state.docs.length) { heading.textContent = 'Documentos preparados'; text.textContent = 'Ajusta las opciones y pulsa «Analizar documentos».'; }
      else { heading.textContent = 'Añade tus documentos'; text.textContent = 'PDF, fotos o escaneos. Nada sale de este equipo.'; }
      return;
    }
    if (!state.details || state.details.id !== doc.id || state.details.revision !== doc.revision) {
      const sameDocument = state.details?.id === doc.id;   // refreshed (the advanced AI added data): stay on the page
      state.details = await api.details(doc.id);
      if (!sameDocument) { state.page = 0; state.current = -1; }
      state.page = Math.min(state.page, state.details.pages.length - 1);
    }
    renderDetails();
  }

  // ------------------------------------------------------------ processing & polling
  async function run() {
    setError('');
    const scope = $('btnRun').dataset.scope || 'pending';
    const ids = state.docs.filter((doc) => doc.status !== 'locked' &&
      (scope === 'all' || ['pending', 'failed'].includes(doc.status))).map((doc) => doc.id);
    if (!ids.length) { setError('No hay documentos que analizar. Añade documentos o desbloquea los protegidos.'); return; }
    if (state.docs.some((doc) => ids.includes(doc.id) && doc.reviewed) &&
        !window.confirm('Se conservarán las zonas manuales si el archivo y sus páginas no han cambiado. Los hallazgos automáticos y su selección se recalcularán. ¿Continuar?')) return;
    let started;
    try { started = await api.process(options(), ids); }
    catch (error) { setError(error.message || String(error)); return; }
    if (!started) { setError('Ya hay un proceso en curso.'); return; }
    state.analysisSignature = detectionSignature();
    state.details = null;
    setManual(false);
    $('resultsCard').hidden = true;
    $('emptyPreview').hidden = false;
    $('emptyPreview').querySelector('h2').textContent = 'Analizando documentos…';
    $('emptyPreview').querySelector('p').textContent = 'Cada documento se puede revisar en cuanto termina.';
    state.analyzing = true;
    state.autoPicked = false;
    startPolling();
  }

  function startPolling() {
    if (state.polling) return;
    state.polling = true;
    if (state.analyzing) setAnalysisLock(true); else setSaving(true);
    $('progressCard').hidden = false;
    $('btnCancel').hidden = false;
    $('btnRun').disabled = true;
    $('btnRun').textContent = 'Analizando…';
    const tick = async () => {
      const info = await api.poll();
      $('progressFill').style.width = `${info.progress.percent || 0}%`;
      $('progressText').textContent = info.progress.message || '';
      state.docs = info.documents;
      renderQueue();
      if (info.install && Object.keys(info.install).length && $('installText')) {
        $('installText').textContent = info.install.message || '';
        $('installFill').style.width = `${info.install.percent || 0}%`;
        if (info.install.done) { state.status = await api.status(); renderStatus(); }
      }
      const installing = info.install && info.install.running;
      if (info.busy || installing) {
        if (state.analyzing) await followAnalysis();
        setTimeout(tick, 400);
        return;
      }
      state.polling = false;
      if (state.analyzing) { state.analyzing = false; setAnalysisLock(false); } else setSaving(false);
      state.status = await api.status();
      renderStatus();
      $('progressCard').hidden = true;
      $('btnCancel').hidden = true;
      renderQueue();
      const firstReady = state.docs.find((doc) => doc.status === 'ready');
      if (activeDoc()?.status !== 'ready' && firstReady) state.activeId = firstReady.id;
      const failed = state.docs.filter((doc) => doc.error);
      if (failed.length) setError(failed.map((doc) => `${doc.name}: ${doc.error}`).join(' · '));
      await showActive();
    };
    tick();
  }

  // While a batch is analysed: open the first finished document, and refresh the open one when its review changes.
  async function followAnalysis() {
    const doc = activeDoc();
    if (!state.autoPicked && !state.details) {
      const ready = doc?.status === 'ready' ? doc : state.docs.find((item) => item.status === 'ready');
      if (ready) {
        state.autoPicked = true;
        state.activeId = ready.id;
        renderQueue();
        await showActive();
      }
      return;
    }
    if (state.details && (doc?.status !== 'ready' || doc.revision !== state.details.revision)) {
      if (doc?.status !== 'ready') state.details = null;
      await showActive();
    }
  }
  function setAnalysisLock(on) {
    const controls = document.querySelectorAll('#btnOpenSave, #btnRailSave, #btnPdf, #btnAll, #btnCsv, #btnJson, #btnRetryBatch, '
      + '#btnReset, #btnAddFiles, #btnAddFolder, #detectionDetails input, #detectionDetails select');
    for (const control of controls) {
      if (on) {
        control.dataset.disabledBeforeAnalysis = String(control.disabled);
        control.disabled = true;
      } else if ('disabledBeforeAnalysis' in control.dataset) {
        control.disabled = control.dataset.disabledBeforeAnalysis === 'true';
        delete control.dataset.disabledBeforeAnalysis;
      }
    }
    renderSettingsSummary();
  }

  // ------------------------------------------------------------ review
  function renderDetails() {
    const d = state.details;
    const findings = d.findings;
    if (state.manualEditId && !findings.some((f) => f.id === state.manualEditId && f.type === 'manual')) {
      state.manualEditId = null;
      $('btnCoordinates').textContent = 'Crear zona';
    }
    const enabled = findings.filter((f) => f.enabled);
    $('currentFileName').textContent = d.name;
    const faces = findings.filter((f) => f.type === 'face').length;
    const stats = [
      [d.pages.length, d.pages.length === 1 ? 'página' : 'páginas'], [findings.length, 'hallazgos'],
      [enabled.length, 'incluidos'], ...(faces ? [[faces, faces === 1 ? 'rostro' : 'rostros']] : []),
      [`${d.seconds} s`, 'de análisis'],
    ];
    $('statsHost').replaceChildren(...stats.flatMap(([value, label], index) => [
      ...(index ? [' · '] : []), el('b', { textContent: String(value) }), ` ${label}`,
    ]));
    const lowText = d.nativeChars / Math.max(1, d.pages.length) < 30;
    $('detectionNotice').hidden = !lowText && !d.notes.length;
    $('detectionNotice').textContent = lowText ? 'Documento escaneado o con poco texto: revisa con atención cada página y usa «Ocultar zona» si falta algo.' : '';
    $('notes').textContent = d.notes.join(' · ');
    $('btnUndo').disabled = !d.history?.undo || editLocked();
    $('btnRedo').disabled = !d.history?.redo || editLocked();
    renderFilterOptions(findings);
    renderReport(d.report);
    renderTable();
    renderPage();
  }

  function renderFilterOptions(findings) {
    const counts = new Map();
    for (const f of findings) counts.set(f.type, (counts.get(f.type) || 0) + 1);
    counts.set(REVIEW_FILTER, findings.filter((f) => f.confidence < LOW_CONFIDENCE).length);
    const filter = $('typeFilter');
    filter.options[0].textContent = `Todos los tipos (${findings.length})`;
    for (const option of [...filter.options].slice(1)) {
      const count = counts.get(option.value) || 0;
      option.textContent = `${option.dataset.label} (${count})`;
      option.hidden = count === 0 && option.value !== state.filter;
    }
  }

  function renderReport(report, savedPath = null) {
    const card = $('verifyCard');
    if (!report) { card.hidden = true; return; }
    card.hidden = false;
    card.className = 'verify-card ' + (report.ok ? 'ok' : 'fail');
    const children = [el('strong', {
      textContent: report.ok
        ? `Verificación superada: 0 restos en ${report.objects} objetos y ${report.pages} páginas (${report.values} valores comprobados).`
        : `Verificación fallida: ${report.leaks.length} resto(s). No se ha guardado el archivo.`,
    })];
    if (report.ok && savedPath) children.push(el('p', { className: 'saved-path', textContent: `Guardado en ${savedPath}` }));
    if (!report.ok) {
      children.push(el('ul', {}, report.leaks.map((leak) => {
        const located = leak.page !== null && leak.page !== undefined && leak.view && leak.view.length;
        // The engine masks original values ("…") so they never reach logs; only show a value it kept.
        const value = leak.value && leak.value !== '…' ? ` «${leak.value}»` : '';
        const text = `${leak.where}: ${leak.detail} (${leak.check})${value}`
          + (located ? ' · ver en la página' : leak.page === null ? ' · en la estructura del archivo' : '');
        if (!located) return el('li', { textContent: text });
        const link = el('button', { type: 'button', className: 'leak-link', textContent: text });
        link.addEventListener('click', () => { state.page = leak.page; renderPage(); });
        return el('li', {}, [link]);
      })));
      children.push(el('p', { textContent: 'Los restos están marcados en rojo sobre el resultado. Añade una zona manual encima o activa «Voy a compartirlo fuera» y vuelve a guardar.' }));
    }
    if (report.warnings?.length) {
      children.push(el('ul', { className: 'warn-list' }, report.warnings.map((w) => el('li', { textContent: w }))));
    }
    card.replaceChildren(...children);
  }

  function renderTable() {
    if (!state.details) return;
    const body = $('rowsBody');
    body.replaceChildren();
    const list = visibleFindings();
    list.forEach((f, index) => {
      const checkbox = el('input', { type: 'checkbox', checked: f.enabled, disabled: state.saving });
      checkbox.setAttribute('aria-label', `Incluir ${f.label} de la página ${f.page + 1}`);
      checkbox.addEventListener('click', (event) => event.stopPropagation());
      checkbox.addEventListener('change', () => toggle([f.id], checkbox.checked));
      const confidence = Math.round(f.confidence * 100);
      const conf = el('span', { className: 'confidence' + (f.confidence < LOW_CONFIDENCE ? ' low' : ''), textContent: f.confidence < LOW_CONFIDENCE ? `${confidence} % · revisar` : `${confidence} %` });
      conf.title = f.warning === 'checksum' ? 'Formato reconocido; dígito de control no válido' : (f.detail || '');
      const meta = el('div', { className: 'finding-meta' }, [
        el('span', { className: 'type-badge', textContent: f.label }), el('span', { textContent: `pág. ${f.page + 1}` }), conf,
      ]);
      const value = el('td', { className: 'orig' }, [
        meta, el('span', { className: 'orig-value', textContent: f.value ?? `(${f.detail || f.label})` }),
        el('span', { className: 'src', textContent: sourceLabel(f.source) }),
      ]);
      const row = el('tr', { className: (f.enabled ? '' : 'off') + (index === state.current ? ' current' : '') }, [
        el('td', {}, [checkbox]), value, el('td', { className: 'tok', textContent: f.token }),
      ]);
      row.addEventListener('click', () => focusFinding(index));
      if (f.type === 'manual') {
        const del = el('button', { className: 'btn ghost small', textContent: 'Borrar', disabled: state.saving });
        del.addEventListener('click', async (event) => {
          event.stopPropagation();
          if (state.saving) return;
          await api.remove_manual(state.details.id, f.id);
          await reloadReview();
        });
        value.append(del);
      }
      body.append(row);
    });
    const enabled = state.details.findings.filter((f) => f.enabled).length;
    $('rowsCount').textContent = `${enabled} de ${state.details.findings.length} se ocultarán`;
    $('railCount').textContent = String(enabled);
  }

  function sourceLabel(source) {
    return {
      text: 'texto del PDF', ai: 'IA de datos personales', ocr: 'OCR', handwriting: 'manuscrito', propagation: 'repetición',
      llm: 'revisión IA', face: 'detector de rostros', signature: 'detector de firmas', manual: 'manual', form: 'formulario',
    }[source] || source;
  }

  async function toggle(ids, enabled) {
    if (!state.details || state.saving) return;
    await api.set_enabled(state.details.id, ids, enabled);
    await reloadReview();
  }

  async function reloadReview() {
    const id = state.details?.id;
    if (!id) return;
    const details = await api.details(id);
    state.docs = await api.documents();
    if (state.details?.id !== id) return;
    state.details = details;
    state.savedIds.delete(id);
    renderQueue();
    renderDetails();
  }

  async function restoreReview(redo = false) {
    if (!state.details || editLocked()) return;
    try {
      await api.restore_review(state.details.id, redo);
      await reloadReview();
    } catch (error) { setError(error.message || String(error)); }
  }

  function focusFinding(index) {
    const list = visibleFindings();
    if (!list.length) return;
    state.current = (index + list.length) % list.length;
    const f = list[state.current];
    if (f.page !== state.page) { state.page = f.page; renderPage(); } else { drawBoxes(); }
    renderTable();
    state.manualEditId = f.type === 'manual' ? f.id : null;
    $('btnCoordinates').textContent = state.manualEditId ? 'Actualizar zona seleccionada' : 'Crear zona';
    if (state.manualEditId) {
      const [x0, y0, x1, y1] = f.view[0];
      for (const [id, value] of [['manualX', x0], ['manualY', y0], ['manualWidth', x1 - x0], ['manualHeight', y1 - y0]]) $(id).value = (value * 100).toFixed(2);
    }
    body().querySelector('tr.current')?.scrollIntoView({ block: 'nearest' });
  }
  const body = () => $('rowsBody');

  async function renderPage() {
    const d = state.details;
    if (!d) return;
    state.page = Math.max(0, Math.min(state.page, d.pages.length - 1));
    if (state.manualEditId && !d.findings.some((f) => f.id === state.manualEditId && f.page === state.page)) {
      state.manualEditId = null;
      $('btnCoordinates').textContent = 'Crear zona';
    }
    $('pageIndicator').textContent = `Página ${state.page + 1} de ${d.pages.length}`;
    $('btnPrevPage').disabled = state.page === 0;
    $('btnNextPage').disabled = state.page === d.pages.length - 1;
    const zoom = Number($('pageZoom').value);
    for (const id of ['originalWrap', 'resultWrap']) {
      const wrap = $(id);
      wrap.style.width = zoom ? `${d.pages[state.page].width * zoom}px` : '';
      wrap.classList.toggle('zoomed', !!zoom);
      wrap.closest('figure').classList.toggle('zoomed-page', !!zoom);
    }
    // Separate counters: an output-option change re-renders only the result and must not discard
    // the original of a page or document that is still loading.
    const seq = ++state.originalSeq;
    setManual(false);
    $('originalWrap').classList.add('loading-preview');
    $('originalImg').removeAttribute('src');
    delete $('originalImg').dataset.doc;
    for (const node of $('originalWrap').querySelectorAll('.box')) node.remove();
    ++state.previewSeq;  // a result still rendering belongs to the previous page
    clearTimeout(state.previewTimer);
    $('resultWrap').classList.add('loading-preview');
    $('resultImg').removeAttribute('src');
    const src = await api.page_image(d.id, state.page, 'original', options());
    if (seq !== state.originalSeq || state.details !== d) return;
    $('originalImg').src = src;
    $('originalImg').dataset.doc = d.id;
    $('originalWrap').classList.remove('loading-preview');
    drawBoxes();
    schedulePreview();
  }

  function schedulePreview() {
    clearTimeout(state.previewTimer);
    const seq = ++state.previewSeq;
    const wrap = $('resultWrap');
    wrap.classList.add('loading-preview');
    $('resultImg').removeAttribute('src');  // never show the original while the result is generated
    state.previewTimer = setTimeout(async () => {
      if (!state.details) return;
      const id = state.details.id;
      try {
        const src = await api.page_image(id, state.page, 'result', options());
        if (seq === state.previewSeq) {
          $('resultImg').src = src;
          $('resultImg').dataset.doc = id;
          wrap.classList.remove('loading-preview');
          drawLeaks();
        }
      } catch (error) {
        setError(`No se pudo generar la vista previa: ${error.message || error}`);
        wrap.classList.remove('loading-preview');
      }
    }, 200);
  }

  function drawLeaks() {
    const wrap = $('resultWrap');
    for (const node of wrap.querySelectorAll('.leak-box')) node.remove();
    const report = state.details && state.details.report;
    if (!report || report.ok) return;
    for (const leak of report.leaks) {
      if (leak.page !== state.page || !leak.view) continue;
      for (const [x0, y0, x1, y1] of leak.view) {
        const box = el('div', { className: 'leak-box', title: `${leak.detail} (${leak.check})` });
        Object.assign(box.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` });
        wrap.append(box);
      }
    }
  }

  function drawBoxes() {
    if (!state.details) return;
    drawLeaks();
    const wrap = $('originalWrap');
    for (const node of wrap.querySelectorAll('.box')) node.remove();
    const list = visibleFindings();
    const current = list[state.current];
    for (const f of state.details.findings) {
      if (f.page !== state.page) continue;
      for (const [x0, y0, x1, y1] of f.view) {
        const box = el('div', {
          className: `box ${f.type}` + (f.enabled ? '' : ' off') + (f.confidence < LOW_CONFIDENCE ? ' low' : '') + (current && current.id === f.id ? ' current' : ''),
          title: `${f.label} · ${f.token} · ${Math.round(f.confidence * 100)} %`,
        });
        Object.assign(box.style, { left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` });
        box.addEventListener('click', (event) => { event.stopPropagation(); toggle([f.id], !f.enabled); });
        wrap.append(box);
      }
    }
  }

  // ------------------------------------------------------------ manual zones
  function installManual(wrap) {
    let start = null;
    let selection = null;
    wrap.addEventListener('pointerdown', (event) => {
      if (!state.manual || state.saving || wrap.classList.contains('loading-preview') || event.button !== 0) return;
      event.preventDefault();
      const bounds = wrap.getBoundingClientRect();
      start = { x: event.clientX - bounds.left, y: event.clientY - bounds.top,
        doc: state.details.id, page: state.page, seq: state.originalSeq };
      selection = el('div', { className: 'manual-selection' });
      wrap.append(selection);
      wrap.setPointerCapture(event.pointerId);
    });
    wrap.addEventListener('pointermove', (event) => {
      if (!start) return;
      const bounds = wrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left));
      const y = Math.max(0, Math.min(bounds.height, event.clientY - bounds.top));
      Object.assign(selection.style, {
        left: `${Math.min(start.x, x)}px`, top: `${Math.min(start.y, y)}px`,
        width: `${Math.abs(x - start.x)}px`, height: `${Math.abs(y - start.y)}px`,
      });
    });
    wrap.addEventListener('pointerup', async () => {
      if (!start) return;
      const draft = start;
      const bounds = wrap.getBoundingClientRect();
      const left = parseFloat(selection.style.left) || 0;
      const top = parseFloat(selection.style.top) || 0;
      const width = parseFloat(selection.style.width) || 0;
      const height = parseFloat(selection.style.height) || 0;
      selection.remove();
      start = null;
      if (state.saving || state.details?.id !== draft.doc || state.page !== draft.page || state.originalSeq !== draft.seq || width < 6 || height < 6) return;
      const rect = [left / bounds.width, top / bounds.height, (left + width) / bounds.width, (top + height) / bounds.height];
      await api.add_manual(state.details.id, state.page, rect);
      setManual(false);
      await reloadReview();
    });
    wrap.addEventListener('pointercancel', () => { selection?.remove(); start = null; selection = null; });
  }
  function setManual(on) {
    if (on && state.saving) return;
    state.manual = on;
    $('btnManual').setAttribute('aria-pressed', String(on));
    $('btnManualLabel').textContent = on ? 'Arrastra sobre la página…' : 'Ocultar zona';
    $('originalWrap').classList.toggle('manual-mode', on);
    $('resultWrap').classList.toggle('manual-mode', on);
  }

  // ------------------------------------------------------------ view & findings panel
  function setView(view) {
    state.view = view;
    $('comparisonGrid').classList.toggle('result-only', view === 'result');
    $('btnViewCompare').setAttribute('aria-pressed', String(view === 'compare'));
    $('btnViewResult').setAttribute('aria-pressed', String(view === 'result'));
  }
  function setPanel(collapsed, { focus = false } = {}) {
    state.panelCollapsed = collapsed;
    $('resultsCard').classList.toggle('panel-collapsed', collapsed);
    $('btnPanelExpand').setAttribute('aria-expanded', String(!collapsed));
    $('btnPanelCollapse').setAttribute('aria-expanded', String(!collapsed));
    try { localStorage.setItem('anonimato.panelCollapsed', collapsed ? '1' : '0'); } catch { /* storage unavailable */ }
    if (focus) (collapsed ? $('btnPanelExpand') : $('btnPanelCollapse')).focus();
  }

  // ------------------------------------------------------------ export
  function setSaving(on) {
    state.saving = on;
    for (const id of ['btnPdf', 'btnRailSave', 'btnOpenSave', 'btnAll', 'btnCsv', 'btnJson']) $(id).disabled = on;
    if (on) setManual(false);
    // Restore each control's previous state instead of enabling unavailable controls after saving.
    for (const control of document.querySelectorAll('#detectionDetails input, #detectionDetails select, #rowsBody input, #rowsBody button, #manualForm input, #manualForm button, #btnUndo, #btnRedo, #btnRetryBatch, #btnAllOn, #btnAllOff, #btnManual, #btnRun, #optMode, #optInternal, #optMaxSecurity, #optUniform, #optTextLayer, #optKeepName')) {
      if (on) {
        control.dataset.disabledBeforeSave = String(control.disabled);
        control.disabled = true;
      } else if ('disabledBeforeSave' in control.dataset) {
        control.disabled = control.dataset.disabledBeforeSave === 'true';
        delete control.dataset.disabledBeforeSave;
      }
    }
  }
  // Every output choice lives in the save dialog, next to the button that uses it.
  function openSave() {
    if (!state.details || state.saving || state.polling || $('saveDialog').open) return;
    const enabled = state.details.findings.filter((f) => f.enabled).length;
    const pages = state.details.pages.length;
    $('saveTitle').textContent = `Guardar ${state.details.name}`;
    $('saveSummary').textContent = `${enabled === 1 ? 'Se ocultará 1 dato' : `Se ocultarán ${enabled} datos`} en ${pages} ${pages === 1 ? 'página' : 'páginas'}. ` +
      'Antes de escribir el archivo se comprueba que ninguno siga legible.';
    $('saveDialog').showModal();
    ($('optMaxSecurity').checked ? $('optMaxSecurity') : $('optInternal')).focus();
  }
  // Detection settings live in their own dialog, opened from the gear at the top right.
  const SETTINGS_TABS = ['tabData', 'tabMethods', 'tabAnalysis', 'tabAdvanced'];
  function selectTab(id, { focus = false } = {}) {
    for (const tabId of SETTINGS_TABS) {
      const tab = $(tabId), selected = tabId === id;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      $(tab.getAttribute('aria-controls')).hidden = !selected;
    }
    if (focus) $(id).focus();
  }
  function openSettings(tab = null) {
    if (tab) selectTab(tab);
    if ($('settingsDialog').open) return;
    $('settingsDialog').showModal();
    $(SETTINGS_TABS.find((id) => $(id).getAttribute('aria-selected') === 'true')).focus();
  }
  function closeSave() {
    if ($('saveDialog').open) $('saveDialog').close();
  }
  async function savePdf() {
    if (!state.details || state.saving) return;
    closeSave();
    const docId = state.details.id;
    setError('');
    setSaving(true);
    $('progressCard').hidden = false;
    $('progressText').textContent = 'Generando y verificando…';
    const ticker = setInterval(async () => {
      const info = await api.poll();
      if (info.busy) {
        $('progressFill').style.width = `${info.progress.percent || 0}%`;
        $('progressText').textContent = info.progress.message || 'Generando y verificando…';
      }
    }, 500);
    try {
      const result = await api.save_pdf(docId, options());
      if (state.details?.id === docId) {
        state.details.report = result.report || null;
        renderReport(state.details.report, result.ok && result.saved ? result.path : null);
        drawLeaks();
      }
      if (!result.ok) setError(result.message);
      else if (result.saved) {
        $('progressText').textContent = `Guardado: ${result.path}`;
        state.savedIds.add(docId);
        state.docs = await api.documents();
        renderQueue();
      }
    } catch (error) {
      setError(`Error al guardar: ${error.message || error}`);
    } finally {
      clearInterval(ticker);
      setSaving(false);
      setTimeout(() => { if (!state.polling) $('progressCard').hidden = true; }, 2500);
    }
  }
  async function saveAll(retry = false) {
    if (!state.details || state.saving) return;
    const retryIds = state.batch?.results.filter((entry) => !entry.ok && state.docs.some((doc) => doc.id === entry.id && doc.status === 'ready')).map((entry) => entry.id) || [];
    if (retry && !retryIds.length) { setError('No hay documentos disponibles para reintentar.'); return; }
    closeSave();
    setError('');
    setSaving(true);
    $('progressCard').hidden = false;
    const ticker = setInterval(async () => {
      const info = await api.poll();
      if (info.busy) {
        $('progressFill').style.width = `${info.progress.percent || 0}%`;
        $('progressText').textContent = info.progress.message || '';
      }
    }, 500);
    let result;
    try {
      result = retry && state.batch ? await api.export_folder(state.batch.folder, options(), retryIds) : await api.save_all(options());
    } catch (error) {
      setError(`Error al guardar: ${error.message || error}`);
      return;
    } finally {
      clearInterval(ticker);
      setSaving(false);
    }
    if (result.message) setError(result.message);
    else if (result.folder) {
      $('progressCard').hidden = false;
      $('progressText').textContent = `${result.saved} guardados${result.failed ? `, ${result.failed} pendientes de corregir` : ''} en ${result.folder}`;
      // The batch summary in the findings panel keeps the details; the sidebar only flashes the outcome.
      setTimeout(() => { if (!state.polling && !state.saving) $('progressCard').hidden = true; }, 2500);
    }
    if (result.folder) {
      const entries = new Map((retry ? state.batch?.results || [] : []).map((entry) => [entry.id, entry]));
      for (const entry of result.results) entries.set(entry.id, entry);
      state.batch = result;
      state.batch.results = [...entries.values()];
      $('batchResults').hidden = false;
      $('batchSummary').textContent = result.reportPath ? `Informe del último intento: ${result.reportPath}` : (result.message || 'Informe no guardado');
      const labels = { saved: 'Guardado', verification_blocked: 'Bloqueado por verificación', processing_error: 'Error de procesamiento', write_error: 'Error al escribir' };
      $('batchList').replaceChildren(...state.batch.results.map((entry) => el('li', { textContent: `${state.docs.find((doc) => doc.id === entry.id)?.name || entry.documento}: ${labels[entry.status] || entry.status}${entry.error ? ` · ${entry.error}` : ''}` })));
      $('btnRetryBatch').hidden = !state.batch.results.some((entry) => !entry.ok);
    }
    state.docs = await api.documents();
    renderQueue();
    state.details = await api.details(state.details.id);
    renderDetails();
  }
  async function saveLog(format) {
    if (!state.details) return;
    try { await api.save_log(state.details.id, format, $('optLogOriginals').checked, $('optLogCoords').checked); }
    catch (error) { setError(`Error al guardar: ${error.message || error}`); }
  }

  // ------------------------------------------------------------ wiring
  function wire() {
    for (const input of document.querySelectorAll('#detectionDetails input, #detectionDetails select, #optInternal, #optMaxSecurity')) {
      input.addEventListener('change', renderSettingsSummary);
    }
    $('btnAddFiles').addEventListener('click', () => addDocuments(() => api.pick_files()));
    $('btnAddFolder').addEventListener('click', () => addDocuments(() => api.pick_folder(false)));
    $('btnRun').addEventListener('click', run);
    $('btnCancel').addEventListener('click', () => api.cancel());
    $('btnPdf').addEventListener('click', savePdf);
    $('btnAll').addEventListener('click', () => saveAll());
    $('btnRetryBatch').addEventListener('click', () => saveAll(true));
    $('btnUndo').addEventListener('click', () => restoreReview());
    $('btnRedo').addEventListener('click', () => restoreReview(true));
    $('pageZoom').addEventListener('change', renderPage);
    $('btnNewZone').addEventListener('click', () => { state.manualEditId = null; $('btnCoordinates').textContent = 'Crear zona'; });
    $('manualForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!state.details || editLocked()) return;
      const [x, y, width, height] = ['manualX', 'manualY', 'manualWidth', 'manualHeight'].map((id) => Number($(id).value) / 100);
      if (x + width > 1 || y + height > 1) { setError('La zona debe quedar dentro de la página.'); return; }
      try {
        const rect = [x, y, x + width, y + height];
        if (state.manualEditId && state.details.findings.some((f) => f.id === state.manualEditId && f.type === 'manual')) await api.update_manual(state.details.id, state.manualEditId, state.page, rect);
        else await api.add_manual(state.details.id, state.page, rect);
        setError('');
        await reloadReview();
      } catch (error) { setError(error.message || String(error)); }
    });
    $('btnCsv').addEventListener('click', () => saveLog('csv'));
    $('btnJson').addEventListener('click', () => saveLog('json'));
    $('optLogOriginals').addEventListener('change', () => { $('logWarning').hidden = !$('optLogOriginals').checked; });
    $('btnReset').addEventListener('click', async () => {
      if (state.docs.some((doc) => doc.reviewed && !doc.saved) && !window.confirm('Hay revisiones sin guardar. ¿Quieres vaciar la lista y descartarlas?')) return;
      if (await api.clear()) { state.activeId = null; state.details = null; state.analysisSignature = null; await refreshDocuments(); }
    });
    $('btnPrevPage').addEventListener('click', () => { state.page -= 1; renderPage(); });
    $('btnNextPage').addEventListener('click', () => { state.page += 1; renderPage(); });
    $('btnManual').addEventListener('click', () => setManual(!state.manual));
    $('btnViewCompare').addEventListener('click', () => setView('compare'));
    $('btnViewResult').addEventListener('click', () => setView('result'));
    $('btnPanelCollapse').addEventListener('click', () => setPanel(true, { focus: true }));
    $('btnPanelExpand').addEventListener('click', () => setPanel(false, { focus: true }));
    $('btnRailSave').addEventListener('click', openSave);
    $('btnOpenSave').addEventListener('click', openSave);
    $('btnSaveBack').addEventListener('click', closeSave);
    $('btnSettings').addEventListener('click', () => openSettings());
    for (const id of SETTINGS_TABS) {
      $(id).addEventListener('click', () => selectTab(id));
      $(id).addEventListener('keydown', (event) => {
        const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
        if (!step) return;
        event.preventDefault();
        selectTab(SETTINGS_TABS[(SETTINGS_TABS.indexOf(id) + step + SETTINGS_TABS.length) % SETTINGS_TABS.length], { focus: true });
      });
    }
    $('btnSettingsDone').addEventListener('click', () => $('settingsDialog').close());
    let collapsed = false;
    try { collapsed = localStorage.getItem('anonimato.panelCollapsed') === '1'; } catch { /* storage unavailable */ }
    setPanel(collapsed);
    $('btnAllOn').addEventListener('click', () => toggle(visibleFindings().map((f) => f.id), true));
    $('btnAllOff').addEventListener('click', () => toggle(visibleFindings().map((f) => f.id), false));
    $('typeFilter').addEventListener('change', (event) => { state.filter = event.target.value; state.current = -1; renderDetails(); });
    for (const id of ['optMode', 'optInternal', 'optMaxSecurity', 'optUniform', 'optTextLayer']) {
      $(id).addEventListener('change', async () => {
        if (state.details) {
          state.details.report = null;
          state.savedIds.delete(state.details.id);
          renderReport(null);
          for (const doc of state.docs.filter((item) => item.status === 'ready')) await api.invalidate_report(doc.id);
          state.docs = await api.documents();
          renderQueue();
          schedulePreview();
        }
      });
    }
    installManual($('originalWrap'));
    installManual($('resultWrap'));
    // The whole documents list is the drop target; files dropped anywhere in the window are added as well.
    const dropzone = $('dropzone');
    let dragDepth = 0;
    dropzone.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth += 1; dropzone.classList.add('drag'); });
    dropzone.addEventListener('dragover', (e) => e.preventDefault());
    dropzone.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dropzone.classList.remove('drag'); });
    dropzone.addEventListener('drop', (e) => { e.preventDefault(); dragDepth = 0; dropzone.classList.remove('drag'); });
    document.addEventListener('dragover', (e) => e.preventDefault());
    document.addEventListener('drop', (e) => e.preventDefault());
    document.addEventListener('keydown', (event) => {
      const target = event.target;
      if ((target instanceof Element && target.matches('input, select, textarea')) || !state.details || $('resultsCard').hidden ||
        $('saveDialog').open || $('settingsDialog').open) return;
      const key = event.key.toLowerCase();
      if (key.startsWith('arrow') && target instanceof Element && target.closest('.zoomed-page')) return;
      if ((event.ctrlKey || event.metaKey) && ['z', 'y'].includes(key)) { event.preventDefault(); restoreReview(key === 'y' || event.shiftKey); return; }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      // Space and Enter keep their normal meaning on a focused button, link or menu.
      if ((key === ' ' || key === 'enter') && target instanceof Element && target.closest('button, a, summary')) return;
      if (key === 'arrowleft' && state.page > 0) { state.page -= 1; renderPage(); }
      else if (key === 'arrowright' && state.page < state.details.pages.length - 1) { state.page += 1; renderPage(); }
      else if (key === 'j') focusFinding(state.current + 1);
      else if (key === 'k') focusFinding(state.current - 1);
      else if (key === ' ' && state.current >= 0) {
        event.preventDefault();
        const f = visibleFindings()[state.current];
        if (f) toggle([f.id], !f.enabled);
      } else if (key === 'm') setManual(!state.manual);
      else if (key === 'd') setPanel(!state.panelCollapsed);
      else if (key === 'g') { event.preventDefault(); openSave(); }
      else if (key === 'escape' && state.manual) setManual(false);
      else return;
    });
  }

  async function init() {
    api = window.pywebview.api;
    state.status = await api.status();
    buildCategories();
    renderStatus();
    wire();
    await refreshDocuments();
    renderSettingsSummary();
  }

  async function refreshStatus() {
    state.status = await api.status();
    renderStatus();
    renderQueue();
    renderSettingsSummary();
  }

  window.app = { refreshDocuments, refreshStatus, notifyError: setError };
  window.addEventListener('pywebviewready', init);
})();

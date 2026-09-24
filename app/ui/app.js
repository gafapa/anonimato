'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    status: null, docs: [], activeId: null, details: null, page: 0, current: -1,
    manual: false, polling: false, previewTimer: null, previewSeq: 0, filter: '',
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
    };
  }
  function activeDoc() { return state.docs.find((doc) => doc.id === state.activeId) || null; }
  function visibleFindings() {
    const all = state.details?.findings || [];
    return state.filter ? all.filter((f) => f.type === state.filter) : all;
  }

  // ------------------------------------------------------------ status & options
  function renderStatus() {
    const s = state.status;
    const host = $('engineStatus');
    host.replaceChildren(
      el('span', { className: 'pill ' + (s.services.gpu ? 'ok' : 'warn'), textContent: s.services.gpu ? 'GPU activa' : 'Modo CPU' }),
      el('span', { className: 'pill ' + (s.advancedInstalled ? 'ok' : 'warn'), textContent: s.advancedInstalled ? 'IA avanzada lista' : 'IA avanzada no instalada' }),
      el('span', { className: 'pill ok', textContent: 'Sin conexión · local' }),
    );
    for (const label of document.querySelectorAll('.toggle.advanced')) {
      label.classList.toggle('unavailable', !s.advancedInstalled);
      label.querySelector('input').disabled = !s.advancedInstalled;
    }
    const box = $('advancedBox');
    if (s.advancedInstalled) {
      box.textContent = 'IA avanzada instalada: lectura de manuscritos y revisión contextual.';
      return;
    }
    box.replaceChildren(
      el('p', { textContent: 'La IA avanzada (≈ 3 GB) lee letra manuscrita y hace una revisión contextual. Solo se descargan modelos; ningún documento sale del equipo.' }),
      el('button', { className: 'btn ghost small', id: 'btnInstall', textContent: 'Descargar IA avanzada', onclick: installAdvanced }),
      el('button', { className: 'btn ghost small', textContent: 'Importar paquete sin conexión (.zip)', onclick: importAdvanced }),
      el('div', { className: 'progress-track', id: 'installTrack', hidden: true }, [el('div', { className: 'progress-fill', id: 'installFill' })]),
      el('p', { id: 'installText' }),
    );
  }

  function buildCategories() {
    const grid = $('catGrid');
    grid.replaceChildren();
    for (const category of state.status.categories) {
      const input = el('input', { type: 'checkbox', checked: category.default });
      input.dataset.cat = category.key;
      grid.append(el('label', { className: 'cat' }, [input, el('span', { textContent: category.label })]));
    }
    const filter = $('typeFilter');
    for (const category of state.status.categories) {
      filter.append(el('option', { value: category.key, textContent: category.label }));
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
    queue.replaceChildren();
    for (const doc of state.docs) {
      const status = doc.status === 'ready' ? `${doc.pages} pág. · ${doc.findings} hallazgos`
        : doc.status === 'processing' ? 'Analizando…'
          : doc.status === 'failed' ? `Error: ${doc.error}` : `${Math.round(doc.size / 1024)} KB · pendiente`;
      const select = el('button', { className: 'document-select', type: 'button', disabled: false }, [
        el('span', { className: 'document-name', textContent: doc.name }),
        el('span', { className: `document-status ${doc.status}`, textContent: status }),
      ]);
      select.addEventListener('click', () => selectDoc(doc.id));
      const remove = el('button', { className: 'document-remove', type: 'button', textContent: 'Quitar' });
      remove.setAttribute('aria-label', `Quitar ${doc.name}`);
      remove.addEventListener('click', async () => {
        if (await api.remove(doc.id)) {
          if (state.activeId === doc.id) { state.activeId = null; state.details = null; }
          await refreshDocuments();
        }
      });
      queue.append(el('div', { className: 'document-item' + (doc.id === state.activeId ? ' active' : '') }, [select, remove]));
    }
    $('btnRun').disabled = !state.docs.length || state.polling;
  }

  async function refreshDocuments() {
    state.docs = await api.documents();
    if (!state.activeId && state.docs.length) state.activeId = state.docs[0].id;
    renderQueue();
    await showActive();
  }

  async function selectDoc(id) {
    state.activeId = id;
    state.details = null;
    state.page = 0;
    state.current = -1;
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
      else if (state.docs.length) { heading.textContent = 'Documentos preparados'; text.textContent = 'Ajusta las opciones y pulsa «Analizar documentos».'; }
      else { heading.textContent = 'Añade tus documentos'; text.textContent = 'PDF, fotos o escaneos. Nada sale de este equipo.'; }
      return;
    }
    if (!state.details || state.details.id !== doc.id) {
      state.details = await api.details(doc.id);
      state.page = 0;
      state.current = -1;
    }
    renderDetails();
  }

  // ------------------------------------------------------------ processing & polling
  async function run() {
    setError('');
    const started = await api.process(options(), null);
    if (!started) { setError('Ya hay un proceso en curso.'); return; }
    state.details = null;
    startPolling();
  }

  function startPolling() {
    if (state.polling) return;
    state.polling = true;
    $('progressCard').hidden = false;
    $('btnCancel').hidden = false;
    $('btnRun').disabled = true;
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
      if (info.busy || installing) { setTimeout(tick, 400); return; }
      state.polling = false;
      $('progressCard').hidden = true;
      $('btnCancel').hidden = true;
      renderQueue();
      const firstReady = state.docs.find((doc) => doc.status === 'ready');
      if (activeDoc()?.status !== 'ready' && firstReady) state.activeId = firstReady.id;
      const failed = state.docs.filter((doc) => doc.status === 'failed');
      if (failed.length) setError(failed.map((doc) => `${doc.name}: ${doc.error}`).join(' · '));
      await showActive();
    };
    tick();
  }

  // ------------------------------------------------------------ review
  function renderDetails() {
    const d = state.details;
    const findings = d.findings;
    const enabled = findings.filter((f) => f.enabled);
    $('currentFileName').textContent = d.name;
    $('statsHost').replaceChildren(...[
      ['Páginas', d.pages.length], ['Hallazgos', findings.length], ['Incluidos', enabled.length],
      ['Rostros', findings.filter((f) => f.type === 'face').length], ['Tiempo', `${d.seconds} s`],
    ].map(([label, value]) => el('div', { className: 'stat' }, [el('b', { textContent: String(value) }), label])));
    const lowText = d.nativeChars / Math.max(1, d.pages.length) < 30;
    $('detectionNotice').hidden = !lowText && !d.notes.length;
    $('detectionNotice').textContent = lowText ? 'Documento escaneado o con poco texto: revisa con atención cada página y usa «Ocultar zona» si falta algo.' : '';
    $('notes').textContent = d.notes.join(' · ');
    renderReport(d.report);
    renderTable();
    renderPage();
  }

  function renderReport(report) {
    const card = $('verifyCard');
    if (!report) { card.hidden = true; return; }
    card.hidden = false;
    card.className = 'verify-card ' + (report.ok ? 'ok' : 'fail');
    const children = [el('strong', {
      textContent: report.ok
        ? `Verificación superada: 0 restos en ${report.objects} objetos y ${report.pages} páginas (${report.values} valores comprobados).`
        : `Verificación fallida: ${report.leaks.length} resto(s). No se ha guardado el archivo.`,
    })];
    if (!report.ok) {
      children.push(el('ul', {}, report.leaks.map((leak) => el('li', { textContent: `${leak.where}: ${leak.detail} (${leak.check}) «${leak.value}»` }))));
      children.push(el('p', { textContent: 'Prueba el modo «Voy a compartir este documento fuera» o añade una zona manual sobre el dato.' }));
    }
    if (report.warnings?.length) {
      children.push(el('ul', { className: 'warn-list' }, report.warnings.map((w) => el('li', { textContent: w }))));
    }
    card.replaceChildren(...children);
  }

  function renderTable() {
    const body = $('rowsBody');
    body.replaceChildren();
    const list = visibleFindings();
    list.forEach((f, index) => {
      const checkbox = el('input', { type: 'checkbox', checked: f.enabled });
      checkbox.setAttribute('aria-label', `Incluir ${f.label} de la página ${f.page + 1}`);
      checkbox.addEventListener('click', (event) => event.stopPropagation());
      checkbox.addEventListener('change', () => toggle([f.id], checkbox.checked));
      const confidence = Math.round(f.confidence * 100);
      const conf = el('td', { className: 'confidence' + (confidence < 80 ? ' low' : ''), textContent: `${confidence} %` });
      conf.title = f.warning === 'checksum' ? 'Formato reconocido; dígito de control no válido' : (f.detail || '');
      const value = el('td', { className: 'orig' }, [f.value ?? `(${f.detail || f.label})`, el('span', { className: 'src', textContent: sourceLabel(f.source) })]);
      const row = el('tr', { className: (f.enabled ? '' : 'off') + (index === state.current ? ' current' : '') }, [
        el('td', {}, [checkbox]), el('td', { textContent: String(f.page + 1) }),
        el('td', {}, [el('span', { className: 'type-badge', textContent: f.label })]), conf, value,
        el('td', { className: 'tok', textContent: f.token }),
      ]);
      row.addEventListener('click', () => focusFinding(index));
      if (f.type === 'manual') {
        const del = el('button', { className: 'btn ghost small', textContent: 'Borrar' });
        del.addEventListener('click', async (event) => {
          event.stopPropagation();
          await api.remove_manual(state.details.id, f.id);
          state.details.findings = state.details.findings.filter((x) => x.id !== f.id);
          renderDetails();
        });
        value.append(del);
      }
      body.append(row);
    });
    const enabled = state.details.findings.filter((f) => f.enabled).length;
    $('rowsCount').textContent = `(${enabled}/${state.details.findings.length} incluidos)`;
  }

  function sourceLabel(source) {
    return {
      text: 'texto del PDF', ai: 'IA de datos personales', ocr: 'OCR', handwriting: 'manuscrito', propagation: 'repetición',
      llm: 'revisión IA', face: 'detector de rostros', signature: 'detector de firmas', manual: 'manual', form: 'formulario',
    }[source] || source;
  }

  async function toggle(ids, enabled) {
    await api.set_enabled(state.details.id, ids, enabled);
    for (const f of state.details.findings) if (ids.includes(f.id)) f.enabled = enabled;
    state.details.report = null;
    renderDetails();
  }

  function focusFinding(index) {
    const list = visibleFindings();
    if (!list.length) return;
    state.current = (index + list.length) % list.length;
    const f = list[state.current];
    if (f.page !== state.page) { state.page = f.page; renderPage(); } else { drawBoxes(); }
    renderTable();
    body().querySelector('tr.current')?.scrollIntoView({ block: 'nearest' });
  }
  const body = () => $('rowsBody');

  async function renderPage() {
    const d = state.details;
    state.page = Math.max(0, Math.min(state.page, d.pages.length - 1));
    $('pageIndicator').textContent = `Página ${state.page + 1} de ${d.pages.length}`;
    $('btnPrevPage').disabled = state.page === 0;
    $('btnNextPage').disabled = state.page === d.pages.length - 1;
    const seq = ++state.previewSeq;
    $('originalImg').src = await api.page_image(d.id, state.page, 'original', options());
    if (seq !== state.previewSeq) return;
    drawBoxes();
    schedulePreview();
  }

  function schedulePreview() {
    clearTimeout(state.previewTimer);
    const wrap = $('resultWrap');
    wrap.classList.add('loading-preview');
    $('resultImg').removeAttribute('src');  // never show the original while the result is generated
    state.previewTimer = setTimeout(async () => {
      const seq = ++state.previewSeq;
      try {
        const src = await api.page_image(state.details.id, state.page, 'result', options());
        if (seq === state.previewSeq) { $('resultImg').src = src; wrap.classList.remove('loading-preview'); }
      } catch (error) {
        setError(`No se pudo generar la vista previa: ${error.message || error}`);
        wrap.classList.remove('loading-preview');
      }
    }, 200);
  }

  function drawBoxes() {
    const wrap = $('originalWrap');
    for (const node of wrap.querySelectorAll('.box')) node.remove();
    const list = visibleFindings();
    const current = list[state.current];
    for (const f of state.details.findings) {
      if (f.page !== state.page) continue;
      for (const [x0, y0, x1, y1] of f.view) {
        const box = el('div', {
          className: `box ${f.type}` + (f.enabled ? '' : ' off') + (f.confidence < 0.8 ? ' low' : '') + (current && current.id === f.id ? ' current' : ''),
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
      if (!state.manual || event.button !== 0) return;
      event.preventDefault();
      const bounds = wrap.getBoundingClientRect();
      start = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
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
      const bounds = wrap.getBoundingClientRect();
      const left = parseFloat(selection.style.left) || 0;
      const top = parseFloat(selection.style.top) || 0;
      const width = parseFloat(selection.style.width) || 0;
      const height = parseFloat(selection.style.height) || 0;
      selection.remove();
      start = null;
      if (width < 6 || height < 6) return;
      const rect = [left / bounds.width, top / bounds.height, (left + width) / bounds.width, (top + height) / bounds.height];
      const finding = await api.add_manual(state.details.id, state.page, rect);
      state.details.findings.push(finding);
      state.details.report = null;
      setManual(false);
      renderDetails();
    });
  }
  function setManual(on) {
    state.manual = on;
    $('btnManual').setAttribute('aria-pressed', String(on));
    $('btnManual').textContent = on ? 'Arrastra sobre la página…' : 'Ocultar zona (M)';
    $('originalWrap').classList.toggle('manual-mode', on);
    $('resultWrap').classList.toggle('manual-mode', on);
  }

  // ------------------------------------------------------------ export
  async function savePdf() {
    setError('');
    $('btnPdf').disabled = true;
    $('progressCard').hidden = false;
    $('progressText').textContent = 'Generando y verificando…';
    try {
      const result = await api.save_pdf(state.details.id, options());
      state.details.report = result.report || null;
      renderReport(state.details.report);
      if (!result.ok) setError(result.message);
      else if (result.saved) $('progressText').textContent = `Guardado: ${result.path}`;
    } catch (error) {
      setError(`Error al guardar: ${error.message || error}`);
    } finally {
      $('btnPdf').disabled = false;
      setTimeout(() => { if (!state.polling) $('progressCard').hidden = true; }, 2500);
    }
  }
  async function saveAll() {
    setError('');
    const result = await api.save_all(options());
    if (result.message) setError(result.message);
    else if (result.folder) {
      $('progressCard').hidden = false;
      $('progressText').textContent = `${result.saved} guardados${result.failed ? `, ${result.failed} bloqueados por la verificación` : ''} en ${result.folder}`;
    }
    state.details = await api.details(state.details.id);
    renderDetails();
  }
  async function saveLog(format) {
    await api.save_log(state.details.id, format, $('optLogOriginals').checked, $('optLogCoords').checked);
  }

  // ------------------------------------------------------------ wiring
  function wire() {
    $('btnAddFiles').addEventListener('click', async () => { await api.pick_files(); await refreshDocuments(); });
    $('btnAddFolder').addEventListener('click', async () => { await api.pick_folder(false); await refreshDocuments(); });
    $('btnRun').addEventListener('click', run);
    $('btnCancel').addEventListener('click', () => api.cancel());
    $('btnPdf').addEventListener('click', savePdf);
    $('btnAll').addEventListener('click', saveAll);
    $('btnCsv').addEventListener('click', () => saveLog('csv'));
    $('btnJson').addEventListener('click', () => saveLog('json'));
    $('optLogOriginals').addEventListener('change', () => { $('logWarning').hidden = !$('optLogOriginals').checked; });
    $('btnReset').addEventListener('click', async () => { if (await api.clear()) { state.activeId = null; state.details = null; await refreshDocuments(); } });
    $('btnPrevPage').addEventListener('click', () => { state.page -= 1; renderPage(); });
    $('btnNextPage').addEventListener('click', () => { state.page += 1; renderPage(); });
    $('btnManual').addEventListener('click', () => setManual(!state.manual));
    $('btnAllOn').addEventListener('click', () => toggle(visibleFindings().map((f) => f.id), true));
    $('btnAllOff').addEventListener('click', () => toggle(visibleFindings().map((f) => f.id), false));
    $('typeFilter').addEventListener('change', (event) => { state.filter = event.target.value; state.current = -1; renderDetails(); });
    for (const id of ['optMode', 'optMaxSecurity', 'optUniform']) {
      $(id).addEventListener('change', () => { if (state.details) { state.details.report = null; renderReport(null); schedulePreview(); } });
    }
    installManual($('originalWrap'));
    installManual($('resultWrap'));
    const dropzone = $('dropzone');
    for (const name of ['dragenter', 'dragover']) dropzone.addEventListener(name, (e) => { e.preventDefault(); dropzone.classList.add('drag'); });
    for (const name of ['dragleave', 'drop']) dropzone.addEventListener(name, (e) => { e.preventDefault(); dropzone.classList.remove('drag'); });
    document.addEventListener('dragover', (e) => e.preventDefault());
    document.addEventListener('drop', (e) => e.preventDefault());
    document.addEventListener('keydown', (event) => {
      if (event.target.matches('input, select, textarea') || !state.details || $('resultsCard').hidden) return;
      const key = event.key.toLowerCase();
      if (key === 'arrowleft' && state.page > 0) { state.page -= 1; renderPage(); }
      else if (key === 'arrowright' && state.page < state.details.pages.length - 1) { state.page += 1; renderPage(); }
      else if (key === 'j') focusFinding(state.current + 1);
      else if (key === 'k') focusFinding(state.current - 1);
      else if (key === ' ' && state.current >= 0) {
        event.preventDefault();
        const f = visibleFindings()[state.current];
        if (f) toggle([f.id], !f.enabled);
      } else if (key === 'm') setManual(!state.manual);
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
  }

  window.app = { refreshDocuments };
  window.addEventListener('pywebviewready', init);
})();

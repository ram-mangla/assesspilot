(cfg) => {
  cfg = cfg || {};
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const up = e => e.parentElement || (e.getRootNode && e.getRootNode().host) || null;
  const deepAll = (root, sel, out = []) => {
    const walk = r => { r.querySelectorAll(sel).forEach(e => out.push(e));
      r.querySelectorAll('*').forEach(e => { if (e.shadowRoot) walk(e.shadowRoot); }); };
    walk(root);
    if (root === document) document.querySelectorAll('iframe').forEach(f => {
      try { const d = f.contentDocument; if (d && d.body) walk(d); } catch (e) {}
    });
    return out;
  };
  window.__qaSeq = window.__qaSeq || 0;
  const stamp = el => { let id = el.getAttribute('data-qa'); if (!id) { id = 'qa' + (++window.__qaSeq); el.setAttribute('data-qa', id); } return id; };
  const vis = el => {
    if (!el || !el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const textOf = el => {
    if (!el) return '';
    const c = el.cloneNode(true);
    c.querySelectorAll('script,style,input,select,textarea,button').forEach(x => x.remove());
    return clean(c.textContent);
  };
  const QSEL = cfg.questionSel || '.que, .question, .quiz-question, .q, form .question, fieldset.question, [role=group][aria-labelledby], div:has(> .stem), div:has(> .qtext), div:has(> .question-text), div:has(> .prompt)';
  const STEM = cfg.stemSel || '.qtext, .stem, .question-text, .prompt, [data-question-text], [id^=QUESTEXT], h2, h3, p';
  const BTN = 'button, a, input[type=button], input[type=submit], [role=button], [role=link]';
  const NAVRX = /^(next|continue|proceed|previous|prev|back|save( (&|and) ?(next|continue))?|submit( all and finish)?|finish( attempt)?|start( attempt)?|begin( quiz| test)?|attempt( quiz)?|take( the)? quiz|check answer|review|submit answer|skip|flag|clear (my )?choice)$/i;

  // ---- question containers
  let containers = deepAll(document, QSEL).filter(e => vis(e) && textOf(e).length > 4);
  // a stem box whose answer inputs live in a sibling container: widen to the whole question
  containers = containers.map(e => {
    // answer radios in a sibling container are the real options; a mark-for-review
    // checkbox sitting on the stem must not be mistaken for an answer box
    if (e.querySelector('input[type=radio],select,textarea')) return e;
    for (let n = e, i = 0; n && i < 3; i++, n = n.parentElement) {
      if (n.querySelectorAll(':scope > div.answer-container, :scope > [role=radiogroup]').length === 1) return n;
    }
    return e;
  });
  containers = containers.filter(e => vis(e) && e.querySelector('input,select,textarea,[role=radio],[role=checkbox],[role=textbox],[role=button],button') && textOf(e).length > 4);
  containers = [...new Set(containers)];
  containers = containers.filter(e => !containers.some(o => o !== e && e.contains(o)));
  const totalRe = /(?:question|item|task)\s*(\d+)\s*(?:of|\/|out of)\s*(\d+)/i;
  const totalText = (document.body ? document.body.innerText : '').match(totalRe);
  const extraText = () => {
    let t = '';
    document.querySelectorAll('*').forEach(e => { if (e.shadowRoot) t += ' ' + e.shadowRoot.textContent; });
    document.querySelectorAll('iframe').forEach(f => {
      try { if (f.contentDocument && f.contentDocument.body) t += ' ' + f.contentDocument.body.innerText; } catch (e) {}
    });
    return t;
  };
  const bodyText = clean((document.body ? document.body.innerText : '') + ' ' + extraText()).slice(0, 8000);

  const questions = containers.map((box, i) => {
    let stem = box.querySelector(STEM);
    if (!stem) { stem = box; }
    let prompt = textOf(stem);
    if (prompt.length > 900) prompt = prompt.slice(0, 900);
    const inputs = deepAll(box, 'input, select, textarea, [role=radio], [role=checkbox], [role=textbox], [role=combobox]').filter(vis);
    const kinds = new Set(inputs.filter(i => i.type !== 'hidden' && !/^MARK/i.test(i.name || '')).map(i => i.tagName === 'SELECT' ? 'select' : i.tagName === 'TEXTAREA' ? 'textarea' : (i.type || i.getAttribute('role') || '')));
    let kind = 'single';
    if (kinds.has('checkbox') || kinds.has('checkbox')) kind = 'multi';
    if (kinds.has('select')) kind = inputs.length === 1 ? 'select' : 'matching';
    if (kinds.has('textarea')) kind = 'textarea';
    if (kinds.has('text') || kinds.has('number') || kinds.has('textbox')) kind = kinds.has('select') ? 'matching' : 'text';
    const opts = [];
    // radios grouped by name: the answer group; mark-for-review style checkboxes share no group
    const group = deepAll(box, 'input[type=radio], input[type=checkbox]').filter(vis);
    const answerGroup = group.filter(inp => inp.type === 'radio').length
      ? group.filter(inp => inp.type === 'radio')
      : group;
    const radios = deepAll(document, 'input[type=radio]').filter(vis);
    const host = box.closest('div.question-wrapper');
    const byName = (() => {
      const own = group.find(inp => inp.name);
      if (!own) return [];
      const name = own.name;
      if (host) return radios.filter(inp => inp.name === name);
      return radios.filter(inp => inp.name === name);
    })();
    const pool = (() => {
      // mark-for-review style checkboxes are not answers: prefer the radio group by name,
      // then a single shared answer-group name (TCTMC1..TCTMCN) over per-question group names
      const r = group.filter(i => i.type === 'radio');
      const names = [...new Set(group.map(i => i.name).filter(Boolean))];
      if (r.length) {
        const name = r[0].name;
        const doc = deepAll(document, 'input[type=radio]').filter(i => vis(i) && i.name === name);
        return doc.length ? doc : r;
      }
      if (names.length === 1) {
        const doc = deepAll(document, 'input[type=checkbox]').filter(i => vis(i) && i.name === names[0]);
        if (doc.length > 1) return doc;
      }
      return group.filter(i => !/^MARK/i.test(i.name || ''));
    })();
    if (pool.length) {
      pool.forEach((inp, k) => {
        let label = inp.labels && inp.labels.length ? textOf(inp.labels[0]) : '';
        if (!label && inp.getAttribute('aria-label')) label = inp.getAttribute('aria-label');
        if (!label && inp.getAttribute('aria-labelledby')) {
          const l = document.getElementById(inp.getAttribute('aria-labelledby'));
          if (l) label = textOf(l);
        }
        if (!label) { const p = up(inp); label = p ? textOf(p) : ''; }
        opts.push({ uid: stamp(inp), click: stamp(inp), text: clean(label) || clean(inp.value), value: inp.value || String(k),
                    checked: !!inp.checked, name: inp.name || '' });
      });
    } else {
      const btns = deepAll(box, '[role=radio],[role=checkbox],[role=option],.opt,.option,.choice,.answer-option').filter(vis);
      btns.forEach((b, k) => {
        const inner = b.querySelector('input[type=radio],input[type=checkbox]');
        opts.push({ uid: stamp(b), click: stamp(inner || b), text: textOf(b), value: b.getAttribute('data-v') || String(k),
                    checked: inner ? !!inner.checked : ['aria-checked', 'aria-selected'].some(a => b.getAttribute(a) === 'true') || /\b(selected|checked|active|chosen)\b/.test(b.className || ''),
                    name: '' });
      });
    }
    const textCtrl = deepAll(box, 'input[type=text], input[type=number], textarea, [contenteditable=true], [role=textbox]').filter(vis)[0];
    const selects = deepAll(box, 'select').filter(vis);
    const qnum = (() => {
      const m = textOf(box).match(/^\s*(?:question\s*)?(\d+)\s*[.):]/i);
      const labelled = box.getAttribute('data-question-number');
      return m ? +m[1] : (labelled ? +labelled : null);
    })();
    const state = deepAll(box, '.state, .status, [data-state], .answered').map(textOf).join(' ').trim();
    return {
      box: stamp(box), kind, prompt, options: opts,
      text_uid: textCtrl ? stamp(textCtrl) : null,
      text_kind: textCtrl ? (textCtrl.tagName === 'TEXTAREA' ? 'textarea' : (textCtrl.type || 'text')) : null,
      text_value: textCtrl ? (textCtrl.value || textCtrl.textContent || '') : '',
      selects: selects.map(s => ({ uid: stamp(s), label: '', value: s.value || '',
        options: [...s.options].map(o => ({ value: o.value, text: clean(o.text) })) })),
      number: qnum,
      position: i + 1,
      saved_state: state,
      answered: opts.some(o => o.checked) || (textCtrl ? clean(textCtrl.value || '').length > 0 : false),
      progress: (textOf(box).match(totalRe) || [])[0] || null,
    };
  });

  // ---- navigator buttons (side rail with per-question links)
  const navItems = deepAll(document, 'a, button, [role=button]').filter(e => {
    const t = clean(e.innerText || e.getAttribute('aria-label') || '');
    return vis(e) && /^(question\s*)?\d{1,3}$/i.test(t) && !e.closest('nav.sidebar-menu, #nav-sections, header nav');
  }).map(e => ({ uid: stamp(e), n: parseInt(clean(e.innerText || e.getAttribute('aria-label') || '').match(/\d+/)[0], 10),
                 cls: (e.className || '').toString().slice(0, 120),
                 answered: /\b(answersaved|answered|complete|done)\b/i.test(e.className || '') }));

  // ---- controls
  const inModal = e => { for (let p = e; p; p = up(p)) { const role = p.getAttribute && p.getAttribute('role'); if (role === 'dialog' || role === 'alertdialog') return true; } return false; };
  const controls = [];
  deepAll(document, BTN + ', [type=submit]').forEach(e => {
    if (!vis(e)) return;
    const t = clean(e.innerText || e.value || e.getAttribute('aria-label') || e.title || '');
    if (!t || t.length > 60) return;
    const nav = NAVRX.test(t) || /(submit|finish|start|begin|next|previous|save|review|submit all)/i.test(t);
    if (!nav) return;
    controls.push({ uid: stamp(e), text: t.slice(0, 60),
      disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true' || /\bdisabled\b/.test(e.className || ''),
      type: e.getAttribute('type') || '', in_modal: inModal(e), tag: e.tagName, href: e.getAttribute('href') || '' });
  });

  // ---- page-level facts
  const timer = bodyText.match(/(?:time left|time remaining|remaining time)\s*:?\s*([\d:]+)/i);
  const title = (document.querySelector('h1, .quizname, [data-quiz-title]') ? clean(document.querySelector('h1, .quizname, [data-quiz-title]').innerText) : clean(document.title));
  const progress = bodyText.match(totalRe);
  const looksQuiz = questions.length > 0 || controls.some(c => /start|begin|attempt|submit|next|finish/i.test(c.text));
  return {
    url: location.href,
    title,
    ready_state: document.readyState,
    busy: !!(document.querySelector('dialog[open]') || document.querySelector('.loading, .spinner, [aria-busy=true]')),
    questions,
    controls,
    nav_items: navItems,
    has_password: deepAll(document, 'input[type=password]').some(vis),
    looks_quiz: looksQuiz,
    timer: timer ? timer[1] : null,
    progress: progress ? { index: +progress[1], total: +progress[2] } : (totalText ? { index: null, total: +totalText[2] } : null),
    images: deepAll(document, 'img, svg, canvas').filter(vis).slice(0, 8).map(i => ({ src: (i.getAttribute && (i.getAttribute('src') || i.getAttribute('data-src'))) || null, alt: clean(i.getAttribute && i.getAttribute('alt') || ''), w: i.getBoundingClientRect().width })),
    text: bodyText,
  };
}

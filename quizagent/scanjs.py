"""In-page scanner. Runs inside every frame, pierces open shadow DOM, returns
question descriptors + nav candidates. Elements get a `data-qa` stamp so Python
can re-locate them (Playwright CSS pierces open shadow roots)."""

SCAN_JS = r"""
(cfg) => {
  cfg = cfg || {};
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const up = e => e.parentElement || (e.getRootNode && e.getRootNode().host) || null;
  const deepAll = (root, sel, out = []) => {
    root.querySelectorAll(sel).forEach(e => out.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) deepAll(e.shadowRoot, sel, out); });
    return out;
  };
  const closestDeep = (el, sel) => { for (let e = el; e; e = up(e)) if (e.matches && e.matches(sel)) return e; return null; };
  const containsDeep = (a, b) => { for (let e = b; e; e = up(e)) if (e === a) return true; return false; };
  window.__qaSeq = window.__qaSeq || 0;
  const stamp = el => { let id = el.getAttribute('data-qa'); if (!id) { id = 'qa' + (++window.__qaSeq); el.setAttribute('data-qa', id); } return id; };
  const vis = el => {
    if (!el || !el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const big = e => { const r = e.getBoundingClientRect(); return vis(e) && r.width >= 6 && r.height >= 6; };
  const textOf = el => {
    if (!el) return '';
    const c = el.cloneNode(true);
    if (cfg.stripSel) c.querySelectorAll(cfg.stripSel).forEach(x => x.remove());
    c.querySelectorAll('script,style,input,select,textarea').forEach(x => x.remove());
    return clean(c.textContent);
  };
  const byId = (node, id) => { const rn = node.getRootNode(); return rn.getElementById ? rn.getElementById(id) : null; };
  const labelOf = (inp, sib = true) => {
    let t = '';
    if (inp.labels && inp.labels.length) t = [...inp.labels].map(textOf).join(' ');
    if (!t && inp.getAttribute('aria-labelledby'))
      t = inp.getAttribute('aria-labelledby').split(/\s+/).map(id => { const e = byId(inp, id); return e ? textOf(e) : ''; }).join(' ');
    if (!t && inp.getAttribute('aria-label')) t = inp.getAttribute('aria-label');
    if (!t && sib) {
      const s = inp.nextElementSibling;
      if (s && !s.matches('input,select,textarea,button')) t = textOf(s);
      if (!t && inp.nextSibling && inp.nextSibling.nodeType === 3) t = inp.nextSibling.textContent;
    }
    if (!t && sib) { const p = up(inp); if (p) t = textOf(p); }
    return clean(t);
  };
  const clickTarget = inp => {
    if (big(inp)) return inp;
    if (inp.labels) for (const l of inp.labels) if (big(l)) return l;
    for (let p = up(inp); p && p !== document.body; p = up(p)) if (big(p)) return p;
    return inp;
  };
  const stateOf = e => e.checked === true ||
    ['aria-checked', 'aria-selected', 'aria-pressed'].some(a => e.getAttribute(a) === 'true') ||
    (cfg.selectedSel ? e.matches(cfg.selectedSel) : /\b(selected|active|checked|chosen|is-selected|picked)\b/.test(e.className || ''));

  const SKIP_TAGS = 'button,select,option,script,style,input,textarea,nav,[role=navigation],svg,noscript';
  const NOISE = '[class*=timer i],[id*=timer i],[class*=countdown i],[id*=countdown i],[class*=progress i],[aria-live]';
  const textOutside = (a, skipEls) => {
    const parts = [];
    const walk = node => {
      if (node.nodeType === 3) { const t = clean(node.textContent); if (t) parts.push(t); return; }
      if (node.nodeType !== 1) return;
      if (node.matches(SKIP_TAGS) || node.matches(NOISE)) return;
      if (skipEls.indexOf(node) >= 0) return;
      if (!vis(node)) return;
      if (node.shadowRoot) node.shadowRoot.childNodes.forEach(walk);
      node.childNodes.forEach(walk);
    };
    if (a.shadowRoot) a.shadowRoot.childNodes.forEach(walk);
    a.childNodes.forEach(walk);
    return clean(parts.join(' '));
  };
  const lca = els => { let a = up(els[0]); while (a && !els.every(e => containsDeep(a, e))) a = up(a); return a; };
  const hasForeignControls = (a, ctrls) =>
    deepAll(a, 'input:not([type=hidden]),select,textarea').some(c => ctrls.indexOf(c) < 0 && vis(c));
  const promptFor = (ctrls, skipEls) => {
    const first = ctrls[0];
    const fs = closestDeep(first, 'fieldset');
    if (fs && ctrls.every(c => containsDeep(fs, c))) {
      const lg = fs.querySelector('legend'); if (lg && clean(lg.textContent)) return clean(lg.textContent);
    }
    const grp = closestDeep(first, '[role=radiogroup],[role=group],[role=listbox]');
    if (grp) {
      const lb = grp.getAttribute('aria-labelledby');
      if (lb) { const t = clean(lb.split(/\s+/).map(id => { const e = byId(grp, id); return e ? e.textContent : ''; }).join(' ')); if (t) return t; }
      const al = grp.getAttribute('aria-label'); if (al) return clean(al);
    }
    let a = ctrls.length === 1 ? ctrls[0] : lca(ctrls);
    for (let i = 0; i < 7 && a && a !== document.body && a !== document.documentElement; i++) {
      if (!hasForeignControls(a, ctrls)) { const t = textOutside(a, skipEls); if (t.length >= 3) return t.slice(0, 600); }
      for (let s = a.previousElementSibling, n = 0; s && n < 2; s = s.previousElementSibling, n++) {
        if (!vis(s) || s.matches(SKIP_TAGS) || s.matches(NOISE)) continue;
        if (deepAll(s, 'input,select,textarea').length) break;
        const t = textOutside(s, []) || clean(s.textContent);
        if (t.length >= 3) return t.slice(0, 600);
      }
      a = up(a);
    }
    return '';
  };
  const ITEM = 'li,label,tr,.option,[class*=opt i],[class*=choice i],[class*=answer i],[class*=radio i],[class*=check i]';
  const itemOf = (i, all) => { let it = closestDeep(i, ITEM); if (it && all.length > 1 && all.every(o => containsDeep(it, o))) it = null; return it; };
  const rowLabel = el => {
    const tr = closestDeep(el, 'tr');
    if (tr) for (const c of tr.children) if (!c.querySelector('select,input,textarea') && clean(c.textContent)) return textOf(c);
    return '';
  };
  const isPlaceholder = o => o.value === '' || /^\s*(-+|select|choose|pick|please)\b/i.test(o.textContent || '');
  const okCtl = i => !i.disabled && (vis(i) || (i.labels && [...i.labels].some(vis)) || vis(up(i)));

  const MULTIHINT = /select all|choose all|all that apply|check all|one or more|multiple/i;
  const isMulti = (root, prompt) => {
    const m = cfg.multi;
    if (typeof m === 'string') return m.startsWith('re:') ? new RegExp(m.slice(3), 'i').test(prompt) : !!(root && root.matches && root.matches(m));
    if (typeof m === 'boolean') return m;
    return MULTIHINT.test(prompt);
  };
  const out = [];
  const seen = new Set();
  const push = (q, first) => {
    q.uid = stamp(first);
    const r = first.getBoundingClientRect();
    q.top = r.top + window.scrollY; q.left = r.left;
    out.push(q);
  };
  const optOf = i => ({ text: labelOf(i), value: i.value || '', uid: stamp(i), click: stamp(clickTarget(i)), checked: !!i.checked });
  const formKey = i => (i.form ? stamp(i.form) : '') + '|';

  function collect(root, scoped, base) {
    const R = sel => deepAll(root, sel);
    // radios
    const rg = new Map();
    R('input[type=radio]').filter(i => !seen.has(i) && okCtl(i)).forEach(i => {
      const k = i.name ? formKey(i) + i.name : 'x|' + stamp(closestDeep(i, '[role=radiogroup],fieldset') || up(i));
      if (!rg.has(k)) rg.set(k, []); rg.get(k).push(i);
    });
    rg.forEach(g => {
      g.forEach(i => seen.add(i));
      const skip = g.flatMap(i => [...(i.labels || []), itemOf(i, g)]).filter(Boolean);
      push({ kind: 'single', mode: 'native', reliable: true, prompt: base || promptFor(g, skip), options: g.map(optOf), answered: g.some(i => i.checked) }, g[0]);
    });
    // checkboxes
    const cbs = R('input[type=checkbox]').filter(i => !seen.has(i) && okCtl(i));
    const cg = new Map();
    if (scoped) { if (cbs.length) cg.set('all', cbs); }
    else {
      const cnt = {}; cbs.forEach(i => { if (i.name) { const k = formKey(i) + i.name; cnt[k] = (cnt[k] || 0) + 1; } });
      cbs.forEach(i => {
        let k;
        if (i.name && cnt[formKey(i) + i.name] >= 2) k = 'n|' + formKey(i) + i.name;
        else {
          let c = closestDeep(i, 'fieldset,[role=group],.question,.que,[class*=question i],[class*=quiz-item i],.card');
          if (!c) { const li = closestDeep(i, 'li,tr'); c = li ? up(li) : up(closestDeep(i, 'label') || i); }
          k = 'c|' + stamp(c);
        }
        if (!cg.has(k)) cg.set(k, []); cg.get(k).push(i);
      });
    }
    cg.forEach(g => {
      if (g.length === 1 && /agree|terms|accept|remember|consent|subscribe|newsletter|robot/i.test(labelOf(g[0]))) return;
      g.forEach(i => seen.add(i));
      const skip = g.flatMap(i => [...(i.labels || []), itemOf(i, g)]).filter(Boolean);
      push({ kind: 'multi', mode: 'native', reliable: true, prompt: base || promptFor(g, skip), options: g.map(optOf), answered: g.some(i => i.checked) }, g[0]);
    });
    // selects
    R('select').filter(s => !seen.has(s) && !s.disabled && vis(s) && !/lang|locale|sort|per.?page|page.?size/i.test((s.name || '') + ' ' + (s.id || ''))).forEach(s => {
      seen.add(s);
      const opts = [...s.options].filter(o => !isPlaceholder(o)).map(o => ({ text: clean(o.textContent), value: o.value, idx: o.index }));
      const sel = s.options[s.selectedIndex];
      let p;
      if (scoped) { const rl = rowLabel(s); p = (base || '') + (rl ? (base ? ' :: ' : '') + rl : ''); }
      else { p = labelOf(s, false); if (!p || p.length < 3) p = promptFor([s], []); }
      push({ kind: s.multiple ? 'multi' : 'select', mode: 'select', reliable: true, prompt: p, options: opts, answered: !!sel && !isPlaceholder(sel) }, s);
    });
    // free text
    R('input:not([type]),input[type=text],input[type=number],input[type=tel],textarea,[contenteditable=""],[contenteditable=true]')
      .filter(e => !seen.has(e) && vis(e) && !e.disabled && !e.readOnly &&
        !/search|filter|find|query|email|user|login|pass|captcha|coupon|promo/i.test((e.name || '') + ' ' + (e.id || '') + ' ' + (e.placeholder || '') + ' ' + (e.getAttribute('aria-label') || '') + ' ' + (e.type || '')) &&
        !closestDeep(e, '[role=search]'))
      .forEach(e => {
        seen.add(e);
        const isInput = e.tagName === 'INPUT', isTA = e.tagName === 'TEXTAREA';
        const kind = isTA || !isInput ? 'textarea' : (e.type === 'number' ? 'number' : 'text');
        const val = isInput || isTA ? e.value : e.textContent;
        let p;
        if (scoped) { const rl = rowLabel(e); p = (base || '') + (rl && rl !== base ? (base ? ' :: ' : '') + rl : ''); }
        else { p = labelOf(e, false); if (!p || p.length < 3) p = promptFor([e], []); if (!p) p = e.placeholder || ''; }
        push({ kind, mode: 'text', reliable: true, prompt: p, options: [], answered: clean(val) !== '' }, e);
      });
    // ARIA widgets
    const aria = (sel, kind) => {
      const g = new Map();
      R(sel).filter(e => !seen.has(e) && vis(e)).forEach(e => {
        const grp = closestDeep(e, '[role=radiogroup],[role=group],[role=listbox]') || up(e);
        const k = stamp(grp); if (!g.has(k)) g.set(k, []); g.get(k).push(e);
      });
      g.forEach(arr => {
        arr.forEach(e => seen.add(e));
        const multi = kind === 'multi' || !!closestDeep(arr[0], '[aria-multiselectable=true]');
        push({ kind: multi ? 'multi' : 'single', mode: 'aria', reliable: true,
          prompt: base || promptFor(arr, arr),
          options: arr.map(e => ({ text: textOf(e) || e.getAttribute('aria-label') || '', value: '', uid: stamp(e), click: stamp(e), checked: stateOf(e) })),
          answered: arr.some(stateOf) }, arr[0]);
      });
    };
    aria('[role=radio]', 'single'); aria('[role=checkbox]', 'multi'); aria('[role=option]', 'single');
    // configured custom options (scoped)
    if (scoped && cfg.optionSel) {
      const els = R(cfg.optionSel).filter(e => !seen.has(e) && vis(e));
      if (els.length) {
        els.forEach(e => seen.add(e));
        const pr = base || promptFor(els, els);
        const multi = isMulti(root, pr);
        push({ kind: multi ? 'multi' : 'single', mode: 'custom', reliable: !!cfg.selectedSel || els.some(e => e.hasAttribute('aria-checked') || e.hasAttribute('aria-selected')),
          prompt: pr,
          options: els.map(e => ({ text: cfg.optionTextSel ? textOf(e.querySelector(cfg.optionTextSel) || e) : textOf(e), value: '', uid: stamp(e), click: stamp(e), checked: stateOf(e) })),
          answered: els.some(stateOf) }, els[0]);
      }
    }
  }

  function heuristics() {
    const NAVRE = /^(next|prev|previous|back|submit|finish|start|begin|continue|cancel|close|ok|yes|no|skip|retry|restart)\b/i;
    const groups = new Map();
    deepAll(document, 'body *').forEach(el => {
      if (!vis(el) || seen.has(el)) return;
      if (closestDeep(el, 'nav,header,footer,[role=navigation],[role=menu],[role=toolbar],button,a,[role=search]')) return;
      if (getComputedStyle(el).cursor !== 'pointer') return;
      if (el.querySelector('input,button,select,textarea,a')) return;
      const t = clean(el.innerText || el.textContent);
      if (!t || t.length > 200) return;
      const p = up(el); if (!p) return;
      const STATE_CLS = /^(selected|active|checked|chosen|is-selected|picked|hover|focus|focused|disabled|on|correct|wrong)$/i;
      const k = stamp(p) + '|' + el.tagName + '.' + [...el.classList].filter(c => !STATE_CLS.test(c)).sort().join('.');
      if (!groups.has(k)) groups.set(k, []); groups.get(k).push(el);
    });
    const cands = [...groups.values()].filter(g => g.length >= 2 && g.length <= 12 && !g.every(e => NAVRE.test(clean(e.innerText))));
    const outer = cands.filter(g => !cands.some(h => h !== g && g.every(e => h.some(x => containsDeep(x, e)))));
    outer.forEach(g => {
      g.forEach(e => seen.add(e));
      const pr = promptFor(g, g);
      push({ kind: isMulti(null, pr) ? 'multi' : 'single', mode: 'heur', reliable: false, prompt: pr,
        options: g.map(e => ({ text: textOf(e), value: '', uid: stamp(e), click: stamp(e), checked: stateOf(e) })),
        answered: g.some(stateOf) }, g[0]);
    });
  }

  if (cfg.qsel) {
    deepAll(document, cfg.qsel).filter(vis).forEach(c => {
      const pe = cfg.promptSel ? c.querySelector(cfg.promptSel) : null;
      collect(c, true, pe ? textOf(pe) : null);
    });
  } else {
    collect(document, false, null);
    if (cfg.heuristic && !out.length) heuristics();
  }
  out.sort((a, b) => (a.top - b.top) || (a.left - b.left));

  // ---- nav candidates
  const modals = deepAll(document, '[role=dialog],[role=alertdialog],dialog[open],[aria-modal=true],[class*=modal i],[class*=dialog i]')
    .filter(m => vis(m) && (m.matches('[role=dialog],[role=alertdialog],dialog[open],[aria-modal=true]') ||
      ['fixed', 'absolute'].includes(getComputedStyle(m).position)));
  const NAVSEL = 'button,a,input[type=submit],input[type=button],input[type=image],[role=button],[role=link],[onclick],summary';
  const cand = new Set(deepAll(document, NAVSEL));
  deepAll(document, 'div,span,li,td,p').forEach(e => {
    if (cand.has(e) || !vis(e) || e.querySelector('input,select,textarea')) return;
    const t = clean(e.innerText); if (!t || t.length > 30) return;
    if (closestDeep(up(e) || e, NAVSEL)) return;
    if (getComputedStyle(e).cursor === 'pointer' && e.children.length <= 1) cand.add(e);
  });
  const navs = [];
  cand.forEach(e => {
    if (!vis(e)) return;
    const text = clean(e.innerText || e.value || e.getAttribute('aria-label') || e.title || e.alt || '');
    if (!text) return;
    navs.push({ uid: stamp(e), text: text.slice(0, 80), tag: e.tagName,
      disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true' || /\bdisabled\b/.test(e.className || ''),
      modal: modals.some(m => containsDeep(m, e)) });
  });
  const href = location.href || '';
  const isGoogle = /accounts\.google\.com/i.test(href) || !!document.querySelector('a[href*="accounts.google.com"], button[id*="google" i], div[id*="g_id_onload" i], [aria-label*="Google" i]');
  const isOAuth = isGoogle || /login\.microsoftonline\.com|auth0\.com|\/oauth2?\/|\/auth\/|\/signin|\/saml/i.test(href);
  return {
    url: location.href, questions: out, navs,
    text: (document.body ? document.body.innerText : '').slice(0, 4000),
    hasPassword: deepAll(document, 'input[type=password]').some(vis),
    isGoogle: isGoogle,
    isOAuth: isOAuth
  };
}
"""

STATE_JS = r"""el => el.checked === true ||
  ['aria-checked','aria-selected','aria-pressed'].some(a => el.getAttribute(a) === 'true') ||
  /\b(selected|active|checked|chosen|is-selected|picked)\b/.test(el.className || '')"""

SETTLE_JS = r"""() => new Promise(res => {
  let t = setTimeout(done, 350);
  const mo = new MutationObserver(() => { clearTimeout(t); t = setTimeout(done, 350); });
  mo.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  const hard = setTimeout(done, 1500);
  function done() { clearTimeout(t); clearTimeout(hard); mo.disconnect(); res(); }
})"""

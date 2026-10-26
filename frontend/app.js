/* AICTE RAVS prototype UI - vanilla JS, talks to the FastAPI backend. */
const $ = s => document.querySelector(s);
let TOKEN = localStorage.t || '', USER = JSON.parse(localStorage.u || 'null'), LANG = 'en', CUR = null;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pill = (t, c) => `<span class="pill ${c || t}">${esc(String(t).replace(/_/g, ' '))}</span>`;
const L = { en: { Dashboard: 'Dashboard', Applications: 'Applications' }, hi: { Dashboard: 'डैशबोर्ड', Applications: 'आवेदन', 'Document Intelligence': 'दस्तावेज़ बुद्धिमत्ता', 'Document Verification': 'दस्तावेज़ सत्यापन', 'Regulatory Compliance': 'नियामक अनुपालन', 'Infrastructure Review': 'अवसंरचना समीक्षा', 'AI Findings & Reports': 'एआई निष्कर्ष एवं रिपोर्ट', 'Official Review Queue': 'अधिकारी समीक्षा कतार', 'Audit Trail': 'ऑडिट ट्रेल', Administration: 'प्रशासन' } };
const tr = k => (L[LANG] || {})[k] || k;
const NAV = [['Dashboard', 'dashboard'], ['Applications', 'applications'], ['Document Intelligence', 'documents'], ['Document Verification', 'verification'], ['Regulatory Compliance', 'compliance'], ['Infrastructure Review', 'infrastructure'], ['AI Findings & Reports', 'findings'], ['Official Review Queue', 'queue'], ['Audit Trail', 'audit'], ['Administration', 'admin']];
const ALLOW = { admin: NAV.map(n => n[1]), official: NAV.map(n => n[1]).filter(x => x != 'admin'), institution: ['dashboard', 'applications', 'documents', 'findings', 'infrastructure'] };

async function api(p, o = {}) {
  const h = {}; if (TOKEN) h.Authorization = 'Bearer ' + TOKEN; let body = o.body;
  if (body && !(body instanceof FormData)) { h['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
  const r = await fetch('/api' + p, { method: o.method || 'GET', headers: h, body });
  if (r.status == 401 && TOKEN) { logout(); throw new Error('Session expired'); }
  if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || 'Error'); }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r.blob();
}
const run = async (fn, ok) => { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { alert('⚠ ' + e.message); } };
const toast = m => { const t = document.createElement('div'); t.textContent = m; t.style = 'position:fixed;bottom:16px;right:16px;background:#138808;color:#fff;padding:9px 14px;z-index:99'; document.body.append(t); setTimeout(() => t.remove(), 2500); };
async function dl(path, name) { const b = await run(() => api(path)); if (!b) return; const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; a.click(); }
async function openFile(id) { const b = await run(() => api(`/documents/${id}/file`)); if (b) window.open(URL.createObjectURL(b)); }
function fz(d) { document.documentElement.style.fontSize = (d ? parseFloat(getComputedStyle(document.documentElement).fontSize) + d : 15) + 'px'; }
function setLang(v) { LANG = v; render(); }
function logout() { TOKEN = ''; USER = null; localStorage.clear(); location.hash = '#/'; render(); }
function modal(h) { $('#modal').innerHTML = h ? `<div class="modal-bg" onclick="if(event.target==this)modal()"><div class="modal">${h}</div></div>` : ''; }

function loginBox(hint) {
  modal(`<h3>Sign in — ${esc(hint || 'Secure Login')}</h3><label>Username</label><input id="lu" autofocus><label>Password</label><input id="lp" type="password" onkeydown="if(event.key=='Enter')doLogin()">
  <p class="sm">Demo accounts (synthetic): <span class="mono">admin/admin123</span>, <span class="mono">official1/official123</span>, <span class="mono">inst1/inst123</span>. Change before any shared deployment.</p>
  <button class="btn" onclick="doLogin()">Login</button> <button class="btn o" onclick="modal()">Cancel</button>`);
}
async function doLogin() {
  const r = await run(() => api('/login', { method: 'POST', body: { username: $('#lu').value, password: $('#lp').value } })); if (!r) return;
  TOKEN = r.token; USER = r.user; localStorage.t = TOKEN; localStorage.u = JSON.stringify(USER); modal(); location.hash = '#/dashboard'; render();
}

function chrome() {
  $('#nav').innerHTML = USER ? NAV.filter(n => ALLOW[USER.role].includes(n[1])).map(n => `<a href="#/${n[1]}" class="${(location.hash.split('/')[1] || '') == n[1] ? 'on' : ''}">${esc(tr(n[0]))}</a>`).join('') : `<a href="#/" class="on">Home</a><a href="#/help">About</a><a href="#/help">API Documentation</a><a href="#/help">Help</a>`;
  $('#tools').innerHTML = USER ? `<input id="gs" placeholder="Search institution / application / certificate no." style="width:260px;color:#000" onkeydown="if(event.key=='Enter')location.hash='#/applications?s='+encodeURIComponent(this.value)">
   <span style="position:relative"><button onclick="showNotes()" aria-label="Notifications">🔔 Notifications <span class="badge" id="nb">0</span></button><div id="nd"></div></span>
   <span style="position:relative"><button onclick="$('#pm').hidden=!$('#pm').hidden">👤 ${esc(USER.name)} ▾</button><div class="dd" id="pm" hidden><div><b>${esc(USER.name)}</b><br>Role: ${esc(USER.role)}</div><div><a href="#/help">Help</a></div><div><a href="#" onclick="logout()">Secure logout</a></div></div></span>` : `<button onclick="loginBox('Portal Login')">Login</button>`;
  if (USER) api('/notifications').then(n => { $('#nb').textContent = n.length; window.NOTES = n; }).catch(() => { });
}
function showNotes() { const d = $('#nd'); d.className = d.innerHTML ? '' : 'dd'; d.innerHTML = d.innerHTML ? '' : (window.NOTES || []).map(n => `<div>${esc(n.ts)} — ${esc(n.text)}${n.app_id ? ` <a href="#/app/${n.app_id}">open</a>` : ''}</div>`).join('') || '<div>No notifications</div>'; }

async function render() {
  chrome(); const [, page, arg] = location.hash.split('?')[0].split('/'); const m = $('#main');
  try {
    if (!USER && page != 'help') return m.innerHTML = await landing();
    if (page == 'help') return m.innerHTML = help();
    const P = { dashboard, applications, app: () => workspace(arg), documents, verification, compliance, infrastructure, findings, queue, audit, admin };
    if (page != 'app' && page && !ALLOW[USER.role].includes(page)) return m.innerHTML = '<div class="card"><h2>Access denied</h2>Your role is not permitted to view this section.</div>';
    m.innerHTML = '<div class="card">Loading…</div>'; m.innerHTML = await (P[page] || dashboard)();
    if (window.after) { window.after(); window.after = null; }
  } catch (e) { m.innerHTML = `<div class="card"><h2>Error</h2>${esc(e.message)}</div>`; }
}
window.onhashchange = render; window.onload = render;

/* ---------------------------------------------------------------- landing */
async function landing() {
  const s = await api('/public/stats').catch(() => ({ applications: 0, documents: 0, findings: 0, institutions: 0 }));
  const flow = ['Institution|submits application', 'Classify|application category', 'Load|AICTE checklist', 'OCR|document classification', 'Validate|fields & expiry', 'Cross-check|institutional records', 'Anomaly|duplicate checks', 'Verify|authorized sources', 'Evaluate|regulatory rules', 'Evidence-linked|report', 'Human review|competent authority decides'];
  const cap = [['AI Document Intelligence', 'OCR, classification and field extraction with page-level evidence and confidence.'], ['Cross-Document Consistency', 'Names, IDs, dates, courses, faculty and intake compared across documents and records.'], ['Forensics & Duplicates', 'SHA-256 and perceptual hashes, metadata review. Flags for human verification — never auto-declares forgery.'], ['Rules Engine', 'Configurable, version-tracked checklists loaded from the applicable handbook.'], ['Verification Gateway', 'QR / API / portal verification. Unavailable sources are routed to manual verification.'], ['Regulatory RAG Assistant', 'Answers cite document, page and version; refuses to answer without approved sources.'], ['Risk-Based Prioritization', 'Transparent, factor-based scores — not proof of wrongdoing.'], ['Audit & Human-in-the-Loop', 'Every rule run, view and decision logged; AI never makes final decisions.']];
  return `<div class="hero"><small>AI-POWERED APPLICATION VALIDATION · SIH 2026 · PS ID SIH26261</small><h1>Faster, evidence-linked scrutiny of AICTE applications</h1>
  <p>Automated document validation, cross-document verification and regulatory compliance checks that give officials explainable findings. AI is advisory; competent authorities make all final decisions.</p>
  <button class="btn s" onclick="loginBox('AICTE Official')">Official Login</button> <button class="btn o" onclick="location.hash='#/help'">Documentation</button></div>
  <div class="grid g4"><div class="card stat"><b>${s.applications}</b><span>Applications in demo repository</span></div><div class="card stat s1"><b>${s.institutions}</b><span>Institutions (synthetic profiles)</span></div><div class="card stat s2"><b>${s.documents}</b><span>Documents processed</span></div><div class="card stat s3"><b>${s.findings}</b><span>Open flagged items awaiting review</span></div></div>
  <h2>Access the Portal</h2><div class="grid g3"><div class="card"><h3>Institution Nodal Officer</h3><p class="sm">Submit applications, upload documents, respond to deficiencies and track resubmissions.</p><button class="btn" onclick="loginBox('Institution')">Institution Login</button></div>
  <div class="card"><h3>AICTE Official</h3><p class="sm">Review AI findings with evidence, verify sources, request corrections and record recommendations.</p><button class="btn" onclick="loginBox('AICTE Official')">Official Login</button></div>
  <div class="card"><h3>Administrator</h3><p class="sm">Manage users, configurable rules, regulation versions, knowledge base and settings.</p><button class="btn" onclick="loginBox('Administrator')">Admin Login</button></div></div>
  <h2>Process Flow</h2><div class="flow">${flow.map(f => `<div><b>${f.split('|')[0]}</b>${f.split('|')[1]}</div>`).join('')}</div>
  <h2 style="margin-top:18px">Key Capabilities</h2><div class="grid g4">${cap.map(c => `<div class="cap"><b>${c[0]}</b>${c[1]}</div>`).join('')}</div>
  <div class="disc" style="margin-top:14px">Gemini AI: <b>${s.ai ? 'configured' : 'not configured (heuristic mode) — add key in Administration'}</b>. ${esc(s.note)}.</div>`;
}
const help = () => `<div class="card"><h2>Help, Accessibility, Privacy &amp; Terms</h2><p><b>Prototype notice.</b> This is an independent demonstration system. It is not an official Government of India, Ministry of Education or AICTE portal, and shows no real application data.</p>
<p><b>Advisory AI.</b> Findings are flags for human review with evidence. They are not determinations of forgery, non-compliance or any regulatory outcome.</p>
<p><b>Verification honesty.</b> No live government verification is simulated. Without authorized credentials (e.g. DigiLocker/API Setu partner registration) documents are marked “source unavailable” and routed to manual verification.</p>
<p><b>Accessibility.</b> Skip link, text-size controls, high-contrast mode, keyboard-operable controls. Hindi labels are provided for navigation only in this prototype.</p>
<p><b>Privacy.</b> Role-based access, access logging, hashed passwords, private file storage. Replace with production-grade controls (HTTPS, SSO, encryption at rest, retention policy) before real use.</p><p><a href="#/">← Back</a></p></div>`;

/* ---------------------------------------------------------------- dashboard */
function chart(obj) { const mx = Math.max(1, ...Object.values(obj)); return Object.entries(obj).map(([k, v]) => `<div class="bar"><span>${esc(k)}</span><i style="width:${v / mx * 220}px"></i><b>${v}</b></div>`).join('') || '<span class="sm">No data</span>'; }
const aTable = (r) => `<div class="tw"><table><tr><th>Application ID</th><th>Institution</th><th>Type</th><th>Submitted</th><th>Status</th><th>Risk</th><th>Open</th></tr>${r.map(a => `<tr><td><a href="#/app/${a.id}">${a.id}</a></td><td>${esc(a.inst_name)}</td><td>${esc(a.type)}</td><td>${a.submitted}</td><td>${esc(a.status)}</td><td>${riskBadge(a)}</td><td>${a.open_issues}</td></tr>`).join('')}</table></div>`;
const riskBadge = a => pill(`${a.risk} ${a.risk_band || ''}`, a.risk >= 60 ? 'high' : a.risk >= 30 ? 'medium' : 'ok');
async function dashboard() {
  const d = await api('/dashboard'), c = d.cards;
  return `<h2>Dashboard Overview</h2><div class="grid g5">${[['Total applications', c.total, ''], ['Validations completed', c.validated, 's2'], ['Issues identified (open)', c.issues, 's3'], ['Pending source verification', c.pending_verification, 's1'], ['Manual review required', c.manual_review, 's4']].map(x => `<div class="card stat ${x[2]}"><b>${x[1]}</b><span>${x[0]}</span></div>`).join('')}</div>
  <div class="grid g2"><div class="card"><h3>Application Status</h3>${chart(d.status_chart)}</div><div class="card"><h3>AI Processing Statistics</h3><table><tr><td>Documents processed</td><td>${d.ai.docs_processed}</td></tr><tr><td>Avg. extraction confidence</td><td>${Math.round(d.ai.avg_confidence * 100)}%</td></tr><tr><td>Avg. processing time / document</td><td>${d.ai.avg_proc_ms} ms</td></tr><tr><td>Anomaly flags raised</td><td>${d.ai.anomalies}</td></tr><tr><td>OCR engine</td><td>${esc(d.ai.ocr_engine)}</td></tr></table><p class="sm">Accuracy figures on real data require labelled test sets; see Review Queue → Analytics for synthetic-test results.</p></div></div>
  <div class="grid g12"><div class="card"><h3>Priority Cases (highest risk first)</h3>${aTable(d.priority)}</div><div class="card"><h3>Notifications</h3>${d.notifications.map(n => `<div class="sm" style="padding:4px 0;border-bottom:1px solid #eee">${n.ts} — ${esc(n.text)}</div>`).join('') || 'None'}</div></div>
  <div class="card"><h3>Recent Applications</h3>${aTable(d.recent)}</div>`;
}

/* ---------------------------------------------------------------- applications */
async function applications() {
  const p = new URLSearchParams(location.hash.split('?')[1] || ''); const s = p.get('s') || '', st = p.get('status') || '';
  const r = await api(`/applications?s=${encodeURIComponent(s)}&status=${encodeURIComponent(st)}`);
  const statuses = ['', 'Submitted', 'Deficiencies Identified', 'Manual Review Required', 'Verification Pending', 'Ready for Scrutiny', 'Corrections Requested', 'Resubmitted', 'Forwarded for Scrutiny'];
  let inst = USER.role != 'official' ? await api('/institutions') : [];
  return `<h2>Applications</h2><div class="card"><div class="row"><div><label>Search (institution, ID, certificate no.)</label><input id="fs" value="${esc(s)}"></div><div><label>Status</label><select id="fst">${statuses.map(x => `<option ${x == st ? 'selected' : ''}>${x}</option>`).join('')}</select></div><button class="btn" onclick="location.hash='#/applications?s='+encodeURIComponent($('#fs').value)+'&status='+encodeURIComponent($('#fst').value)">Filter</button></div></div>
  <div class="card">${aTable(r)}</div>
  ${USER.role != 'official' ? `<div class="card"><h3>Register New Application</h3><div class="row"><div><label>Institution</label><select id="ni">${inst.filter(i => USER.role == 'admin' || i.id == USER.inst_id).map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join('')}</select></div><div><label>Category</label><select id="nt"><option>Extension of Approval</option></select></div><div><label>Application date</label><input id="nd2" type="date" value="${new Date().toISOString().slice(0, 10)}"></div></div>
  <label>Course = intake (one per line)</label><textarea id="nc" rows="3" placeholder="B.E. Computer Science and Engineering=180"></textarea><br><button class="btn s" onclick="newApp()">Create application</button></div>` : ''}`;
}
async function newApp() {
  const ci = {}; $('#nc').value.split('\n').forEach(l => { const [a, b] = l.split('='); if (a && b) ci[a.trim()] = +b; });
  const r = await run(() => api('/applications', { method: 'POST', body: { inst_id: +$('#ni').value, type: $('#nt').value, application_date: $('#nd2').value, course_intake: ci } }), 'Application created'); if (r) location.hash = '#/app/' + r.id;
}

/* ---------------------------------------------------------------- scrutiny workspace */
const FIELD_LBL = { institution_name: 'Institution name', certificate_number: 'Certificate no.', issuing_authority: 'Issuing authority', issue_date: 'Issue date', expiry_date: 'Expiry date', registration_number: 'Registration no.', application_date: 'Application date', course_intake: 'Courses / intake', faculty: 'Faculty', view: 'View label' };
function hl(text, needles, sel) {
  let h = esc(text);
  [...new Set(needles.filter(Boolean).map(String))].sort((a, b) => b.length - a.length).forEach(n => { const e = esc(n).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); h = h.replace(new RegExp(`(?![^<]*>)(${e})`, 'gi'), `<mark class="${sel && sel == n ? 'sel' : ''}">$1</mark>`); });
  return h;
}
async function workspace(id) {
  const d = await api('/applications/' + id); CUR = d; const a = d.app, off = USER.role != 'institution', docs = d.documents.filter(x => !x.superseded);
  window.selDoc = window.selDoc && docs.find(x => x.id == window.selDoc) ? window.selDoc : (docs[0] || {}).id; window.selEv = null;
  const r = d.risk, col = r.score >= 60 ? '#b3261e' : r.score >= 30 ? '#ff9933' : '#138808';
  window.after = () => { tab('findings'); viewDoc(window.selDoc); };
  return `<h2>Application Scrutiny Workspace — ${a.id}</h2>
  <div class="disc"><b>AI-generated findings are advisory.</b> Final statutory scrutiny and regulatory decisions belong to the competent authority. Ruleset: ${esc(d.ruleset)}.</div>
  <div class="card"><div class="grid g3"><div><b>${esc(d.institution.name)}</b><br><span class="sm">${esc(d.institution.city)}, ${esc(d.institution.state)} · ${esc(d.institution.category)} · ${esc(d.institution.source)}</span><br>${esc(a.type)} · Submitted ${a.submitted}<br>Assigned: ${esc(a.assigned_to || '-')}</div>
  <div>Status: <b>${esc(a.status)}</b><br>Risk score <b>${r.score}</b> (${r.band}) <div class="meter"><i style="width:${r.score}%;background:${col}"></i></div><span class="sm">Factors: ${esc(r.factors.join('; ') || 'none')}. Prioritization aid only — not evidence of wrongdoing.</span></div>
  <div><button class="btn sm" onclick="act('validate')">↻ Revalidate</button> ${off ? `<button class="btn sm" onclick="act('verify')">Run source verification</button>` : ''} <button class="btn sm o" onclick="dl('/applications/${a.id}/report.pdf','validation_report_${a.id}.pdf')">⬇ PDF report</button>
  <br><label>Upload documents (PDF / image / txt)</label><input type="file" id="up" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.txt"><button class="btn sm s" onclick="upload()">Upload &amp; analyse</button></div></div></div>
  <div class="grid g2"><div class="card"><h3>Document Viewer (OCR text with evidence highlighting)</h3><select id="dsel" onchange="viewDoc(this.value)">${docs.map(x => `<option value="${x.id}">${esc(x.filename)} — ${esc(x.doc_type)}</option>`).join('')}</select><div id="dv"></div></div>
  <div class="card"><h3>Extracted Fields &amp; Classification</h3><div id="fv"></div></div></div>
  <div class="tabs" id="tabs">${['findings:AI Findings', 'checklist:Compliance Checklist', 'verify:Source Verification', 'history:History Comparison', 'review:Review & Comments', 'docs:Documents & Rectification', 'time:Timeline'].map(t => `<a id="t_${t.split(':')[0]}" onclick="tab('${t.split(':')[0]}')">${t.split(':')[1]}</a>`).join('')}</div><div id="tabc"></div>`;
}
function viewDoc(id) {
  window.selDoc = +id; const d = CUR.documents.find(x => x.id == id); if (!d) { $('#dv').innerHTML = '<p class="sm">No documents uploaded yet.</p>'; $('#fv').innerHTML = ''; return; }
  const f = d.fields, needles = [...Object.entries(f).flatMap(([k, v]) => k == 'course_intake' ? Object.keys(v) : k == 'faculty' ? v.flatMap(x => [x.name, x.id]) : (k != 'view' && k != 'issues' ? [v] : []))];
  const ev = window.selEv; if (ev) needles.push(ev);
  $('#dsel').value = id;
  $('#dv').innerHTML = `<div class="sm">Type: <b>${esc(d.doc_type)}</b> · OCR: ${esc(d.method)} · Extraction: ${esc(d.source)} · Confidence ${Math.round(d.confidence * 100)}% · v${d.version} ${d.synthetic ? '· <b>SYNTHETIC</b>' : ''} ${d.filename.match(/\.(pdf|png|jpe?g|webp)$/i) ? `<a href="#" onclick="openFile(${d.id});return false">open original</a>` : ''}</div>` +
    d.pages.map((p, i) => `<div class="sm" style="margin-top:6px">Page ${i + 1}</div><div class="view" id="pg${i + 1}">${hl(p, needles, ev)}</div>`).join('') +
    `<div class="sm">SHA-256: <span class="mono">${d.sha256.slice(0, 20)}…</span> ${d.meta && d.meta.producer ? ' · Producer: ' + esc(d.meta.producer) : ''}</div>`;
  const rows = Object.entries(f).filter(([k]) => k != 'issues').map(([k, v]) => { const e = d.evidence[k]; const val = k == 'course_intake' ? Object.entries(v).map(([a, b]) => `${esc(a)}: ${b}`).join('<br>') : k == 'faculty' ? v.map(x => `${esc(x.name)} (${esc(x.id)})`).join('<br>') : esc(v); const c = d.field_conf[k];
    return `<tr><td>${FIELD_LBL[k] || k}</td><td>${val}</td><td>${c ? Math.round(c * 100) + '%' : '-'}</td><td class="sm">${e ? `p.${e.page}: “${esc(e.text.slice(0, 60))}”` : '-'}</td></tr>`; }).join('');
  $('#fv').innerHTML = `<table><tr><th>Field</th><th>Value</th><th>Conf.</th><th>Evidence</th></tr>${rows || '<tr><td colspan=4>No fields extracted</td></tr>'}</table>
  ${d.missing_fields.length ? `<p class="warn disc">Missing/unreadable fields: <b>${d.missing_fields.join(', ')}</b>${d.confidence < .6 ? ' — low confidence, manual correction requested.' : ''}</p>` : ''}
  <button class="btn sm o" onclick="correct(${d.id})">✎ Manual correction</button> <span class="sm">Corrections are audit-logged.</span>`;
}
async function correct(id) { const k = prompt('Field to correct (institution_name, certificate_number, issuing_authority, issue_date, expiry_date, registration_number):'); if (!k) return; const v = prompt('Correct value (dates as YYYY-MM-DD):'); if (v == null) return; await run(() => api(`/documents/${id}/fields`, { method: 'PUT', body: { fields: { [k]: v } } }), 'Correction saved; revalidated'); render(); }
function tab(t) {
  document.querySelectorAll('#tabs a').forEach(a => a.classList.toggle('on', a.id == 't_' + t)); const d = CUR, off = USER.role != 'institution'; let h = '';
  if (t == 'findings') h = d.findings.map(f => `<div class="fnd ${f.severity}"><div class="row" style="align-items:center"><div><b>${esc(f.title)}</b> ${pill(f.severity)} ${pill(f.status)} <span class="sm">${esc(f.category)}</span></div></div>
    <div><b>Why flagged:</b> ${esc(f.reason)}</div><div class="sm"><b>Rule reference:</b> ${esc(f.rule_ref)}</div>
    ${(f.evidence || []).map(e => `<div class="ev" onclick="goEv(${e.doc_id || 0},${JSON.stringify(String(e.value ?? e.text ?? '')).replace(/"/g, '&quot;')})">📄 ${esc(e.doc)} ${e.page ? '· page ' + e.page : ''} ${e.field ? '· ' + esc(e.field) : ''}: <b>${esc(typeof e.value == 'object' ? '' : e.value)}</b> ${e.text ? `— “${esc(e.text)}”` : ''}</div>`).join('')}
    <div class="sm"><b>Recommended action:</b> ${esc(f.action)} ${f.note ? `· Reviewer note: ${esc(f.note)}` : ''}</div>
    ${off ? `<div style="margin-top:5px"><button class="btn sm g" onclick="fs(${f.id},'valid')">Mark valid</button> <button class="btn sm o" onclick="fs(${f.id},'false_positive')">False positive</button> <button class="btn sm o" onclick="fs(${f.id},'resolved')">Resolved</button> <button class="btn sm o" onclick="fs(${f.id},'open')">Reopen</button></div>` : ''}</div>`).join('') || '<div class="card">No findings.</div>';
  if (t == 'checklist') h = `<div class="tw"><table><tr><th>Rule</th><th>Requirement</th><th>Reference</th><th>Version</th><th>Severity</th><th>Outcome</th></tr>${d.checklist.map(c => `<tr><td>${c.code}</td><td>${esc(c.title)}</td><td class="sm">${esc(c.ref)}<br><i>${esc(c.note)}</i></td><td class="sm">${esc(c.version)}</td><td>${pill(c.severity)}</td><td>${pill(c.outcome, c.outcome.startsWith('No') ? 'ok' : 'high')}</td></tr>`).join('')}</table></div><p class="sm">Rules are configurable by administrators and shown with rule reference and version. Demo rules must be verified against the official handbook before use.</p>`;
  if (t == 'verify') h = `<div class="disc warn">No live government verification is simulated. Where no authorized integration is configured the status is “source unavailable” and manual verification is required.</div><div class="tw"><table><tr><th>Time</th><th>Document</th><th>Source</th><th>Status</th><th>Response / notes</th><th>Ref</th><th></th></tr>${d.verifications.map(v => { const dd = d.documents.find(x => x.id == v.doc_id) || {}; return `<tr><td>${v.ts}</td><td>${esc(dd.filename)}</td><td>${esc(v.source)}</td><td>${pill(v.status)}</td><td class="sm">${esc(v.response)}</td><td class="mono">${v.reference}</td><td>${off ? `<button class="btn sm" onclick="manualV(${v.id})">Record manual result</button>` : ''}</td></tr>`; }).join('')}</table></div>`;
  if (t == 'history') { const p = d.previous.approved_intake, s = d.previous.submitted || {}; const keys = [...new Set([...Object.keys(p), ...Object.keys(s)])];
    h = `<table><tr><th>Course</th><th>Previous approved intake</th><th>Submitted intake</th><th>Source</th><th>Discrepancy</th></tr>${keys.map(k => { const a = p[k], b = s[k], bad = a == null || b == null || b > a; return `<tr><td>${esc(k)}</td><td>${a ?? '— (not approved)'}</td><td>${b ?? '— (dropped)'}</td><td class="sm">Institution profile (${esc(d.institution.source)}) vs Application</td><td>${bad ? pill(a == null ? 'new course' : b == null ? 'removed' : 'increase', 'high') : pill('none', 'ok')}</td></tr>`; }).join('')}</table>
    <h3 style="margin-top:10px">Faculty on record</h3>${(d.institution.faculty || []).map(f => `<div class="sm">${esc(f.name)} · ${esc(f.id)} · ${esc(f.qualification)}</div>`).join('')}`; }
  if (t == 'review') h = `<div class="grid g2"><div class="card"><h3>Comments &amp; correction requests</h3>${d.comments.map(c => `<div class="sm" style="border-bottom:1px solid #eee;padding:4px 0"><b>${esc(c.user)}</b> (${c.role}) ${pill(c.kind, 'low')} ${c.ts}<br>${esc(c.text)}</div>`).join('') || '<span class="sm">None</span>'}
    <textarea id="cm" rows="3" placeholder="Write a comment…"></textarea><button class="btn sm" onclick="cmt('comment')">Add comment</button> ${off ? `<button class="btn sm s" onclick="cmt('correction_request')">Send as correction request to institution</button>` : ''}</div>
    ${off ? `<div class="card"><h3>Official review (human-in-the-loop)</h3><p class="sm">Records the official's recommendation. Final decisions are made by the competent authority.</p><label>Reviewer note (mandatory for recommendations)</label><textarea id="dn" rows="3"></textarea>
    <button class="btn sm g" onclick="dec('forward_for_scrutiny')">Forward for scrutiny</button> <button class="btn sm s" onclick="dec('request_corrections')">Request corrections</button> <button class="btn sm" onclick="dec('recommend_approve')">Favourable recommendation</button> <button class="btn sm r" onclick="dec('recommend_reject')">Adverse recommendation</button></div>` : ''}</div>`;
  if (t == 'docs') h = `<div class="tw"><table><tr><th>File</th><th>Type</th><th>Version</th><th>State</th><th>Uploaded</th><th>Rectification</th></tr>${d.documents.map(x => `<tr><td>${esc(x.filename)}</td><td>${esc(x.doc_type)}</td><td>v${x.version}</td><td>${x.superseded ? pill('superseded (retained)', 'false_positive') : pill('current', 'ok')}</td><td>${x.uploaded_at}</td><td>${x.superseded ? '' : `<input type="file" id="rp${x.id}" style="width:170px"> <button class="btn sm" onclick="replaceDoc(${x.id})">Replace</button>`}</td></tr>`).join('')}</table></div><p class="sm">Replacing a document keeps the previous version in audit history and revalidates automatically; resolved issues are marked as resolved.</p>`;
  if (t == 'time') h = `<table><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr>${d.timeline.map(x => `<tr><td>${x.ts}</td><td>${esc(x.user)}</td><td>${esc(x.action)}</td><td class="sm">${esc(x.detail)}</td></tr>`).join('')}</table>`;
  $('#tabc').innerHTML = h;
}
function goEv(did, val) { if (did) { window.selEv = val; viewDoc(did); const m = document.querySelector('#dv mark.sel') || document.querySelector('#dv mark'); if (m) m.scrollIntoView({ block: 'center' }); } }
const act = async k => { const r = await run(() => api(`/applications/${CUR.app.id}/${k}`, { method: 'POST' }), 'Done'); if (r) render(); };
const fs = async (id, s) => { const n = s == 'open' ? '' : (prompt('Reviewer note (optional):') || ''); await run(() => api(`/findings/${id}/status`, { method: 'POST', body: { status: s, note: n } }), 'Saved'); render(); };
const cmt = async k => { if (!$('#cm').value) return; await run(() => api(`/applications/${CUR.app.id}/comments`, { method: 'POST', body: { text: $('#cm').value, kind: k } }), 'Sent'); render(); };
const dec = async k => { await run(() => api(`/applications/${CUR.app.id}/decision`, { method: 'POST', body: { decision: k, note: $('#dn').value } }), 'Recorded'); render(); };
const manualV = async id => { const s = prompt('Status: verified / mismatch_detected / expired / pending / source_unavailable / manual_review_required'); if (!s) return; const n = prompt('Verification note (who/how verified):') || ''; await run(() => api(`/verifications/${id}/manual`, { method: 'POST', body: { status: s, note: n } }), 'Recorded'); render(); };
async function upload() { const f = $('#up').files; if (!f.length) return alert('Choose files'); const fd = new FormData(); [...f].forEach(x => fd.append('files', x)); $('#up').disabled = true; await run(() => api(`/applications/${CUR.app.id}/documents`, { method: 'POST', body: fd }), 'Uploaded, OCR & validation complete'); render(); }
async function replaceDoc(id) { const f = $('#rp' + id).files[0]; if (!f) return alert('Choose a replacement file'); const fd = new FormData(); fd.append('file', f); await run(() => api(`/documents/${id}/replace`, { method: 'POST', body: fd }), 'Resubmitted & revalidated'); render(); }

/* ---------------------------------------------------------------- other modules */
async function documents() {
  const [d, a] = await Promise.all([api('/documents'), api('/applications')]);
  return `<h2>Document Intelligence — OCR, Classification &amp; Completeness</h2><div class="disc">OCR: pypdf for text PDFs; Gemini vision for scans/images (when key configured); optional PaddleOCR/Tesseract. Classification and extraction use Gemini + deterministic patterns. Low-confidence results request manual correction.</div>
  <div class="card"><h3>Upload &amp; analyse</h3><div class="row"><div><label>Application</label><select id="ua">${a.map(x => `<option>${x.id}</option>`).join('')}</select></div><div><label>Files</label><input type="file" id="uf" multiple></div><button class="btn s" onclick="upl2()">Run OCR + classification</button></div></div>
  <div class="card tw"><table><tr><th>Application</th><th>File</th><th>Classified as</th><th>Confidence</th><th>Key fields</th><th>Missing fields</th><th>OCR / extraction</th></tr>${d.map(x => `<tr><td><a href="#/app/${x.app_id}">${x.app_id.slice(-4)}</a></td><td>${esc(x.filename)} ${x.synthetic ? '<span class="sm">(synthetic)</span>' : ''}</td><td>${esc(x.doc_type)}</td><td>${pill(Math.round(x.confidence * 100) + '%', x.confidence < .6 ? 'high' : x.confidence < .8 ? 'medium' : 'ok')}</td><td class="sm">${esc(x.fields.certificate_number || '')} ${esc(x.fields.issue_date || '')} → ${esc(x.fields.expiry_date || '')}</td><td class="sm">${(x.missing_fields || []).join(', ') || '-'}</td><td class="sm">${esc(x.method)} / ${esc(x.source)}</td></tr>`).join('')}</table></div>`;
}
async function upl2() { const f = $('#uf').files; if (!f.length) return; const fd = new FormData(); [...f].forEach(x => fd.append('files', x)); await run(() => api(`/applications/${$('#ua').value}/documents`, { method: 'POST', body: fd }), 'Processed'); render(); }
async function verification() {
  const [v, du, a] = await Promise.all([api('/verifications'), USER.role != 'institution' ? api('/duplicates') : { exact: [], certificate_reuse: [] }, api('/applications')]);
  return `<h2>Document Verification</h2><div class="disc warn"><b>Honesty notice:</b> This prototype does not call DigiLocker, API Setu, NAD, NBA or any issuing-authority API. Results below are “source unavailable” until authorized credentials are configured; officials record manual outcomes. See README → Integrating real verification.</div>
  <div class="card"><b>Status legend:</b> ${['verified', 'mismatch_detected', 'expired', 'pending', 'source_unavailable', 'manual_review_required'].map(s => pill(s)).join(' ')}${USER.role != 'institution' ? `<div class="row" style="margin-top:8px"><div><label>Run gateway for application</label><select id="va">${a.map(x => `<option>${x.id}</option>`).join('')}</select></div><button class="btn" onclick="run(()=>api('/applications/'+$('#va').value+'/verify',{method:'POST'}),'Gateway run').then(render)">Run verification</button></div>` : ''}</div>
  <div class="card tw"><h3>Verification Evidence Log</h3><table><tr><th>Time</th><th>Application</th><th>Document</th><th>Source</th><th>Status</th><th>Response</th><th>Ref</th></tr>${v.map(x => `<tr><td>${x.ts}</td><td><a href="#/app/${x.app_id}">${x.app_id.slice(-4)}</a></td><td>${esc(x.filename)}</td><td>${esc(x.source)}</td><td>${pill(x.status)}</td><td class="sm">${esc(x.response)}</td><td class="mono">${x.reference}</td></tr>`).join('')}</table></div>
  <div class="card"><h3>Duplicate Document Registry</h3>${du.exact.map(g => `<div class="fnd high">Identical content (SHA-256 ${g[0].sha256.slice(0, 12)}…): ${g.map(d => `${esc(d.filename)} (${d.app_id.slice(-4)})`).join(' = ')}</div>`).join('') || '<span class="sm">No exact duplicates</span>'}${du.certificate_reuse.map(g => `<div class="fnd critical">Certificate no. ${esc(g.certificate_number)} used by different institutions: ${g.docs.map(d => esc(d.fields.institution_name)).join(' / ')}</div>`).join('')}<p class="sm">Flags are for human verification; they do not establish forgery.</p></div>`;
}
async function compliance() {
  const [r, st] = await Promise.all([api('/rules'), USER.role != 'institution' ? api('/rag/status') : { sources: [] }]);
  window.after = () => { };
  return `<h2>Regulatory Compliance</h2><div class="grid g2"><div class="card"><h3>Active Rules Engine (configurable)</h3><div class="tw"><table><tr><th>Code</th><th>Type</th><th>Requirement</th><th>Severity</th><th>Version</th><th>On</th></tr>${r.map(x => `<tr><td>${x.code}</td><td>${esc(x.app_type)}</td><td class="sm">${esc(x.title)}</td><td>${pill(x.severity)}</td><td class="sm">${esc(x.version)}</td><td>${x.active ? '✔' : '—'}</td></tr>`).join('')}</table></div><p class="sm">Reference: ${esc(r[0] ? r[0].ref : '')}. ${esc(r[0] ? r[0].note : '')} Administrators edit rules in Administration.</p></div>
  <div class="card"><h3>Handbook RAG Assistant</h3>${st.sources.length ? `<div class="sm">Knowledge base: ${st.sources.map(s => `${esc(s.source)} (${esc(s.version)}, ${s.chunks} passages)`).join('; ')}</div>` : '<div class="disc warn">No regulatory document ingested yet. Administrator: Administration → Regulatory Knowledge Base → upload the official AICTE Approval Process Handbook PDF. The assistant will not answer from memory.</div>'}
  <textarea id="rq" rows="3" placeholder="e.g. What documents are required for Extension of Approval?"></textarea><button class="btn" onclick="ask()">Ask</button><div id="ra" style="margin-top:8px"></div></div></div>`;
}
async function ask() { $('#ra').innerHTML = 'Searching approved documents…'; const r = await run(() => api('/rag/ask', { method: 'POST', body: { question: $('#rq').value } })); if (!r) return; $('#ra').innerHTML = `<div class="card" style="white-space:pre-wrap">${esc(r.answer)}</div>` + r.citations.map((c, i) => `<div class="fnd low"><b>[${i + 1}] ${esc(c.source)}</b> · ${esc(c.version)} · page ${c.page} ${esc(c.section)}<div class="sm">${esc(c.text)}…</div></div>`).join('') + '<p class="sm">Advisory only; not an official interpretation.</p>'; }
async function infrastructure() {
  const d = await api('/infrastructure');
  return `<h2>Infrastructure Review</h2><div class="disc warn">${esc(d.disclaimer)}</div><div class="grid g2"><div class="card"><h3>Evidence received</h3><table><tr><th>Application</th><th>File</th><th>Type</th><th>View label</th></tr>${d.documents.map(x => `<tr><td><a href="#/app/${x.app_id}">${x.app_id.slice(-4)}</a></td><td>${esc(x.filename)}</td><td>${esc(x.doc_type)}</td><td>${esc(x.fields.view || '-')}</td></tr>`).join('')}</table><p class="sm">Required views (configurable in code): ${d.required_views.join(', ')}. Upload photos named e.g. <i>classroom_1.jpg</i>, or with a Gemini key the view is read from the image.</p></div>
  <div class="card"><h3>Flags requiring clarification / inspection</h3>${d.findings.map(f => `<div class="fnd ${f.severity}"><b>${esc(f.title)}</b> ${pill(f.severity)} <a href="#/app/${f.app_id}">${f.app_id.slice(-4)}</a><div class="sm">${esc(f.reason)}</div></div>`).join('') || '<span class="sm">No infrastructure flags. Upload floor plans / photographs to an application to trigger the review.</span>'}</div></div>`;
}
async function findings() {
  const p = new URLSearchParams(location.hash.split('?')[1] || ''), sv = p.get('severity') || '', ct = p.get('category') || '', stt = p.get('status') || '';
  const f = await api(`/findings?severity=${sv}&category=${encodeURIComponent(ct)}&status=${stt}`);
  const cats = ['', 'Missing Document', 'Expired Document', 'Cross-Document Mismatch', 'Intake Discrepancy', 'Course Discrepancy', 'Duplicate Document', 'Metadata Anomaly', 'Faculty Verification', 'Infrastructure Evidence', 'Date Conflict', 'Low OCR Confidence', 'Incomplete Document'];
  const sel = (id, arr, v) => `<select id="${id}">${arr.map(x => `<option ${x == v ? 'selected' : ''}>${x}</option>`).join('')}</select>`;
  return `<h2>AI Findings &amp; Reports</h2><div class="card"><div class="row"><div><label>Severity</label>${sel('fsv', ['', 'critical', 'high', 'medium', 'low'], sv)}</div><div><label>Category</label>${sel('fct', cats, ct)}</div><div><label>Status</label>${sel('fst2', ['', 'open', 'valid', 'resolved', 'false_positive'], stt)}</div><button class="btn" onclick="location.hash='#/findings?severity='+$('#fsv').value+'&category='+encodeURIComponent($('#fct').value)+'&status='+$('#fst2').value">Apply</button></div></div>
  <div class="card tw"><table><tr><th>Application</th><th>Institution</th><th>Finding</th><th>Severity</th><th>Status</th><th>Evidence (doc · page)</th><th>Report</th></tr>${f.map(x => `<tr><td><a href="#/app/${x.app_id}">${x.app_id.slice(-4)}</a></td><td>${esc(x.inst_name)}</td><td><b>${esc(x.title)}</b><div class="sm">${esc(x.reason)}</div></td><td>${pill(x.severity)}</td><td>${pill(x.status)}</td><td class="sm">${(x.evidence || []).map(e => esc(e.doc) + (e.page ? ' · p.' + e.page : '')).join('<br>')}</td><td><a href="#" onclick="dl('/applications/${x.app_id}/report.pdf','report_${x.app_id}.pdf');return false">PDF</a></td></tr>`).join('')}</table></div>`;
}
async function queue() {
  const [q, an] = await Promise.all([api('/review-queue'), api('/analytics')]);
  return `<h2>Official Review Queue</h2><div class="card"><p class="sm">Ranked by documented unresolved issues and configured severity weights (critical 25, high 15, medium 8, low 3; capped at 100). Not a finding of wrongdoing.</p>${aTable(q)}</div>
  <h2>Analytics &amp; Performance</h2><div class="grid g3"><div class="card stat"><b>${an.avg_processing_ms} ms</b><span>Average processing time / application (system time)</span></div><div class="card stat s2"><b>${Math.round(an.ocr_extraction_completeness * 100)}%</b><span>Documents with all expected fields extracted</span></div><div class="card stat s1"><b>${an.false_positive_rate == null ? 'n/a' : Math.round(an.false_positive_rate * 100) + '%'}</b><span>False-positive rate (${an.reviewed_flags} reviewed flags)</span></div></div>
  <div class="grid g2"><div class="card"><h3>Common deficiencies</h3>${chart(Object.fromEntries(an.common_deficiencies))}</div><div class="card"><h3>Reviewer workload</h3>${chart(an.reviewer_workload)}<p class="sm"><b>Synthetic labelled test:</b> ${an.detection_recall_synthetic.detected}/${an.detection_recall_synthetic.expected} expected issues detected. ${esc(an.detection_recall_synthetic.note)}</p><p class="sm"><b>Potential manual-work reduction:</b> ≈ ${an.manual_effort.estimated_hours_saved_on_current_docs} h on current documents. ${esc(an.manual_effort.note)}</p></div></div>`;
}
async function audit() {
  const s = new URLSearchParams(location.hash.split('?')[1] || '').get('s') || ''; const a = await api('/audit?s=' + encodeURIComponent(s));
  return `<h2>Audit Trail</h2><div class="card"><div class="row"><input id="as" value="${esc(s)}" placeholder="Filter by user, action, application…"><button class="btn" onclick="location.hash='#/audit?s='+encodeURIComponent($('#as').value)">Filter</button></div></div><div class="card tw"><table><tr><th>Timestamp</th><th>User</th><th>Role</th><th>Action</th><th>Target</th><th>Detail</th></tr>${a.map(x => `<tr><td>${x.ts}</td><td>${esc(x.user)}</td><td>${x.role}</td><td>${esc(x.action)}</td><td>${esc(x.target)}</td><td class="sm">${esc(x.detail)}</td></tr>`).join('')}</table></div>`;
}
async function admin() {
  const [u, r, s] = await Promise.all([api('/users'), api('/rules'), api('/settings')]);
  return `<h2>Administration</h2><div class="grid g2"><div class="card"><h3>Gemini AI Settings</h3><p class="sm">Status: <b>${s.gemini_configured ? 'configured' : 'not configured'}</b> · model ${esc(s.gemini_model)}. Free key: aistudio.google.com/apikey (or set GEMINI_API_KEY env var).</p><label>API key</label><input id="gk" type="password" placeholder="AIza…"><label>Model</label><input id="gm" value="${esc(s.gemini_model)}"><br><button class="btn" onclick="saveSet()">Save</button></div>
  <div class="card"><h3>Regulatory Knowledge Base (RAG)</h3><p class="sm">Upload the official AICTE Approval Process Handbook PDF (download from aicte.gov.in) and name the version.</p><label>Version label</label><input id="rv" value="APH 2024-27"><label>PDF</label><input type="file" id="rf" accept=".pdf,.txt"><br><button class="btn" onclick="ingest()">Ingest</button></div></div>
  <div class="card"><h3>Rules &amp; Checklist Administration (version-tracked)</h3><div class="tw"><table><tr><th>Code</th><th>Kind</th><th>Params</th><th>Severity</th><th>Version</th><th>Active</th><th></th></tr>${r.map(x => `<tr><td>${x.code}</td><td>${x.kind}</td><td class="mono sm">${esc(JSON.stringify(x.params))}</td><td>${x.severity}</td><td class="sm">${esc(x.version)}</td><td>${x.active ? '✔' : '—'}</td><td><button class="btn sm o" onclick='editRule(${JSON.stringify(x).replace(/'/g, '&#39;')})'>Edit</button></td></tr>`).join('')}</table></div>
  <button class="btn sm s" onclick="editRule(null)">+ Add rule</button> <span class="sm">Kinds: required_doc, not_expired, field_match, intake_match, course_match, min_confidence. Do not treat demo rules as official requirements.</span></div>
  <div class="grid g2"><div class="card"><h3>Users (role-based access)</h3><table><tr><th>User</th><th>Role</th></tr>${u.map(x => `<tr><td>${esc(x.username)} — ${esc(x.name)}</td><td>${x.role}</td></tr>`).join('')}</table><div class="row"><input id="uu" placeholder="username"><input id="un" placeholder="name"><select id="ur"><option>institution</option><option>official</option><option>admin</option></select><input id="up2" type="password" placeholder="password"><input id="ui" placeholder="inst id"></div><button class="btn sm" onclick="addUser()">Save user</button></div>
  <div class="card"><h3>Data</h3><p class="sm">Reset database to synthetic demo data (deletes uploads' records).</p><button class="btn r sm" onclick="if(confirm('Reset all data to synthetic demo?'))run(()=>api('/admin/reset-demo',{method:'POST'}),'Reset').then(logout)">Reset demo data</button></div></div>`;
}
const saveSet = () => run(() => api('/settings', { method: 'PUT', body: { gemini_key: $('#gk').value || null, gemini_model: $('#gm').value } }), 'Saved').then(render);
async function ingest() { const f = $('#rf').files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f); fd.append('version', $('#rv').value); const r = await run(() => api('/rag/ingest', { method: 'POST', body: fd })); if (r) { toast(`Ingested ${r.pages} pages / ${r.chunks} passages`); render(); } }
const addUser = () => run(() => api('/users', { method: 'POST', body: { username: $('#uu').value, name: $('#un').value, role: $('#ur').value, password: $('#up2').value, inst_id: $('#ui').value ? +$('#ui').value : null } }), 'Saved').then(render);
async function editRule(x) {
  const j = prompt('Edit rule as JSON (code, app_type, ref, kind, params, severity, applicable_if, version, active, note):', JSON.stringify(x || { code: 'R99', app_type: 'Extension of Approval', ref: 'AICTE Approval Process Handbook 2024-27, <section>', kind: 'required_doc', params: { doc_type: 'land_document' }, severity: 'medium', applicable_if: {}, version: 'APH 2024-27 (demo ruleset v1)', active: 1, note: 'Verify against official handbook' }));
  if (!j) return; const b = JSON.parse(j); await run(() => api(x ? '/rules/' + x.id : '/rules', { method: x ? 'PUT' : 'POST', body: b }), 'Rule saved'); render();
}

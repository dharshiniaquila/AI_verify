"""AICTE Regulatory Intelligence & Application Verification System - API (FastAPI).
Run:  uvicorn main:app --reload --port 8000   (from the backend folder)"""
import os, io, json, secrets, datetime as dt
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Header, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import core, engine
from core import q, x, audit, now

app = FastAPI(title="AICTE RAVS (Prototype)")
TOKENS = {}


@app.on_event("startup")
def _s():
    core.seed()
    core.load_settings()


def user(authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
    t = (authorization or "").replace("Bearer ", "") or token
    if t not in TOKENS:
        raise HTTPException(401, "Not authenticated")
    return TOKENS[t]


def need(u, *roles):
    if u["role"] not in roles:
        raise HTTPException(403, f"Role '{u['role']}' is not permitted to perform this action")


def scope_app(u, app_id):
    a = q("SELECT * FROM applications WHERE id=?", (app_id,), one=True)
    if not a: raise HTTPException(404, "Application not found")
    if u["role"] == "institution" and a["inst_id"] != u["inst_id"]: raise HTTPException(403, "Not your institution's application")
    return a


class Login(BaseModel): username: str; password: str
class Status(BaseModel): status: str; note: str = ""
class Cmt(BaseModel): text: str; kind: str = "comment"
class Dec(BaseModel): decision: str; note: str = ""
class Assign(BaseModel): username: str
class NewApp(BaseModel): inst_id: int; type: str = "Extension of Approval"; application_date: Optional[str] = None; course_intake: dict = {}
class Ask(BaseModel): question: str
class RuleIn(BaseModel): code: str; app_type: str = "Extension of Approval"; ref: str; kind: str; params: dict = {}; severity: str = "medium"; applicable_if: dict = {}; version: str = ""; active: int = 1; note: str = ""
class UserIn(BaseModel): username: str; name: str; role: str; password: str; inst_id: Optional[int] = None
class Setting(BaseModel): gemini_key: Optional[str] = None; gemini_model: Optional[str] = None
class Fields(BaseModel): fields: dict; doc_type: Optional[str] = None


@app.post("/api/login")
def login(b: Login):
    u = q("SELECT * FROM users WHERE username=?", (b.username,), one=True)
    if not u or u["pw"] != core.pw(b.password):
        audit(b.username, "LOGIN_FAILED"); raise HTTPException(401, "Invalid credentials")
    t = secrets.token_urlsafe(24)
    TOKENS[t] = {k: u[k] for k in ("username", "name", "role", "inst_id")}
    audit(TOKENS[t], "LOGIN")
    return {"token": t, "user": TOKENS[t]}


@app.get("/api/me")
def me(u=Depends(user)): return u


@app.get("/api/public/stats")
def pub():
    return {"applications": q("SELECT COUNT(*) n FROM applications", one=True)["n"], "documents": q("SELECT COUNT(*) n FROM documents WHERE superseded=0", one=True)["n"],
            "findings": q("SELECT COUNT(*) n FROM findings WHERE status='open'", one=True)["n"], "institutions": q("SELECT COUNT(*) n FROM institutions", one=True)["n"],
            "ai": bool(engine.get_key()), "note": "Synthetic demonstration data"}


def app_rows(u, where="1=1", a=()):
    sql = f"SELECT a.*, i.name inst_name, i.state, (SELECT COUNT(*) FROM findings f WHERE f.app_id=a.id AND f.status='open') open_issues FROM applications a JOIN institutions i ON i.id=a.inst_id WHERE {where}"
    if u["role"] == "institution": sql += f" AND a.inst_id={int(u['inst_id'] or 0)}"
    return q(sql + " ORDER BY a.risk DESC", a)


@app.get("/api/dashboard")
def dash(u=Depends(user)):
    apps = app_rows(u)
    ids = [a["id"] for a in apps] or ["-"]
    ph = ",".join("?" * len(ids))
    fs = q(f"SELECT * FROM findings WHERE app_id IN ({ph})", ids)
    docs = q(f"SELECT * FROM documents WHERE superseded=0 AND app_id IN ({ph})", ids)
    ver = q(f"SELECT * FROM verifications WHERE app_id IN ({ph})", ids)
    st = {}
    for a in apps: st[a["status"]] = st.get(a["status"], 0) + 1
    pend = sum(1 for d in docs if d["doc_type"] in core.VERIFIABLE and not any(v["doc_id"] == d["id"] and v["status"] == "verified" for v in ver))
    return {"cards": {"total": len(apps), "validated": sum(1 for a in apps if a["status"] != "Submitted"), "issues": sum(1 for f in fs if f["status"] == "open"),
                      "pending_verification": pend, "manual_review": sum(1 for a in apps if a["status"] in ("Manual Review Required", "Deficiencies Identified"))},
            "status_chart": st, "priority": apps[:5], "recent": sorted(apps, key=lambda a: a["submitted"], reverse=True)[:8],
            "ai": {"docs_processed": len(docs), "avg_confidence": round(sum(d["confidence"] for d in docs) / max(1, len(docs)), 2),
                   "avg_proc_ms": int(sum(d["proc_ms"] for d in docs) / max(1, len(docs))), "anomalies": sum(1 for f in fs if f["category"] in ("Duplicate Document", "Metadata Anomaly")),
                   "ocr_engine": "Gemini vision + pypdf" if engine.get_key() else "pypdf / heuristics (no Gemini key set)"},
            "notifications": q("SELECT * FROM notifications ORDER BY id DESC LIMIT 8")}


@app.get("/api/applications")
def apps(u=Depends(user), s: str = "", status: str = "", type: str = ""):
    r = app_rows(u)
    s = s.lower()
    if s:
        cert = {d["app_id"] for d in q("SELECT app_id,fields FROM documents WHERE superseded=0") if s in json.dumps(d["fields"]).lower()}
        r = [a for a in r if s in a["id"].lower() or s in a["inst_name"].lower() or a["id"] in cert]
    if status: r = [a for a in r if a["status"] == status]
    if type: r = [a for a in r if a["type"] == type]
    return r


@app.post("/api/applications")
def new_app(b: NewApp, u=Depends(user)):
    need(u, "institution", "admin")
    iid = u["inst_id"] if u["role"] == "institution" else b.inst_id
    n = q("SELECT COUNT(*) n FROM applications", one=True)["n"] + 1
    aid = f"AICTE-EOA-2026-{n:04d}"
    inst = q("SELECT * FROM institutions WHERE id=?", (iid,), one=True)
    d = {"institution_name": inst["name"], "application_date": b.application_date or dt.date.today().isoformat(), "course_intake": b.course_intake}
    offs = q("SELECT username FROM users WHERE role='official'")
    load = {o["username"]: q("SELECT COUNT(*) n FROM applications WHERE assigned_to=?", (o["username"],), one=True)["n"] for o in offs}
    x("INSERT INTO applications(id,inst_id,type,submitted,status,assigned_to,data,updated) VALUES(?,?,?,?,?,?,?,?)", (aid, iid, b.type, d["application_date"], "Submitted", min(load, key=load.get), d, now()))
    audit(u, "APPLICATION_CREATED", aid, f"{b.type}; auto-assigned to {min(load, key=load.get)}")
    return {"id": aid}


@app.get("/api/applications/{aid}")
def app_detail(aid: str, u=Depends(user)):
    a = scope_app(u, aid)
    inst = q("SELECT * FROM institutions WHERE id=?", (a["inst_id"],), one=True)
    docs = q("SELECT id,app_id,filename,sha256,doc_type,fields,evidence,field_conf,missing_fields,confidence,pages,meta,method,source,version,superseded,uploaded_at,proc_ms,synthetic FROM documents WHERE app_id=? ORDER BY superseded,id", (aid,))
    fs = q("SELECT * FROM findings WHERE app_id=? ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END", (aid,))
    score, band, factors = engine.risk_score(fs)
    rules = [r for r in q("SELECT * FROM rules") if r["active"] and r["app_type"] in ("*", a["type"])]
    open_keys = {f["rule_ref"] for f in fs if f["status"] == "open"}
    checklist = [{"code": r["code"], "title": r["title"], "ref": r["ref"], "version": r["version"], "severity": r["severity"], "note": r["note"],
                  "outcome": "Not satisfied / needs review" if any(f"rule {r['code']}," in k for k in open_keys) else "No issue found"} for r in rules]
    hist = q("SELECT ts,user,action,detail FROM audit WHERE target=? ORDER BY id", (aid,))
    return {"app": a, "institution": inst, "documents": docs, "findings": fs, "risk": {"score": score, "band": band, "factors": factors},
            "verifications": q("SELECT * FROM verifications WHERE app_id=? ORDER BY id DESC", (aid,)), "comments": q("SELECT * FROM comments WHERE app_id=? ORDER BY id", (aid,)),
            "timeline": hist, "checklist": checklist, "ruleset": core.RULESET_VERSION,
            "previous": {"approved_intake": inst["approved_intake"], "submitted": a["data"].get("course_intake")}}


@app.post("/api/applications/{aid}/documents")
async def upload(aid: str, files: list[UploadFile] = File(...), u=Depends(user)):
    a = scope_app(u, aid)
    for f in files:
        raw = await f.read()
        if len(raw) > 20_000_000: raise HTTPException(413, "File too large (20 MB limit)")
        did = core.store_doc(aid, f.filename, raw, u["username"])
        audit(u, "DOCUMENT_UPLOADED", aid, f"{f.filename} (doc {did})")
    st = core.evaluate(aid, u)
    return {"status": st}


@app.post("/api/documents/{did}/replace")
async def replace(did: int, file: UploadFile = File(...), u=Depends(user)):
    old = q("SELECT * FROM documents WHERE id=?", (did,), one=True)
    scope_app(u, old["app_id"])
    raw = await file.read()
    nid = core.store_doc(old["app_id"], file.filename, raw, u["username"], version=old["version"] + 1)
    x("UPDATE documents SET superseded=1 WHERE id=?", (did,))
    audit(u, "DOCUMENT_REPLACED", old["app_id"], f'{old["filename"]} v{old["version"]} -> {file.filename} v{old["version"]+1}; previous version retained')
    x("UPDATE applications SET status='Resubmitted' WHERE id=?", (old["app_id"],))
    st = core.evaluate(old["app_id"], u)
    x("INSERT INTO comments(app_id,user,role,kind,text,ts) VALUES(?,?,?,?,?,?)", (old["app_id"], u["username"], u["role"], "resubmission", f"Replaced {old['filename']} with {file.filename}", now()))
    return {"status": st, "new_id": nid}


@app.put("/api/documents/{did}/fields")
def fix_fields(did: int, b: Fields, u=Depends(user)):
    d = q("SELECT * FROM documents WHERE id=?", (did,), one=True)
    scope_app(u, d["app_id"])
    f = {**d["fields"], **{k: v for k, v in b.fields.items() if v not in (None, "")}}
    x("UPDATE documents SET fields=?, doc_type=COALESCE(?,doc_type), confidence=MAX(confidence,0.85) WHERE id=?", (f, b.doc_type, did))
    audit(u, "FIELDS_CORRECTED", d["app_id"], f'doc {did}: {json.dumps(b.fields)}')
    return {"status": core.evaluate(d["app_id"], u)}


@app.get("/api/documents")
def documents(u=Depends(user), s: str = "", type: str = ""):
    r = q("SELECT d.id,d.app_id,d.filename,d.doc_type,d.confidence,d.fields,d.missing_fields,d.method,d.source,d.version,d.uploaded_at,d.synthetic FROM documents d WHERE superseded=0 ORDER BY id DESC")
    if u["role"] == "institution": r = [d for d in r if scope_app(u, d["app_id"])]
    if type: r = [d for d in r if d["doc_type"] == type]
    if s: r = [d for d in r if s.lower() in json.dumps(d).lower()]
    return r


@app.get("/api/documents/{did}/file")
def dfile(did: int, u=Depends(user)):
    d = q("SELECT * FROM documents WHERE id=?", (did,), one=True)
    scope_app(u, d["app_id"]); audit(u, "DOCUMENT_ACCESSED", d["app_id"], d["filename"])
    return FileResponse(d["path"], filename=d["filename"])


@app.post("/api/applications/{aid}/validate")
def revalidate(aid: str, u=Depends(user)):
    scope_app(u, aid); return {"status": core.evaluate(aid, u)}


@app.post("/api/applications/{aid}/verify")
def verify(aid: str, u=Depends(user)):
    need(u, "official", "admin"); scope_app(u, aid)
    r = {d["filename"]: core.verify_doc(d, u) for d in core.current_docs(aid) if d["doc_type"] in core.VERIFIABLE}
    core.evaluate(aid, u); return r


class Man(BaseModel): status: str; note: str


@app.post("/api/verifications/{vid}/manual")
def manual(vid: int, b: Man, u=Depends(user)):
    need(u, "official", "admin")
    if b.status not in core.STATUS_TRACK: raise HTTPException(400, "Invalid status")
    v = q("SELECT * FROM verifications WHERE id=?", (vid,), one=True)
    x("INSERT INTO verifications(app_id,doc_id,source,status,response,ts,reference,by) VALUES(?,?,?,?,?,?,?,?)",
      (v["app_id"], v["doc_id"], "Manual verification by official", b.status, b.note, now(), v["reference"], u["username"]))
    audit(u, "MANUAL_VERIFICATION", v["app_id"], f"doc {v['doc_id']} -> {b.status}: {b.note}")
    core.evaluate(v["app_id"], u); return {"ok": True}


@app.get("/api/verifications")
def verifs(u=Depends(user)):
    return q("SELECT v.*, d.filename, d.doc_type, d.fields FROM verifications v JOIN documents d ON d.id=v.doc_id ORDER BY v.id DESC")


@app.post("/api/findings/{fid}/status")
def fstatus(fid: int, b: Status, u=Depends(user)):
    need(u, "official", "admin")
    if b.status not in ("open", "valid", "resolved", "false_positive"): raise HTTPException(400, "Invalid status")
    f = q("SELECT * FROM findings WHERE id=?", (fid,), one=True)
    x("UPDATE findings SET status=?,note=?,reviewer=?,updated=? WHERE id=?", (b.status, b.note, u["username"], now(), fid))
    audit(u, "FINDING_REVIEWED", f["app_id"], f'#{fid} "{f["title"]}" -> {b.status}. Feedback stored for controlled evaluation. {b.note}')
    core.evaluate(f["app_id"], u); return {"ok": True}


@app.get("/api/findings")
def findings(u=Depends(user), severity: str = "", category: str = "", status: str = ""):
    ids = {a["id"] for a in app_rows(u)}
    r = [f for f in q("SELECT f.*, i.name inst_name FROM findings f JOIN applications a ON a.id=f.app_id JOIN institutions i ON i.id=a.inst_id ORDER BY f.id DESC") if f["app_id"] in ids]
    return [f for f in r if (not severity or f["severity"] == severity) and (not category or f["category"] == category) and (not status or f["status"] == status)]


@app.post("/api/applications/{aid}/comments")
def comment(aid: str, b: Cmt, u=Depends(user)):
    scope_app(u, aid)
    x("INSERT INTO comments(app_id,user,role,kind,text,ts) VALUES(?,?,?,?,?,?)", (aid, u["username"], u["role"], b.kind, b.text, now()))
    if b.kind == "correction_request":
        need(u, "official", "admin")
        x("UPDATE applications SET status='Corrections Requested',decision='request_corrections' WHERE id=?", (aid,))
        core.notify("correction", aid, f"Correction requested for {aid}: {b.text[:80]}")
    audit(u, b.kind.upper(), aid, b.text[:200]); return {"ok": True}


@app.post("/api/applications/{aid}/decision")
def decision(aid: str, b: Dec, u=Depends(user)):
    need(u, "official", "admin"); scope_app(u, aid)
    m = {"forward_for_scrutiny": "Forwarded for Scrutiny", "request_corrections": "Corrections Requested", "recommend_reject": "Reviewed - Adverse Recommendation (pending competent authority)", "recommend_approve": "Reviewed - Favourable Recommendation (pending competent authority)"}
    if b.decision not in m: raise HTTPException(400, "Invalid decision")
    open_f = q("SELECT COUNT(*) n FROM findings WHERE app_id=? AND status='open' AND severity IN ('critical','high')", (aid,), one=True)["n"]
    if b.decision in ("recommend_reject", "recommend_approve") and not b.note.strip(): raise HTTPException(400, "A reviewer note is mandatory (human-in-the-loop).")
    x("UPDATE applications SET status=?,decision=?,updated=? WHERE id=?", (m[b.decision], b.decision, now(), aid))
    audit(u, "OFFICIAL_DECISION", aid, f'{b.decision}; {open_f} open high/critical issues at the time; note: {b.note}. Recommendation only - final decision by competent authority.')
    return {"status": m[b.decision]}


@app.post("/api/applications/{aid}/assign")
def assign(aid: str, b: Assign, u=Depends(user)):
    need(u, "admin"); x("UPDATE applications SET assigned_to=? WHERE id=?", (b.username, aid)); audit(u, "ASSIGNED", aid, b.username); return {"ok": True}


@app.get("/api/review-queue")
def queue(u=Depends(user)):
    need(u, "official", "admin")
    return [a for a in app_rows(u, "a.status NOT IN ('Submitted')") if a["status"] != "Ready for Scrutiny" or True]


@app.get("/api/applications/{aid}/report.pdf")
def report(aid: str, u=Depends(user)):
    scope_app(u, aid); audit(u, "REPORT_GENERATED", aid)
    return Response(core.report_pdf(aid), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=validation_report_{aid}.pdf"})


@app.get("/api/institutions")
def insts(u=Depends(user)): return q("SELECT * FROM institutions")


@app.get("/api/infrastructure")
def infra(u=Depends(user)):
    ids = {a["id"] for a in app_rows(u)}
    d = [d for d in q("SELECT id,app_id,filename,doc_type,fields,confidence FROM documents WHERE superseded=0 AND doc_type IN ('infrastructure_photo','floor_plan','building_approval','fire_safety')") if d["app_id"] in ids]
    f = [f for f in q("SELECT * FROM findings WHERE category='Infrastructure Evidence'") if f["app_id"] in ids]
    return {"documents": d, "findings": f, "required_views": ["classroom", "laboratory", "library", "exterior"],
            "disclaimer": "Photographs and plans are supporting evidence only; they do not prove actual compliance. Inspection decisions rest with officials."}


@app.get("/api/duplicates")
def dups(u=Depends(user)):
    need(u, "official", "admin")
    ds = q("SELECT id,app_id,filename,sha256,phash,fields FROM documents WHERE superseded=0")
    g = {}
    for d in ds: g.setdefault(d["sha256"], []).append(d)
    return {"exact": [v for v in g.values() if len(v) > 1], "certificate_reuse": [
        {"certificate_number": c, "docs": v} for c, v in _cert(ds).items() if len({engine.norm(d["fields"].get("institution_name", "")) for d in v}) > 1]}


def _cert(ds):
    g = {}
    for d in ds:
        c = d["fields"].get("certificate_number")
        if c: g.setdefault(c, []).append(d)
    return {c: v for c, v in g.items() if len(v) > 1}


# ---- RAG (admin ingests official handbook PDF; answers cite document, page, version)
@app.post("/api/rag/ingest")
async def ingest(file: UploadFile = File(...), version: str = Form("APH 2024-27"), u=Depends(user)):
    need(u, "admin")
    raw = await file.read()
    pages, m = engine.read_file("", file.filename, raw)
    ch = engine.chunk_pages(pages)
    x("DELETE FROM chunks WHERE source=? AND version=?", (file.filename, version))
    for p, h, t in ch: x("INSERT INTO chunks(source,version,page,section,text) VALUES(?,?,?,?,?)", (file.filename, version, p, h, t))
    audit(u, "RAG_INGEST", "", f"{file.filename} ({version}) {len(pages)} pages, {len(ch)} chunks"); return {"pages": len(pages), "chunks": len(ch)}


@app.get("/api/rag/status")
def rstatus(u=Depends(user)):
    return {"sources": q("SELECT source,version,COUNT(*) chunks,MAX(page) pages FROM chunks GROUP BY source,version"), "gemini": bool(engine.get_key())}


@app.post("/api/rag/ask")
def ask(b: Ask, u=Depends(user)):
    need(u, "official", "admin")
    hits = engine.bm25(b.question, q("SELECT * FROM chunks"), 5)
    audit(u, "RAG_QUERY", "", b.question[:150])
    if not hits:
        return {"answer": "No approved regulatory document has been ingested (or nothing relevant was found). Ask an administrator to upload the official AICTE Approval Process Handbook under Administration > Regulatory Knowledge Base. I will not answer from memory.", "citations": []}
    cites = [{"source": h["source"], "version": h["version"], "page": h["page"], "section": h["section"], "text": h["text"][:500]} for h in hits]
    ctx = "\n\n".join(f'[{i+1}] {h["source"]} ({h["version"]}), p.{h["page"]}, {h["section"]}:\n{h["text"]}' for i, h in enumerate(hits))
    ans = engine.gemini("You assist AICTE officials. Answer ONLY from the numbered excerpts. Cite as [n]. If the excerpts do not answer, say so. "
                        "Do not invent regulations. This is advisory, not an official decision.\n\nEXCERPTS:\n" + ctx + "\n\nQUESTION: " + b.question)
    return {"answer": ans or "Gemini key not configured - showing the most relevant retrieved excerpts only (retrieval without generation).", "citations": cites}


# ---- admin
@app.get("/api/rules")
def rules(u=Depends(user)): return q("SELECT * FROM rules ORDER BY id")


@app.post("/api/rules")
def rule_add(b: RuleIn, u=Depends(user)):
    need(u, "admin")
    i = x("INSERT INTO rules(code,app_type,ref,title,kind,params,severity,applicable_if,version,active,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
          (b.code, b.app_type, b.ref, f"{b.kind}: {json.dumps(b.params)}", b.kind, b.params, b.severity, b.applicable_if, b.version or core.RULESET_VERSION, b.active, b.note))
    audit(u, "RULE_ADDED", "", f"{b.code} {b.kind} {b.params}"); return {"id": i}


@app.put("/api/rules/{rid}")
def rule_up(rid: int, b: RuleIn, u=Depends(user)):
    need(u, "admin")
    x("UPDATE rules SET code=?,app_type=?,ref=?,title=?,kind=?,params=?,severity=?,applicable_if=?,version=?,active=?,note=? WHERE id=?",
      (b.code, b.app_type, b.ref, f"{b.kind}: {json.dumps(b.params)}", b.kind, b.params, b.severity, b.applicable_if, b.version, b.active, b.note, rid))
    audit(u, "RULE_UPDATED", "", f"{b.code} v{b.version} active={b.active}"); return {"ok": True}


@app.get("/api/users")
def users(u=Depends(user)):
    need(u, "admin"); return q("SELECT username,name,role,inst_id FROM users")


@app.post("/api/users")
def user_add(b: UserIn, u=Depends(user)):
    need(u, "admin")
    if b.role not in ("admin", "official", "institution"): raise HTTPException(400, "bad role")
    x("INSERT OR REPLACE INTO users VALUES(?,?,?,?,?)", (b.username, b.name, b.role, core.pw(b.password), b.inst_id)); audit(u, "USER_SAVED", "", f"{b.username} ({b.role})"); return {"ok": True}


@app.get("/api/settings")
def gset(u=Depends(user)):
    need(u, "admin"); return {"gemini_configured": bool(engine.get_key()), "gemini_model": engine.SETTINGS.get("gemini_model") or engine.GEMINI_MODEL, "ruleset": core.RULESET_VERSION}


@app.put("/api/settings")
def pset(b: Setting, u=Depends(user)):
    need(u, "admin")
    for k, v in b.dict().items():
        if v: x("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
    core.load_settings(); audit(u, "SETTINGS_CHANGED", "", "Gemini settings updated (key not logged)"); return {"ok": True}


@app.post("/api/admin/reset-demo")
def reset(u=Depends(user)):
    need(u, "admin"); core.seed(reset=True); TOKENS.clear(); return {"ok": True}


@app.get("/api/audit")
def aud(u=Depends(user), s: str = ""):
    need(u, "official", "admin")
    r = q("SELECT * FROM audit ORDER BY id DESC LIMIT 500")
    return [a for a in r if s.lower() in json.dumps(a).lower()] if s else r


@app.get("/api/notifications")
def notes(u=Depends(user)): return q("SELECT * FROM notifications ORDER BY id DESC LIMIT 30")


@app.get("/api/analytics")
def analytics(u=Depends(user)):
    need(u, "official", "admin")
    fs, docs, apps_ = q("SELECT * FROM findings"), q("SELECT * FROM documents WHERE superseded=0"), q("SELECT * FROM applications")
    cat = {}
    for f in fs: cat[f["title"].split(":")[0]] = cat.get(f["title"].split(":")[0], 0) + 1
    rev = [f for f in fs if f["status"] in ("valid", "false_positive")]
    fp = sum(1 for f in rev if f["status"] == "false_positive")
    avg = int(sum(a["proc_ms"] for a in apps_) / max(1, len(apps_)))
    manual_min = 25  # ASSUMPTION (editable here): minutes of manual checking per document
    saved = round(len(docs) * manual_min / 60, 1)
    load = {}
    for a in apps_: load[a["assigned_to"]] = load.get(a["assigned_to"], 0) + 1
    # labelled synthetic test: expected issues per seeded application
    exp = {"AICTE-EOA-2026-0001": ["Missing: Affidavit", "Missing: Building Approval", "Expired: Fire Safety Certificate", "Institution name differs", "Submitted intake exceeds approved intake", "Identical file uploaded twice", "Same faculty member under different IDs", "Course not in approved records"],
           "AICTE-EOA-2026-0003": ["Expired: Accreditation Certificate", "Course not in approved records", "Missing: Affidavit"]}
    tp = tot = 0
    for aid, titles in exp.items():
        tl = [f["title"] for f in fs if f["app_id"] == aid]
        for t in titles:
            tot += 1; tp += any(t.lower() in x_.lower() for x_ in tl)
    return {"avg_processing_ms": avg, "common_deficiencies": sorted(cat.items(), key=lambda z: -z[1])[:8],
            "reviewed_flags": len(rev), "false_positive_rate": round(fp / len(rev), 2) if rev else None, "reviewer_workload": load,
            "ocr_extraction_completeness": round(sum(1 for d in docs if not d["missing_fields"]) / max(1, len(docs)), 2),
            "detection_recall_synthetic": {"detected": tp, "expected": tot, "note": "Measured only on labelled SYNTHETIC cases; not a claim about real-world accuracy."},
            "manual_effort": {"assumed_minutes_per_doc": manual_min, "estimated_hours_saved_on_current_docs": saved, "note": "Estimate based on an editable assumption, not a measured result."}}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "frontend"), html=True), name="ui")

"""Database, seed (SYNTHETIC) data, document processing, validation workflow, audit, PDF report."""
import os, json, sqlite3, hashlib, secrets, time, datetime as dt, io
import engine

_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(_env):
    for _l in open(_env):
        if "=" in _l and not _l.strip().startswith("#"):
            _k, _v = _l.strip().split("=", 1)
            if _v: os.environ.setdefault(_k, _v)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "..", "data")
UPLOADS = os.path.join(DATA, "uploads")
DB = os.path.join(DATA, "ravs.db")
os.makedirs(UPLOADS, exist_ok=True)
RULESET_VERSION = "APH 2024-27 (demo ruleset v1)"
STATUS_TRACK = ["verified", "mismatch_detected", "expired", "pending", "source_unavailable", "manual_review_required"]


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def q(sql, a=(), one=False):
    c = conn()
    rows = [dict(r) for r in c.execute(sql, a).fetchall()]
    c.close()
    for r in rows:
        for k, v in list(r.items()):
            if k in JSONF and isinstance(v, str):
                try: r[k] = json.loads(v)
                except Exception: pass
    return (rows[0] if rows else None) if one else rows


JSONF = {"data", "fields", "evidence", "field_conf", "meta", "pages", "params", "applicable_if", "approved_intake", "faculty", "missing_fields"}


def x(sql, a=()):
    c = conn()
    cur = c.execute(sql, [json.dumps(v) if isinstance(v, (dict, list)) else v for v in a])
    c.commit(); i = cur.lastrowid; c.close()
    return i


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def pw(p, salt="ravs-demo"):
    return hashlib.sha256((salt + p).encode()).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, name TEXT, role TEXT, pw TEXT, inst_id INTEGER);
CREATE TABLE IF NOT EXISTS institutions(id INTEGER PRIMARY KEY, name TEXT, aishe_code TEXT, state TEXT, city TEXT, category TEXT, established INTEGER, approved_intake TEXT, faculty TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY, inst_id INTEGER, type TEXT, submitted TEXT, status TEXT, risk INTEGER DEFAULT 0, risk_band TEXT, assigned_to TEXT, data TEXT, decision TEXT, updated TEXT, proc_ms INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, app_id TEXT, filename TEXT, path TEXT, sha256 TEXT, phash TEXT, doc_type TEXT, fields TEXT, evidence TEXT, field_conf TEXT, missing_fields TEXT, confidence REAL, pages TEXT, text TEXT, meta TEXT, method TEXT, source TEXT, version INTEGER DEFAULT 1, superseded INTEGER DEFAULT 0, uploaded_at TEXT, proc_ms INTEGER DEFAULT 0, uploaded_by TEXT, synthetic INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS findings(id INTEGER PRIMARY KEY, app_id TEXT, fkey TEXT, category TEXT, rule_ref TEXT, severity TEXT, title TEXT, reason TEXT, evidence TEXT, action TEXT, status TEXT DEFAULT 'open', note TEXT, created TEXT, updated TEXT, reviewer TEXT);
CREATE TABLE IF NOT EXISTS verifications(id INTEGER PRIMARY KEY, app_id TEXT, doc_id INTEGER, source TEXT, status TEXT, response TEXT, ts TEXT, reference TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY, app_id TEXT, user TEXT, role TEXT, kind TEXT, text TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, user TEXT, role TEXT, action TEXT, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, app_id TEXT, text TEXT, read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, code TEXT, app_type TEXT, ref TEXT, title TEXT, kind TEXT, params TEXT, severity TEXT, applicable_if TEXT, version TEXT, active INTEGER DEFAULT 1, note TEXT);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, source TEXT, version TEXT, page INTEGER, section TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
"""


def audit(user, action, target="", detail=""):
    u = user if isinstance(user, dict) else {"username": user or "system", "role": "system"}
    x("INSERT INTO audit(ts,user,role,action,target,detail) VALUES(?,?,?,?,?,?)", (now(), u["username"], u["role"], action, target, detail))


def notify(kind, app_id, text):
    if not q("SELECT id FROM notifications WHERE app_id=? AND text=?", (app_id, text), one=True):
        x("INSERT INTO notifications(ts,kind,app_id,text) VALUES(?,?,?,?)", (now(), kind, app_id, text))


def load_settings():
    engine.SETTINGS.update({r["k"]: r["v"] for r in q("SELECT * FROM settings")})


# ---------------------------------------------------------------- document processing
def store_doc(app_id, filename, raw, user="system", pages=None, meta=None, synthetic=0, version=1):
    t0 = time.time()
    sha = hashlib.sha256(raw).hexdigest()
    path = os.path.join(UPLOADS, f"{sha[:12]}_{os.path.basename(filename)}")
    open(path, "wb").write(raw)
    method = "seed-text"
    if pages is None:
        pages, method = engine.read_file(path, filename, raw)
    a = engine.analyse(pages, filename, raw)
    ext = filename.lower().rsplit(".", 1)[-1]
    if meta is None:
        meta = engine.pdf_metadata(raw) if ext == "pdf" else {}
    if ext in ("png", "jpg", "jpeg", "webp"):
        low = filename.lower()
        a["fields"]["view"] = next((v for v in ("classroom", "laboratory", "lab", "library", "exterior", "building") if v in low), "")
        a["fields"]["view"] = {"lab": "laboratory", "building": "exterior"}.get(a["fields"]["view"], a["fields"]["view"])
        if a["doc_type"] in ("unknown",):
            a["doc_type"] = "infrastructure_photo"
        if engine.get_key():
            r = engine.gemini('Describe this campus photo/plan. JSON: {"view":"classroom|laboratory|library|exterior|other","visible_labels":[str],"issues":[str: visible inconsistencies only]}',
                              [({"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg"), raw)], json_out=True)
            if isinstance(r, dict) and r.get("view"):
                a["fields"]["view"] = r["view"]; a["fields"]["issues"] = r.get("issues") or []
                a["doc_type"] = "floor_plan" if "plan" in filename.lower() else "infrastructure_photo"
    ms = int((time.time() - t0) * 1000)
    return x("""INSERT INTO documents(app_id,filename,path,sha256,phash,doc_type,fields,evidence,field_conf,missing_fields,confidence,pages,text,meta,method,source,version,uploaded_at,proc_ms,uploaded_by,synthetic)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (app_id, filename, path, sha, engine.ahash(raw) if ext in ("png", "jpg", "jpeg", "webp") else "", a["doc_type"], a["fields"], a["evidence"],
              a["field_conf"], a["missing_fields"], a["confidence"], pages, "\n".join(pages), meta, method, a["source"], version, now(), ms, user, synthetic))


def current_docs(app_id):
    return q("SELECT * FROM documents WHERE app_id=? AND superseded=0 ORDER BY id", (app_id,))


def evaluate(app_id, user="system"):
    """Run the full validation pipeline. Preserves reviewer decisions; marks vanished findings 'resolved'."""
    t0 = time.time()
    app = q("SELECT * FROM applications WHERE id=?", (app_id,), one=True)
    inst = q("SELECT * FROM institutions WHERE id=?", (app["inst_id"],), one=True)
    docs = current_docs(app_id)
    others = q("SELECT app_id,filename,fields FROM documents WHERE superseded=0 AND app_id!=?", (app_id,))
    rules = q("SELECT * FROM rules")
    found = engine.run_checks(app, inst, docs, rules, others)
    old = {f["fkey"]: f for f in q("SELECT * FROM findings WHERE app_id=?", (app_id,))}
    keys = set()
    for f in found:
        keys.add(f["key"])
        if f["key"] in old:
            x("UPDATE findings SET evidence=?,reason=?,severity=?,updated=? WHERE id=?", (f["evidence"], f["reason"], f["severity"], now(), old[f["key"]]["id"]))
            if old[f["key"]]["status"] == "resolved":
                x("UPDATE findings SET status='open',updated=? WHERE id=?", (now(), old[f["key"]]["id"]))
        else:
            x("INSERT INTO findings(app_id,fkey,category,rule_ref,severity,title,reason,evidence,action,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (app_id, f["key"], f["category"], f["rule_ref"], f["severity"], f["title"], f["reason"], f["evidence"], f["action"], now(), now()))
            if f["severity"] in ("critical", "high"):
                notify("finding", app_id, f'[{f["severity"].upper()}] {app_id}: {f["title"]}')
    for k, o in old.items():
        if k not in keys and o["status"] == "open":
            x("UPDATE findings SET status='resolved',note=?,updated=? WHERE id=?", ("Auto: no longer reproduced after revalidation", now(), o["id"]))
    fs = q("SELECT * FROM findings WHERE app_id=?", (app_id,))
    score, band, _ = engine.risk_score(fs)
    ver = q("SELECT * FROM verifications WHERE app_id=?", (app_id,))
    pending = [d for d in docs if d["doc_type"] in VERIFIABLE and not any(v["doc_id"] == d["id"] and v["status"] in ("verified",) for v in ver)]
    op = [f for f in fs if f["status"] == "open"]
    if app["decision"] in ("request_corrections", "forward_for_scrutiny") and app["status"] in ("Corrections Requested", "Forwarded for Scrutiny"):
        status = app["status"]
    elif any(f["severity"] in ("critical", "high") for f in op): status = "Deficiencies Identified"
    elif op: status = "Manual Review Required"
    elif pending: status = "Verification Pending"
    else: status = "Ready for Scrutiny"
    ms = int((time.time() - t0) * 1000) + sum(d["proc_ms"] for d in docs)
    x("UPDATE applications SET status=?,risk=?,risk_band=?,updated=?,proc_ms=? WHERE id=?", (status, score, band, now(), ms, app_id))
    audit(user, "VALIDATION_RUN", app_id, f"{RULESET_VERSION}; {len(rules)} rules loaded; {len(found)} findings; risk {score}")
    return status


VERIFIABLE = {"noc", "fire_safety", "accreditation", "building_approval", "aicte_approval_letter", "affidavit"}


def verify_doc(doc, user):
    """Official Verification Gateway. NO live government call is simulated: without authorised credentials the
    result is 'source_unavailable' and routed to manual verification. Nothing here is shown as live verification."""
    text = doc["text"] or ""
    import re
    link = (re.search(r"https?://\S+", text) or [None])[0]
    note = "No authorised integration configured (e.g. DigiLocker / API Setu issuer-verification needs partner registration). "
    if link: note += f"Verification URL found in document: {link} - open manually. "
    if doc["fields"].get("expiry_date") and doc["fields"]["expiry_date"] < dt.date.today().isoformat():
        status = "expired"; note += "Stated validity has passed."
    else:
        status = "source_unavailable"; note += "Routed to manual verification."
    x("INSERT INTO verifications(app_id,doc_id,source,status,response,ts,reference,by) VALUES(?,?,?,?,?,?,?,?)",
      (doc["app_id"], doc["id"], "Gateway (no live source configured)", status, note, now(), f'VR-{secrets.token_hex(3).upper()}', user["username"]))
    audit(user, "VERIFICATION_ATTEMPT", doc["app_id"], f'doc {doc["id"]} -> {status}')
    return status


# ---------------------------------------------------------------- SYNTHETIC seed data (clearly labelled)
def nocs(inst, no, auth, i, e, extra=""):
    return f"NO OBJECTION CERTIFICATE (SYNTHETIC TEST DOCUMENT)\nInstitution Name: {inst}\nCertificate No: {no}\nIssuing Authority: {auth}\nDate of Issue: {i}\nValid up to: {e}\n{extra}"


def seed(reset=False):
    if reset and os.path.exists(DB): os.remove(DB)
    c = conn(); c.executescript(SCHEMA); c.commit(); c.close()
    if q("SELECT 1 FROM users", one=True): load_settings(); return
    for u, n, r, p, i in [("admin", "System Administrator", "admin", "admin123", None), ("official1", "R. Krishnan (AICTE Reviewer)", "official", "official123", None),
                          ("official2", "S. Mehta (AICTE Reviewer)", "official", "official123", None), ("inst1", "Nodal Officer, Sri Vidya Institute", "institution", "inst123", 1)]:
        x("INSERT INTO users VALUES(?,?,?,?,?)", (u, n, r, pw(p), i))
    I = [(1, "Sri Vidya Institute of Engineering & Technology", "C-SYN-0001", "Tamil Nadu", "Chennai", "Private", 2003, {"B.E. Computer Science and Engineering": 180, "B.E. Electronics and Communication Engineering": 120, "B.E. Mechanical Engineering": 60},
          [{"name": "Dr. A. Kumar", "id": "F-1021", "qualification": "Ph.D. (CSE)"}, {"name": "Prof. S. Lakshmi", "id": "F-1044", "qualification": "M.E. (ECE)"}]),
         (2, "Greenfield College of Technology", "C-SYN-0002", "Maharashtra", "Pune", "Private", 2011, {"B.Tech Information Technology": 120, "B.Tech Civil Engineering": 60}, [{"name": "Dr. P. Joshi", "id": "F-2201", "qualification": "Ph.D. (IT)"}]),
         (3, "National Institute of Applied Sciences", "C-SYN-0003", "Rajasthan", "Jaipur", "Government", 1998, {"B.Tech Electrical Engineering": 90, "B.Tech Chemical Engineering": 60}, [{"name": "Dr. R. Sharma", "id": "F-3010", "qualification": "Ph.D. (EE)"}])]
    for i, n, a, s, ci, cat, est, ap, fac in I:
        x("INSERT INTO institutions VALUES(?,?,?,?,?,?,?,?,?,?)", (i, n, a, s, ci, cat, est, ap, fac, "SYNTHETIC (replace via scripts/import_aishe.py)"))
    P = [("R1", "required_doc", {"doc_type": "application_form"}, "high"), ("R2", "required_doc", {"doc_type": "noc"}, "high"), ("R3", "required_doc", {"doc_type": "affidavit"}, "high"),
         ("R4", "required_doc", {"doc_type": "building_approval"}, "high"), ("R5", "required_doc", {"doc_type": "fire_safety"}, "high"), ("R6", "required_doc", {"doc_type": "faculty_qualification"}, "medium"),
         ("R7", "not_expired", {"doc_type": "noc"}, "high"), ("R8", "not_expired", {"doc_type": "fire_safety"}, "critical"), ("R9", "not_expired", {"doc_type": "accreditation"}, "high"),
         ("R10", "field_match", {"doc_type": "noc", "field": "institution_name", "app_field": "institution_name"}, "high"), ("R11", "intake_match", {}, "high"), ("R12", "course_match", {}, "medium"),
         ("R13", "min_confidence", {"threshold": 0.6}, "low")]
    for code, k, p, sev in P:
        x("INSERT INTO rules(code,app_type,ref,title,kind,params,severity,applicable_if,version,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (code, "Extension of Approval", "AICTE Approval Process Handbook 2024-27, Extension of Approval checklist [section no. to be set by administrator]", f"{k}: {json.dumps(p)}", k, p, sev, {}, RULESET_VERSION,
           "DEMO RULE - illustrative. Verify applicability and wording against the official handbook / instructions before use."))
    A = [("AICTE-EOA-2026-0001", 1, "official1", {"institution_name": "Sri Vidya Institute of Engineering & Technology", "application_date": "2026-09-15", "course_intake": {"B.E. Computer Science and Engineering": 240, "B.E. Electronics and Communication Engineering": 120, "B.E. Artificial Intelligence and Data Science": 60}}),
         ("AICTE-EOA-2026-0002", 2, "official2", {"institution_name": "Greenfield College of Technology", "application_date": "2026-09-20", "course_intake": {"B.Tech Information Technology": 120, "B.Tech Civil Engineering": 60}}),
         ("AICTE-EOA-2026-0003", 3, "official1", {"institution_name": "National Institute of Applied Sciences", "application_date": "2026-09-25", "course_intake": {"B.Tech Electrical Engineering": 90, "B.Tech Chemical Engineering": 60}})]
    for aid, ii, off, d in A:
        x("INSERT INTO applications(id,inst_id,type,submitted,status,assigned_to,data,updated) VALUES(?,?,?,?,?,?,?,?)", (aid, ii, "Extension of Approval", d["application_date"], "Submitted", off, d, now()))

    def doc(aid, name, text, meta=None):
        store_doc(aid, name, text.encode(), pages=[text], meta=meta or {}, synthetic=1)
    af = lambda n, d, ci: f"APPLICATION FORM - EXTENSION OF APPROVAL (SYNTHETIC)\nInstitution Name: {n}\nDate of Application: {d}\n" + "\n".join(f"Course: {c} | Intake: {k}" for c, k in ci.items())
    a1, a2, a3 = [a[3] for a in A]
    N1 = "Sri Vidya Institute of Engineering & Technology"
    doc("AICTE-EOA-2026-0001", "application_form.txt", af(N1, "15/09/2026", a1["course_intake"]))
    doc("AICTE-EOA-2026-0001", "noc_state_govt.txt", nocs("Sri Vidhya Institute of Engineering and Technology", "NOC/TN/2024/00421", "Government of Tamil Nadu, Higher Education Department", "12/03/2024", "11/03/2027"))
    doc("AICTE-EOA-2026-0001", "noc_copy_final.txt", nocs("Sri Vidhya Institute of Engineering and Technology", "NOC/TN/2024/00421", "Government of Tamil Nadu, Higher Education Department", "12/03/2024", "11/03/2027"))
    doc("AICTE-EOA-2026-0001", "fire_safety.txt", f"FIRE SAFETY CERTIFICATE (SYNTHETIC)\nInstitution Name: {N1}\nCertificate No: FIRE/CHN/2021/9087\nIssuing Authority: Tamil Nadu Fire & Rescue Services\nDate of Issue: 02/06/2021\nValid up to: 01/06/2026\n",
        {"producer": "Adobe Photoshop 25.0", "created": "2021-06-02", "modified": "2026-09-10"})
    doc("AICTE-EOA-2026-0001", "faculty_list.txt", f"FACULTY DETAILS (SYNTHETIC)\nInstitution Name: {N1}\nFaculty: Dr. A. Kumar | ID: F-1021 | Ph.D. (CSE)\nFaculty: Prof. S. Lakshmi | ID: F-9981 | M.E. (ECE)\nFaculty: Dr. A. Kumar | ID: F-5530 | Ph.D. (CSE)")
    doc("AICTE-EOA-2026-0001", "aicte_approval_2025.txt", f"AICTE EXTENSION OF APPROVAL 2025-26 (SYNTHETIC)\nInstitution Name: {N1}\nApproval No: F.No.SYN/2025/0001\nDate of Issue: 10/05/2025\n" + "\n".join(f"Course: {c} | Intake: {k}" for c, k in I[0][7].items()))
    N2 = "Greenfield College of Technology"
    doc("AICTE-EOA-2026-0002", "application_form.txt", af(N2, "20/09/2026", a2["course_intake"]))
    doc("AICTE-EOA-2026-0002", "noc.txt", nocs(N2, "NOC/MH/2025/11877", "Government of Maharashtra, Higher & Technical Education", "01/02/2025", "31/01/2028"))
    doc("AICTE-EOA-2026-0002", "affidavit.txt", f"AFFIDAVIT (SYNTHETIC) - solemnly affirm before notary\nInstitution Name: {N2}\nDate of Issue: 18/09/2026\n")
    doc("AICTE-EOA-2026-0002", "building_approval.txt", f"BUILDING PLAN APPROVAL (SYNTHETIC)\nInstitution Name: {N2}\nCertificate No: PMC/BLD/2019/5521\nIssuing Authority: Pune Municipal Corporation\nDate of Issue: 14/08/2019\n")
    doc("AICTE-EOA-2026-0002", "fire_safety.txt", f"FIRE SAFETY CERTIFICATE (SYNTHETIC)\nInstitution Name: {N2}\nCertificate No: FIRE/PUN/2025/3310\nIssuing Authority: Maharashtra Fire Services\nDate of Issue: 05/03/2025\nValid up to: 04/03/2027\n")
    doc("AICTE-EOA-2026-0002", "faculty_list.txt", f"FACULTY DETAILS (SYNTHETIC)\nInstitution Name: {N2}\nFaculty: Dr. P. Joshi | ID: F-2201 | Ph.D. (IT)\n")
    N3 = "National Institute of Applied Sciences"
    a3["course_intake"]["B.Tech Mining Engineering"] = 30
    x("UPDATE applications SET data=? WHERE id=?", (a3, "AICTE-EOA-2026-0003"))
    doc("AICTE-EOA-2026-0003", "application_form.txt", af(N3, "25/09/2026", a3["course_intake"]))
    doc("AICTE-EOA-2026-0003", "accreditation_nba.txt", f"NBA ACCREDITATION CERTIFICATE (SYNTHETIC)\nInstitution Name: {N3}\nCertificate No: NBA/SYN/2021/778\nIssuing Authority: National Board of Accreditation\nDate of Issue: 01/07/2021\nValid up to: 30/06/2024\n")
    doc("AICTE-EOA-2026-0003", "noc.txt", nocs(N3, "NOC/RJ/2023/2209", "Government of Rajasthan", "10/10/2023", "09/10/2026"))
    doc("AICTE-EOA-2026-0003", "fire_safety.txt", nocs(N3, "FIRE/RJ/2023/118", "Rajasthan Fire Services", "10/10/2023", "09/10/2028").replace("NO OBJECTION CERTIFICATE", "FIRE SAFETY CERTIFICATE"))
    for aid in [a[0] for a in A]:
        evaluate(aid)
        for d in current_docs(aid):
            if d["doc_type"] in VERIFIABLE: verify_doc(d, {"username": "system", "role": "system"})
        evaluate(aid)
    audit("system", "SEED", "", "Synthetic demo data loaded. No real institution/application records.")


def report_pdf(app_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    app = q("SELECT * FROM applications WHERE id=?", (app_id,), one=True)
    inst = q("SELECT * FROM institutions WHERE id=?", (app["inst_id"],), one=True)
    fs = q("SELECT * FROM findings WHERE app_id=? ORDER BY id", (app_id,))
    docs = current_docs(app_id)
    buf = io.BytesIO(); st = getSampleStyleSheet()
    S = lambda t, s="BodyText": Paragraph(str(t).replace("&", "&amp;").replace("<", "&lt;"), st[s])
    el = [S("AICTE Regulatory Intelligence & Application Verification System", "Title"), S("AI Validation Report - ADVISORY ONLY", "Heading2"),
          S("Prototype / Demonstration System - Not an Official Government Portal. AI findings are advisory; the final regulatory decision rests with the competent authority."),
          Spacer(1, 8), S(f'Application: {app_id} | {app["type"]} | Status: {app["status"]} | Risk: {app["risk"]} ({app["risk_band"]})'),
          S(f'Institution: {inst["name"]}, {inst["city"]}, {inst["state"]} ({inst["source"]})'), S(f'Ruleset: {RULESET_VERSION} | Generated: {now()}'), Spacer(1, 8), S("Documents", "Heading3")]
    t = Table([["File", "Type", "Conf.", "Method"]] + [[d["filename"], engine.DOC_LABEL.get(d["doc_type"]), f'{d["confidence"]:.0%}', d["method"]] for d in docs])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2a5b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    el += [t, Spacer(1, 10), S(f"Findings ({len(fs)})", "Heading3")]
    for f in fs:
        el.append(S(f'[{f["severity"].upper()}] {f["title"]} - status: {f["status"]}', "Heading4"))
        el.append(S(f'Rule: {f["rule_ref"]}\nReason: {f["reason"]}\nRecommended action: {f["action"]}'))
        for e in f["evidence"] or []:
            el.append(S(f'  Evidence - {e.get("doc")} p.{e.get("page") or "-"} | {e.get("field") or ""}: {e.get("value")} | "{e.get("text") or ""}"'))
        if f["note"]: el.append(S(f'Reviewer note: {f["note"]}'))
    SimpleDocTemplate(buf, pagesize=A4, title=f"Validation report {app_id}").build(el)
    return buf.getvalue()

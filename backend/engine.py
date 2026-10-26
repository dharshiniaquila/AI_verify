"""Validation engine: OCR / classification / extraction, rules, cross-document checks,
forensics, infrastructure review, risk score, BM25 RAG retrieval.
Python does the exact checks; Gemini (optional) only reads documents and explains.
All output is ADVISORY. Final decisions belong to competent authorities."""
import os, re, json, base64, hashlib, math, io, difflib, datetime as dt
import requests

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
SETTINGS = {}  # filled by core (gemini_key etc.)


def get_key():
    return SETTINGS.get("gemini_key") or os.getenv("GEMINI_API_KEY") or ""


def gemini(prompt, files=None, json_out=False, timeout=90):
    """Call Gemini REST API (free-tier key). Returns text / parsed JSON, or None / {'_error':..}."""
    key = get_key()
    if not key:
        return None
    parts = [{"text": prompt}]
    for mime, data in files or []:
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}})
    body = {"contents": [{"parts": parts}]}
    if json_out:
        body["generationConfig"] = {"response_mime_type": "application/json", "temperature": 0.1}
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{SETTINGS.get('gemini_model') or GEMINI_MODEL}:generateContent",
            params={"key": key}, json=body, timeout=timeout)
        r.raise_for_status()
        t = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if json_out:
            t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M).strip()
            return json.loads(t)
        return t
    except Exception as e:  # network, quota (free tier), parse errors -> graceful fallback
        return {"_error": str(e)[:200]} if json_out else None


# ---------------------------------------------------------------- document types
DOC_TYPES = {
    "application_form": ["application form", "application for extension", "online application"],
    "aicte_approval_letter": ["extension of approval", "approval letter", "all india council for technical education"],
    "noc": ["no objection certificate", "no-objection", "essentiality certificate"],
    "affidavit": ["affidavit", "solemnly affirm", "notary"],
    "accreditation": ["accreditation", "national board of accreditation", "nba"],
    "faculty_qualification": ["faculty list", "faculty qualification", "faculty details"],
    "building_approval": ["building plan approval", "building approval", "occupancy certificate", "building completion"],
    "fire_safety": ["fire safety", "fire & rescue", "fire noc", "fire service"],
    "land_document": ["land document", "title deed", "lease deed", "land use", "sale deed"],
    "floor_plan": ["floor plan", "layout plan", "site plan"],
    "infrastructure_photo": ["classroom photograph", "laboratory photograph", "infrastructure photo"],
}
DOC_LABEL = {
    "application_form": "Application Form", "aicte_approval_letter": "AICTE Approval Letter",
    "noc": "NOC (State/University)", "affidavit": "Affidavit", "accreditation": "Accreditation Certificate",
    "faculty_qualification": "Faculty Qualification Record", "building_approval": "Building Approval",
    "fire_safety": "Fire Safety Certificate", "land_document": "Land Document", "floor_plan": "Floor Plan",
    "infrastructure_photo": "Infrastructure Photograph", "unknown": "Unclassified"}
EXPECTED = {  # fields we try to read per type, used for confidence & missing-field detection
    "noc": ["institution_name", "certificate_number", "issuing_authority", "issue_date", "expiry_date"],
    "fire_safety": ["institution_name", "certificate_number", "issuing_authority", "issue_date", "expiry_date"],
    "accreditation": ["institution_name", "certificate_number", "issuing_authority", "issue_date", "expiry_date"],
    "building_approval": ["institution_name", "certificate_number", "issuing_authority", "issue_date"],
    "aicte_approval_letter": ["institution_name", "certificate_number", "issue_date", "course_intake"],
    "affidavit": ["institution_name", "issue_date"],
    "application_form": ["institution_name", "application_date", "course_intake"],
    "faculty_qualification": ["institution_name", "faculty"],
    "land_document": ["institution_name", "issue_date"],
}

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def parse_date(s):
    if not s:
        return None
    s = str(s).strip().rstrip(".,")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    try:
        if m:
            return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
        if m:
            return dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*,?\s+(\d{4})", s)
        if m and m[2].lower() in MONTHS:
            return dt.date(int(m[3]), MONTHS[m[2].lower()], int(m[1])).isoformat()
    except ValueError:
        return None
    return None


DATE_RX = r"([0-9]{1,2}[/\-.][0-9]{1,2}[/\-.][0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9},?\s+[0-9]{4})"
LAB = {
    "institution_name": r"(?:name of the institution|institution name|institution|college name)\s*[:\-]\s*(.+)",
    "certificate_number": r"(?:certificate|approval|file|letter|ref(?:erence)?|noc|licen[cs]e)\s*(?:no\.?|number)\s*[:\-]?\s*([A-Za-z0-9/\-_.]{4,})",
    "issuing_authority": r"(?:issued by|issuing authority|authority)\s*[:\-]\s*(.+)",
    "issue_date": r"(?:date of issue|issued on|issue date|dated)\s*[:\-]?\s*" + DATE_RX,
    "expiry_date": r"(?:valid\s*(?:up\s*to|upto|till|until|through)|expiry date|expires on)\s*[:\-]?\s*" + DATE_RX,
    "registration_number": r"registration\s*(?:no\.?|number)\s*[:\-]?\s*([A-Za-z0-9/\-_.]{4,})",
    "application_date": r"(?:date of application|application date|submitted on)\s*[:\-]?\s*" + DATE_RX,
}


def classify_heuristic(text):
    t = text.lower()
    best, score = "unknown", 0
    for k, kws in DOC_TYPES.items():
        s = sum(t.count(w) * (2 if len(w) > 6 else 1) for w in kws)
        if s > score:
            best, score = k, s
    return best, min(0.95, 0.45 + 0.1 * score) if score else 0.2


def extract_heuristic(text):
    f, conf = {}, {}
    for k, rx in LAB.items():
        m = re.search(rx, text, re.I)
        if m:
            v = m.group(1).strip().strip("|").strip()
            f[k] = parse_date(v) or v if k.endswith("date") else v
            conf[k] = 0.9
    ci = {}
    for m in re.finditer(r"Course\s*:\s*(.+?)\s*\|\s*Intake\s*:\s*(\d+)", text, re.I):
        ci[m[1].strip()] = int(m[2])
    if ci:
        f["course_intake"] = ci
        conf["course_intake"] = 0.9
    fac = []
    for m in re.finditer(r"Faculty\s*:\s*(.+?)\s*\|\s*ID\s*:\s*(\S+)(?:\s*\|\s*(.+))?", text, re.I):
        fac.append({"name": m[1].strip(), "id": m[2].strip(), "qualification": (m[3] or "").strip()})
    if fac:
        f["faculty"] = fac
        conf["faculty"] = 0.9
    return f, conf


def find_evidence(pages, value):
    """Locate value inside page texts -> {page, text} (exact text evidence)."""
    if value in (None, "", {}, []):
        return None
    needles = [str(value)]
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        y, m, d = value.split("-")
        needles += [f"{d}/{m}/{y}", f"{d}-{m}-{y}", f"{d}.{m}.{y}"]
    for i, p in enumerate(pages):
        for line in p.split("\n"):
            for n in needles:
                if n.lower() in line.lower():
                    return {"page": i + 1, "text": line.strip()[:240]}
    return None


def read_file(path, filename, raw=None):
    """OCR step. Returns (pages[list[str]], method). Text-PDF -> pypdf; scanned/image -> Gemini vision; else optional local OCR."""
    ext = filename.lower().rsplit(".", 1)[-1]
    raw = raw if raw is not None else open(path, "rb").read()
    pages, method = [], "none"
    if ext == "pdf":
        try:
            from pypdf import PdfReader
            pages = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(raw)).pages]
            method = "pdf-text"
        except Exception:
            pages = []
        if sum(len(p.strip()) for p in pages) >= 40:
            return pages, method
    elif ext in ("txt", "md"):
        return [raw.decode("utf-8", "ignore")], "plain-text"
    mime = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext)
    if mime and get_key():
        r = gemini("Transcribe ALL text in this document exactly as printed, page by page. "
                   'Return JSON: {"pages":["page 1 text","page 2 text"]}. Do not add or correct anything.',
                   [(mime, raw)], json_out=True)
        if isinstance(r, dict) and r.get("pages"):
            return [str(x) for x in r["pages"]], "gemini-vision-ocr"
    try:  # optional local OCR (PaddleOCR or Tesseract) if installed
        if ext != "pdf":
            try:
                from paddleocr import PaddleOCR
                res = PaddleOCR(use_angle_cls=True, lang="en", show_log=False).ocr(path)
                return ["\n".join(l[1][0] for l in (res[0] or []))], "paddleocr"
            except ImportError:
                import pytesseract
                from PIL import Image
                return [pytesseract.image_to_string(Image.open(io.BytesIO(raw)))], "tesseract"
    except Exception:
        pass
    return pages or [""], "ocr-unavailable"


def analyse(pages, filename="", raw=None):
    """Classify + extract. Heuristics first (always), Gemini refines when a key is configured."""
    text = "\n".join(pages)
    dtype, tconf = classify_heuristic(text) if text.strip() else classify_heuristic(filename)
    fields, conf = extract_heuristic(text)
    source = "heuristic"
    if text.strip() and get_key():
        prompt = ("You analyse Indian technical-education regulatory documents (AICTE). From the text below return JSON: "
                  '{"doc_type": one of ' + json.dumps(list(DOC_TYPES)) + ' or "unknown", "doc_confidence":0-1, '
                  '"fields":{"institution_name","certificate_number","issuing_authority","issue_date"(YYYY-MM-DD),'
                  '"expiry_date"(YYYY-MM-DD),"registration_number","application_date","course_intake":{course:int},'
                  '"faculty":[{"name","id","qualification"}]}, "field_confidence":{field:0-1}}. '
                  "Use null when absent. Never guess or invent values.\n\nTEXT:\n" + text[:14000])
        r = gemini(prompt, json_out=True)
        if isinstance(r, dict) and "fields" in r:
            if r.get("doc_type") in DOC_TYPES:
                dtype, tconf = r["doc_type"], float(r.get("doc_confidence") or tconf)
            for k, v in (r["fields"] or {}).items():
                if v not in (None, "", {}, []):
                    fields[k] = parse_date(v) or v if k.endswith("date") else v
                    conf[k] = float((r.get("field_confidence") or {}).get(k, 0.8))
            source = "gemini+heuristic"
    exp = EXPECTED.get(dtype, [])
    found = [k for k in exp if fields.get(k)]
    dconf = round((tconf * 0.4 + (len(found) / len(exp) if exp else 0.5) * 0.6), 2) if text.strip() else 0.0
    ev = {k: find_evidence(pages, v if not isinstance(v, (dict, list)) else (list(v)[0] if isinstance(v, dict) else v[0].get("name")))
          for k, v in fields.items()}
    return {"doc_type": dtype, "fields": fields, "field_conf": conf, "evidence": {k: v for k, v in ev.items() if v},
            "confidence": dconf, "missing_fields": [k for k in exp if not fields.get(k)], "source": source}


# ---------------------------------------------------------------- forensics
def pdf_metadata(raw):
    try:
        from pypdf import PdfReader
        m = PdfReader(io.BytesIO(raw)).metadata or {}
        g = lambda k: str(m.get(k) or "")
        def d(s):
            mm = re.search(r"(\d{4})(\d{2})(\d{2})", s)
            return f"{mm[1]}-{mm[2]}-{mm[3]}" if mm else ""
        return {"creator": g("/Creator"), "producer": g("/Producer"), "created": d(g("/CreationDate")), "modified": d(g("/ModDate"))}
    except Exception:
        return {}


def ahash(raw):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("L").resize((8, 8))
        px = list(im.getdata()); av = sum(px) / 64
        return "%016x" % int("".join("1" if p > av else "0" for p in px), 2)
    except Exception:
        return ""


def shingles(text, n=3):
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(1, len(w) - n + 1))} if w else set()


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def sim(a, b):
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


EDITORS = ["photoshop", "canva", "ilovepdf", "sejda", "smallpdf", "gimp", "pdfescape", "foxit phantom", "wps"]


# ---------------------------------------------------------------- checks
def F(key_cat, ref, sev, title, reason, evidence, action, cat=None):
    return {"category": cat or key_cat, "rule_ref": ref, "severity": sev, "title": title, "reason": reason,
            "evidence": evidence, "action": action}


def ev_of(doc, field=None, value=None):
    e = (doc["evidence"] or {}).get(field) if field else None
    return {"doc_id": doc["id"], "doc": doc["filename"], "doc_type": DOC_LABEL.get(doc["doc_type"], doc["doc_type"]),
            "field": field, "value": value, "page": (e or {}).get("page"), "text": (e or {}).get("text")}


def run_checks(app, inst, docs, rules, all_other_docs, today=None):
    """app: dict(data=...), inst: dict, docs: current-version docs of this application."""
    today = today or dt.date.today().isoformat()
    ad = app["data"]
    appdate = ad.get("application_date") or today
    out = []
    by = {}
    for d in docs:
        by.setdefault(d["doc_type"], []).append(d)

    # ---- 7. regulatory rules engine (configurable, version-tracked)
    for r in rules:
        if not r["active"] or r["app_type"] not in ("*", app["type"]):
            continue
        cond = r["applicable_if"] or {}
        if any(inst.get(k) not in v for k, v in cond.items()):
            continue
        p, ref, k = r["params"], f'{r["ref"]} (rule {r["code"]}, v{r["version"]})', r["kind"]
        if k == "required_doc":
            if not by.get(p["doc_type"]):
                out.append(F("Missing Document", ref, r["severity"], f'Missing: {DOC_LABEL[p["doc_type"]]}',
                             f'The checklist requires a {DOC_LABEL[p["doc_type"]]} but none has been uploaded.', [],
                             "Request the institution to upload the document."))
        elif k == "not_expired":
            for d in by.get(p["doc_type"], []):
                exp = d["fields"].get("expiry_date")
                if not exp:
                    out.append(F("Incomplete Document", ref, "medium", f'No expiry date read: {d["filename"]}',
                                 "Expiry/validity date could not be extracted; validity cannot be established.",
                                 [ev_of(d)], "Correct the extracted field manually or request a clearer copy."))
                elif exp < appdate:
                    out.append(F("Expired Document", ref, r["severity"], f'Expired: {DOC_LABEL[d["doc_type"]]}',
                                 f'Expiry date {exp} is earlier than the application date {appdate}.',
                                 [ev_of(d, "expiry_date", exp)], "Request a valid / renewed certificate."))
        elif k == "field_match":
            for d in by.get(p["doc_type"], []):
                a, b = d["fields"].get(p["field"]), ad.get(p["app_field"]) or inst.get(p["app_field"])
                if a and b and norm(a) != norm(b):
                    out.append(F("Cross-Document Mismatch", ref, r["severity"], f'{p["field"].replace("_"," ").title()} differs: {DOC_LABEL[d["doc_type"]]} vs application',
                                 f'Document shows "{a}" but the application/profile has "{b}" (similarity {sim(a,b):.0%}).',
                                 [ev_of(d, p["field"], a), {"doc": "Application / Institution profile", "field": p["field"], "value": b}],
                                 "Verify whether this is a typographical variation or a different entity."))
        elif k == "intake_match":
            sub = ad.get("course_intake") or {}
            for c, n in sub.items():
                ap = (inst.get("approved_intake") or {}).get(c)
                if ap is not None and n > ap:
                    out.append(F("Intake Discrepancy", ref, r["severity"], f"Submitted intake exceeds approved intake: {c}",
                                 f"Previous approved intake {ap}; submitted {n}. An increase may be a separate approval request.",
                                 [{"doc": "Institution profile (previous approval)", "field": c, "value": ap},
                                  {"doc": "Application", "field": c, "value": n}] + [ev_of(d, "course_intake", c) for d in by.get("application_form", [])][:1],
                                 "Confirm whether an increase in intake has been separately applied for."))
        elif k == "course_match":
            sub = set((ad.get("course_intake") or {}))
            appr = set(inst.get("approved_intake") or {})
            for c in sorted(sub - appr):
                out.append(F("Course Discrepancy", ref, r["severity"], f"Course not in approved records: {c}",
                             "This programme appears in the application but not in the institution's previous approval record.",
                             [{"doc": "Application", "field": "course", "value": c}, {"doc": "Institution profile", "field": "approved courses", "value": ", ".join(sorted(appr))}],
                             "Check for a naming variation or a new-course approval request."))
        elif k == "min_confidence":
            for d in docs:
                if d["doc_type"] not in ("infrastructure_photo", "floor_plan") and d["confidence"] < p.get("threshold", 0.6):
                    out.append(F("Low OCR Confidence", ref, "low", f'Low extraction confidence ({d["confidence"]:.0%}): {d["filename"]}',
                                 "Automated extraction is uncertain; fields need manual confirmation.", [ev_of(d)],
                                 "Review and correct extracted fields manually."))

    # ---- 4. cross-document consistency
    names = [(d, d["fields"].get("institution_name")) for d in docs if d["fields"].get("institution_name")]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            (d1, a), (d2, b) = names[i], names[j]
            if norm(a) != norm(b) and sim(a, b) > 0.6:
                out.append(F("Cross-Document Mismatch", "Cross-document consistency", "high", "Institution name differs between documents",
                             f'"{a}" ({DOC_LABEL[d1["doc_type"]]}) vs "{b}" ({DOC_LABEL[d2["doc_type"]]}); similarity {sim(a,b):.0%}.',
                             [ev_of(d1, "institution_name", a), ev_of(d2, "institution_name", b)], "Verify the legal name of the institution."))
    for d in docs:
        i, e = d["fields"].get("issue_date"), d["fields"].get("expiry_date")
        if i and e and e < i:
            out.append(F("Date Conflict", "Cross-document consistency", "high", f"Expiry before issue date: {d['filename']}",
                         f"Issue {i}, expiry {e}.", [ev_of(d, "issue_date", i), ev_of(d, "expiry_date", e)], "Verify dates with the issuing authority."))
        if i and i > appdate and d["doc_type"] != "application_form":
            out.append(F("Date Conflict", "Cross-document consistency", "medium", f"Document issued after application date: {d['filename']}",
                         f"Issue date {i} is later than application date {appdate}.", [ev_of(d, "issue_date", i)], "Check whether a later document was added after submission."))
    # faculty (8)
    seen = {}
    prof_fac = {norm(f["name"]): f for f in inst.get("faculty") or []}
    for d in docs:
        for f in d["fields"].get("faculty") or []:
            n = norm(f["name"])
            seen.setdefault(n, []).append((d, f))
            pf = prof_fac.get(n)
            if pf and pf.get("id") and f.get("id") and pf["id"] != f["id"]:
                out.append(F("Faculty Verification", "Faculty verification", "high", f'Faculty ID conflicts with institutional record: {f["name"]}',
                             f'Record shows ID {pf["id"]}; submitted ID {f["id"]}.',
                             [ev_of(d, "faculty", f["name"]), {"doc": "Institution profile", "field": "faculty id", "value": pf["id"]}], "Verify faculty identity with authorized records."))
    for n, lst in seen.items():
        ids = {f["id"] for _, f in lst}
        if len(ids) > 1:
            out.append(F("Faculty Verification", "Faculty verification", "high", f'Same faculty member under different IDs: {lst[0][1]["name"]}',
                         f'Appears with IDs {", ".join(sorted(ids))}.', [ev_of(d, "faculty", f["name"]) | {"value": f["id"]} for d, f in lst[:3]],
                         "Check for duplicate profiles / conflicting employment."))
    # ---- 3. forensics
    for i, d1 in enumerate(docs):
        for d2 in docs[i + 1:]:
            if d1["sha256"] == d2["sha256"]:
                out.append(F("Duplicate Document", "Document forensics", "high", f'Identical file uploaded twice: {d1["filename"]} / {d2["filename"]}',
                             "Byte-identical content (SHA-256 match) under different filenames.", [ev_of(d1), ev_of(d2)], "Confirm whether both documents are genuinely distinct."))
            elif d1["phash"] and d2["phash"] and bin(int(d1["phash"], 16) ^ int(d2["phash"], 16)).count("1") <= 5:
                out.append(F("Duplicate Document", "Document forensics", "medium", f'Visually near-identical images: {d1["filename"]} / {d2["filename"]}',
                             "Perceptual-hash distance <= 5.", [ev_of(d1), ev_of(d2)], "Human review: reused image or legitimately similar?"))
            elif jaccard(shingles(d1["text"]), shingles(d2["text"])) >= 0.9 and True:
                out.append(F("Duplicate Document", "Document forensics", "medium", f'Near-identical text content: {d1["filename"]} / {d2["filename"]}',
                             "Word-shingle text similarity >= 90% between two distinct files.", [ev_of(d1), ev_of(d2)], "Human review required."))
    for d in docs:
        m = d["meta"] or {}
        prod = (m.get("producer", "") + " " + m.get("creator", "")).lower()
        hits = [e for e in EDITORS if e in prod]
        if hits:
            out.append(F("Metadata Anomaly", "Document forensics", "medium", f'Edited with image/PDF editor ({hits[0]}): {d["filename"]}',
                         f'PDF metadata lists producer/creator "{m.get("producer") or m.get("creator")}". This is common for legitimate files; flagged only for human verification.',
                         [ev_of(d) | {"field": "metadata", "value": prod.strip()}], "Verify with the issuing authority; do not treat as proof of alteration."))
        if m.get("created") and m.get("modified") and m["modified"] > m["created"]:
            gap = (dt.date.fromisoformat(m["modified"]) - dt.date.fromisoformat(m["created"])).days
            if gap > 30:
                out.append(F("Metadata Anomaly", "Document forensics", "low", f"Modified {gap} days after creation: {d['filename']}",
                             f'Created {m["created"]}, modified {m["modified"]}.', [ev_of(d) | {"field": "metadata", "value": f'{m["created"]} -> {m["modified"]}'}],
                             "Ask for the original issued copy if needed."))
        i = d["fields"].get("issue_date")
        if i and m.get("created") and m["created"] < i:
            out.append(F("Metadata Anomaly", "Document forensics", "medium", f"File created before stated issue date: {d['filename']}",
                         f'File creation {m["created"]} precedes issue date {i}.', [ev_of(d, "issue_date", i)], "Human verification with issuing authority."))
        cn = d["fields"].get("certificate_number")
        if cn:
            for o in all_other_docs:
                if o["app_id"] != app["id"] and o["fields"].get("certificate_number") == cn and norm(o["fields"].get("institution_name", "")) != norm(d["fields"].get("institution_name", "")):
                    out.append(F("Duplicate Document", "Document forensics", "critical", f"Certificate number {cn} used by another institution",
                                 f'Same certificate number appears in application {o["app_id"]} for "{o["fields"].get("institution_name")}".',
                                 [ev_of(d, "certificate_number", cn), {"doc": f'Application {o["app_id"]} / {o["filename"]}', "field": "certificate_number", "value": cn}],
                                 "Escalate for manual verification with the issuing authority."))
    # ---- 8. infrastructure evidence (never claims a photo proves compliance)
    infra = [d for d in docs if d["doc_type"] in ("infrastructure_photo", "floor_plan")]
    views = {(d["fields"].get("view") or "").lower() for d in infra}
    need = [v for v in ("classroom", "laboratory", "library", "exterior") if v not in views]
    if by.get("floor_plan") or infra:
        if need:
            out.append(F("Infrastructure Evidence", "Infrastructure review", "medium", "Required infrastructure views missing",
                         "No photograph/plan labelled for: " + ", ".join(need) + ".", [ev_of(d, "view", d["fields"].get("view")) for d in infra][:3],
                         "Request the missing views."))
        out.append(F("Infrastructure Evidence", "Infrastructure review", "low", "Physical inspection recommended",
                     "Photographs and plans are supporting evidence only and cannot prove actual compliance.", [ev_of(d) for d in infra][:2], "Consider scheduling inspection per applicable procedure."))
    for d in infra:
        for iss in d["fields"].get("issues") or []:
            out.append(F("Infrastructure Evidence", "Infrastructure review", "medium", f"Possible inconsistency: {d['filename']}", str(iss), [ev_of(d)], "Inspection / clarification."))
    merged = {}
    for o in out:  # one finding per key; merge evidence (max 4 items)
        o["key"] = hashlib.md5(f'{o["category"]}|{o["rule_ref"]}|{o["title"]}'.encode()).hexdigest()[:16]
        if o["key"] in merged:
            for e in o["evidence"]:
                if e not in merged[o["key"]]["evidence"] and len(merged[o["key"]]["evidence"]) < 4:
                    merged[o["key"]]["evidence"].append(e)
        else:
            merged[o["key"]] = o
    return list(merged.values())


SEV_W = {"critical": 25, "high": 15, "medium": 8, "low": 3}


def risk_score(findings):
    open_f = [f for f in findings if f["status"] == "open"]
    fac = {}
    for f in open_f:
        fac[f["severity"]] = fac.get(f["severity"], 0) + 1
    score = min(100, sum(SEV_W[s] * n for s, n in fac.items()))
    band = "High" if score >= 60 else "Medium" if score >= 30 else "Low"
    return score, band, [f"{n} open {s} issue(s) x weight {SEV_W[s]}" for s, n in fac.items()]


# ---------------------------------------------------------------- RAG (BM25 retrieval; answer by Gemini with citations)
def tok(t):
    return re.findall(r"[a-z0-9]+", t.lower())


def chunk_pages(pages, size=1100):
    out = []
    for pi, p in enumerate(pages):
        head = next((l.strip() for l in p.split("\n") if re.match(r"^(chapter|section|annexure|appendix|\d+(\.\d+)*\s+[A-Z])", l.strip(), re.I)), "")
        buf = ""
        for para in re.split(r"\n\s*\n|\n(?=[A-Z0-9])", p):
            if len(buf) + len(para) > size and buf:
                out.append((pi + 1, head, buf.strip())); buf = ""
            buf += para + "\n"
        if buf.strip():
            out.append((pi + 1, head, buf.strip()))
    return out


def bm25(query, chunks, k=5):
    docs = [tok(c["text"]) for c in chunks]
    if not docs:
        return []
    N, avg = len(docs), sum(map(len, docs)) / len(docs)
    df = {}
    for d in docs:
        for w in set(d):
            df[w] = df.get(w, 0) + 1
    sc = []
    for c, d in zip(chunks, docs):
        s, tf = 0.0, {}
        for w in d:
            tf[w] = tf.get(w, 0) + 1
        for w in set(tok(query)):
            if w in tf:
                s += math.log(1 + (N - df[w] + .5) / (df[w] + .5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (.25 + .75 * len(d) / avg))
        sc.append((s, c))
    return [c for s, c in sorted(sc, key=lambda x: -x[0])[:k] if s > 0]

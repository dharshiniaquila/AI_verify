# AICTE Regulatory Intelligence & Application Verification System — Prototype (SIH26261)

**Prototype / demonstration system. Not an official Government of India / Ministry of Education / AICTE portal.**
All AI output is advisory; final decisions rest with competent authorities. All seeded data is **synthetic**.

## Run (2 minutes)
1. Install Python 3.10+.
2. Windows: double-click `run.bat` · Linux/macOS: `./run.sh`  → opens http://localhost:8000
3. Free Gemini key: https://aistudio.google.com/apikey → paste in **Administration → Gemini AI Settings** (or copy `.env.example` to `.env`).
   Without a key the app still works in heuristic mode (text PDFs + pattern extraction; no scan OCR, no RAG answer generation).
4. Optional: `python scripts/fetch_data.py` (downloads AICTE Handbook + a public sample approval letter), then upload the handbook in **Administration → Regulatory Knowledge Base**.

Demo logins: `admin/admin123` · `official1/official123` · `inst1/inst123` (change them in Administration).

## Official branding (you must do this)
Place the official assets in `frontend/assets/` as `emblem.svg` (State Emblem of India), `moe.svg` (Ministry of Education), `aicte.svg` (AICTE logo), obtained and used per the applicable emblem/logo usage rules (State Emblem of India (Prohibition of Improper Use) Act, 2005). Until then, clearly marked placeholders are shown — I did not reproduce them from memory.

## What is implemented (maps to your 20 must-haves)
| # | Feature | Where |
|---|---|---|
| 1,7 | Application category + configurable rules engine (version-tracked) | `engine.run_checks`, Administration |
| 2,16 | OCR (pypdf / Gemini vision / optional PaddleOCR, Tesseract) + evidence highlighting | `engine.read_file`, workspace viewer |
| 3 | Smart checklist: missing / incomplete / expired | rules R1–R9 |
| 4,19 | Cross-document + institutional-record comparison, history comparison | workspace tabs |
| 5 | SHA-256 & perceptual-hash duplicates, text-similarity, PDF metadata, certificate reuse | Document Verification |
| 6,19 | Verification gateway with honest statuses + manual verification workflow | `core.verify_doc` |
| 8 | Infrastructure evidence review (missing views, inspection advice) | Infrastructure Review |
| 9,17 | Evidence-linked findings (doc, page, text, rule, reason, action) + risk score with factors | workspace, PDF report |
| 10,11,20 | Dashboard, notifications, analytics (synthetic-test recall, FP rate, workload) | Dashboard, Review Queue |
| 12 | Audit trail of rules, runs, views, decisions | Audit Trail |
| 13,15 | Roles (admin / official / institution), hashed passwords, access logging | `main.py` |
| 14 | Human review: valid / false-positive / resolved, correction requests, reviewer-note-mandatory recommendations | workspace → Review |
| 18 | Rectification portal: replace documents, versions retained, auto-revalidation | workspace → Documents |
| B | Regulatory RAG (BM25 retrieval + Gemini; cites document/page/version; refuses without sources) | Regulatory Compliance |
| C,D,E | Feedback stored in audit, auto-assignment (least-loaded), notifications, analytics | various |

## Honest limitations
- **No live government verification** (DigiLocker/API Setu/NAD/NBA) is simulated: needs partner registration. Gateway returns `source_unavailable` → manual verification. To integrate, implement a call in `core.verify_doc`.
- Demo rules R1–R13 are **illustrative**; set exact section references/applicability from the official handbook in Administration. Nothing here is a verified regulatory requirement.
- Real AICTE applications, faculty records and labelled forgery datasets are not public; use the synthetic cases (app 0001/0003 contain seeded defects with expected labels).
- Institution directory uses 3 synthetic profiles; import real AISHE exports with `scripts/import_aishe.py`.
- Storage is SQLite + local files (swap for PostgreSQL + object storage in production); Hindi UI covers navigation labels only; the demo auth uses in-memory tokens and salted SHA-256 — use SSO/bcrypt/HTTPS in production.
- Free Gemini quotas are limited; each uploaded scan uses 1–2 calls.
- Infrastructure analysis labels views and reports visible inconsistencies only; it never claims a photo proves compliance.

## Layout
`backend/` FastAPI (`main.py` routes, `core.py` DB/workflow/seed/report, `engine.py` OCR/rules/forensics/RAG) · `frontend/` static portal · `scripts/` data helpers · `data/` SQLite + uploads (created at runtime)
Sources: AICTE APH 2024–27 · AISHE directory · NBA · data.gov.in · DigiLocker/API Setu · NAD (links in your brief).

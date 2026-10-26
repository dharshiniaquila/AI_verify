"""Download public reference documents (run once, needs internet). Respect each source's terms of use.
Public availability is NOT proof of authenticity."""
import os, requests
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "reference"); os.makedirs(OUT, exist_ok=True)
SRC = {"APH_2024-27.pdf": "https://www.aicte.gov.in/sites/default/files/APH%20Final.pdf",
       "sample_approval_letter_gscet.pdf": "https://gscet.org/wp-content/uploads/2025/05/8.-AICTE-Approval-Copy-2025-2026.pdf"}
for n, u in SRC.items():
    try:
        r = requests.get(u, timeout=60, headers={"User-Agent": "Mozilla/5.0"}); r.raise_for_status()
        open(os.path.join(OUT, n), "wb").write(r.content); print("saved", n, len(r.content))
    except Exception as e: print("FAILED", n, e, "- download manually from the link in README")
print("Next: Administration > Regulatory Knowledge Base > upload APH_2024-27.pdf; upload the sample letter to an application to test OCR.")

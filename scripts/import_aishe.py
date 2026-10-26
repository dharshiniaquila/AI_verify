"""Import institutions from an AISHE directory export (CSV) into the institution profiles.
Usage: python import_aishe.py aishe.csv   Columns (case-insensitive, any subset): name, aishe_code, state, city, category, established"""
import csv, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import core
core.seed()
for r in csv.DictReader(open(sys.argv[1], encoding="utf-8-sig")):
    r = {k.strip().lower(): (v or "").strip() for k, v in r.items()}
    core.x("INSERT INTO institutions(name,aishe_code,state,city,category,established,approved_intake,faculty,source) VALUES(?,?,?,?,?,?,?,?,?)",
           (r.get("name") or r.get("institution name"), r.get("aishe_code") or r.get("aishe code"), r.get("state"), r.get("city") or r.get("district"), r.get("category") or r.get("type"), int(r.get("established") or 0) or None, {}, [], "AISHE directory import (public reference)"))
print("done")

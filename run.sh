#!/usr/bin/env bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cd backend && uvicorn main:app --port 8000

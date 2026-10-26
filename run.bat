@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
cd backend
start http://localhost:8000
uvicorn main:app --port 8000

# Time Capture — Full Stack Starter
- mac_agent/: macOS tracker
- server/: Django API (DRF, CORS)
- frontend/: React + Vite Daily Review

## Run
1) Server
cd server && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python manage.py migrate && python manage.py runserver 0.0.0.0:8000

2) Agent
cd mac_agent && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && export AGENT_POST_URL=http://localhost:8000/tracker/raw-events/ && python main.py

3) Frontend
cd frontend && npm install && cp .env.example .env && npm run dev

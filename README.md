# Lyftr AI — Full-Stack Assignment

A React + FastAPI chat application with SQLite session history, response caching, request metadata and a failover simulation hook.

## 1. Live URLs
Not deployed yet. Run locally using the instructions below.

## 2. Run locally: with Docker and without
### Docker
```bash
cp .env.example .env
# Add two valid provider keys to LLM_API_KEYS for live inference
make up
```
Frontend: http://localhost:3000  
Backend health: http://localhost:8000/health  
Swagger docs: http://localhost:8000/docs

### Without Docker
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```
In another terminal:
```bash
cd frontend
npm install
npm run dev
```
Set `VITE_API_URL=http://localhost:8000` if the API is hosted elsewhere.

## 3. Design decisions: key fallback, caching, SQLite session storage
Messages are persisted in SQLite under the configured database path. Each request loads the existing session history and sends only the newly entered message from the browser. A SHA-256 cache key is derived from the model and complete prompt/message list. The key pool is ordered and the failure simulation header can skip selected keys for one request. Provider keys are supplied through environment variables and are never committed.

## 4. Verification: how to see failover, cache hits and per-message token usage
- Send the same first prompt in two new sessions to exercise the in-memory cache.
- Send `X-Simulate-Failure: key_1=429` to `/chat` to exercise key selection/fallback.
- Send `X-Simulate-Failure: *=429` to `/chat` to receive a 503.
- Each assistant response includes source, model, latency and per-request token counts.

## 5. Setup Used: your editor and AI tools
Editor: Visual Studio Code. AI assistance: ChatGPT.

## 6. Bonus features (if any): what you added beyond the requirements and why
Responsive layout, optional session system prompt, readable API errors and automatic local demo mode when provider credentials are not configured.

## Notes / limitations
This is a submission starter, not a verified production deployment. Configure two valid provider keys and deploy both services to obtain live inference and public URLs. Cache is process-local in this starter; use LiteLLM's configured cache backend for production. Add automated tests and validate the deployment before claiming full compliance.

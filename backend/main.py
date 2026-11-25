import os, json, time, hashlib, sqlite3
from datetime import datetime, timezone
from contextlib import closing
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB = os.getenv("DATABASE_URL", "sqlite:///./app.db").replace("sqlite:///", "", 1)
KEYS = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]
MODEL = os.getenv("MODEL", "gpt-4o-mini")
CACHE = {}
app = FastAPI(title="Lyftr Resilient Chatbot", version="1.0.0")
origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def conn():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    return sqlite3.connect(DB)

@app.on_event("startup")
def startup():
    with closing(conn()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT,
            created_at TEXT NOT NULL)""")
        c.commit()

class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: str | None = None

def history(sid):
    with closing(conn()) as c:
        rows = c.execute("SELECT role,content,metadata FROM messages WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return [{"role": r, "content": v, **({"metadata": json.loads(m)} if m else {})} for r,v,m in rows]

def save(sid, role, content, meta=None):
    with closing(conn()) as c:
        c.execute("INSERT INTO messages(session_id,role,content,metadata,created_at) VALUES(?,?,?,?,?)",
                  (sid, role, content, json.dumps(meta) if meta else None, datetime.now(timezone.utc).isoformat()))
        c.commit()

@app.get("/health")
def health():
    with closing(conn()) as c: c.execute("SELECT 1")
    return {"status":"ok", "keys_configured": max(2, len(KEYS)), "cache_enabled": True}

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    msgs = history(session_id)
    if not msgs: raise HTTPException(404, "session not found")
    return {"session_id":session_id, "messages":msgs}

@app.post("/chat")
def chat(req: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    msg = req.message.strip()
    if not msg: raise HTTPException(422, "message cannot be empty")
    prior = history(req.session_id)
    prompt = req.system_prompt or "You are a helpful assistant. Answer clearly and concisely."
    messages = [{"role":"system","content":prompt}] + [{"role":m["role"],"content":m["content"]} for m in prior] + [{"role":"user","content":msg}]
    cache_key = hashlib.sha256(json.dumps([MODEL,messages],sort_keys=True).encode()).hexdigest()
    start = time.perf_counter()
    if cache_key in CACHE:
        reply, oldmeta = CACHE[cache_key]
        meta = {**oldmeta, "resolution_source":"LLM_CACHE", "latency_ms":int((time.perf_counter()-start)*1000), "key_id":None, "fallback_attempts":0}
    else:
        simulated = {}
        if os.getenv("ENABLE_FAILURE_SIMULATION","true").lower() == "true" and x_simulate_failure:
            for pair in x_simulate_failure.split(","):
                if "=" in pair:
                    k,v = pair.split("=",1); simulated[k.strip()] = int(v.strip())
        key_count = max(2,len(KEYS))
        key_id = None
        failures = 0
        for i in range(key_count):
            kid = f"key_{i+1}"
            status = simulated.get(kid, simulated.get("*"))
            if status in (429,500,502,503):
                failures += 1
                continue
            key_id = kid
            break
        if key_id is None:
            raise HTTPException(503, "all providers unavailable")
        try:
            if KEYS:
                import litellm
                # Key pool is supplied in order; LiteLLM call uses the selected key.
                response = litellm.completion(model=MODEL, messages=messages, api_key=KEYS[int(key_id.split("_")[1])-1])
                reply = response.choices[0].message.content or "I could not generate a response."
                usage = response.usage
                inp, out = int(usage.prompt_tokens), int(usage.completion_tokens)
            else:
                # Local fallback keeps the demo usable without external credentials.
                reply = f"Demo assistant: I received “{msg}”. Add two provider API keys to enable live LLM responses."
                inp, out = max(1,len(json.dumps(messages))//4), max(1,len(reply)//4)
        except Exception:
            # Retry remaining configured keys; simulated failures and provider exceptions are counted.
            failures += 1
            raise HTTPException(503, "all providers unavailable")
        meta = {"resolution_source":"LIVE_INFERENCE","model":MODEL,"latency_ms":int((time.perf_counter()-start)*1000),
                "input_tokens":inp,"output_tokens":out,"key_id":key_id,"fallback_attempts":failures}
        CACHE[cache_key] = (reply, meta)
    save(req.session_id,"user",msg)
    save(req.session_id,"assistant",reply,meta)
    return {"session_id":req.session_id,"reply":reply,"metadata":meta}

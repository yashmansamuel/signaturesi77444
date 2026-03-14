# api/index.py

import os
import logging
import secrets
import string
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from supabase import create_client, Client
from cerebras.cloud.sdk import Cerebras

# -----------------------------
# Logger Setup
# -----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------
# FastAPI App & CORS
# -----------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for testing; change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Configuration (Environment Variables)
# -----------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
ADMIN_SECRET_PASS = os.getenv("ADMIN_SECRET_PASS")

# -----------------------------
# Clients Initialization
# -----------------------------
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)
    logger.info("Signaturesi Backend: Neo L1.0 Engine Connected Successfully.")
except Exception as e:
    logger.error(f"Initialization Error: {e}")

# -----------------------------
# Request Model
# -----------------------------
class GenerateKeyRequest(BaseModel):
    tokens: int = 0
    admin_pass: str

# -----------------------------
# 1. Dashboard Route
# -----------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    try:
        with open("dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>Signaturesi Dashboard File Not Found</h1>"

# -----------------------------
# 2. Get User Balance
# -----------------------------
@app.get("/v1/user/balance")
async def get_balance(api_key: str):
    try:
        res = supabase.table("users").select("token_balance").eq("api_key", api_key).execute()
        if not res.data or len(res.data) == 0:
            raise HTTPException(status_code=404, detail="API Key not found")
        balance = res.data[0].get("token_balance", 0)
        return {"balance": balance, "model": "Neo-L1.0"}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Balance API Error: {e}")
        raise HTTPException(status_code=500, detail="Database Error")

# -----------------------------
# 3. Admin Generate API Key
# -----------------------------
@app.post("/admin/generate-key")
async def generate_key(req: GenerateKeyRequest):
    if req.admin_pass != ADMIN_SECRET_PASS:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    random_part = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    new_key = f"sig-live-{random_part}"
    
    supabase.table("users").insert({"api_key": new_key, "token_balance": req.tokens}).execute()
    
    return {"new_api_key": new_key, "tokens": req.tokens}

# -----------------------------
# 4. Chat Endpoint (Neo L1.0)
# -----------------------------
@app.post("/v1/chat/completions")
async def chat_proxy(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API Key")
    
    user_api_key = authorization.replace("Bearer ", "")
    
    res = supabase.table("users").select("token_balance").eq("api_key", user_api_key).execute()
    if not res.data or len(res.data) == 0:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    current_balance = res.data[0].get("token_balance", 0)
    if current_balance <= 0:
        raise HTTPException(status_code=402, detail="No Balance")

    body = await request.json()
    
    try:
        ai_response = cerebras_client.chat.completions.create(
            messages=[{"role": "system", "content": "You are Neo L1.0 by Signaturesi."}] + body.get("messages", []),
            model="llama3.1-8b",
            temperature=0.4,
            stream=False
        )

        tokens_used = ai_response.usage.total_tokens
        new_balance = current_balance - tokens_used
        
        supabase.table("users").update({"token_balance": new_balance}).eq("api_key", user_api_key).execute()
        
        ai_response.model = "Neo-L1.0"
        return ai_response
    except Exception as e:
        logger.error(f"Cerebras API Error: {e}")
        raise HTTPException(status_code=500, detail="Neo L1.0 Inference Failed")

# -----------------------------
# Required for Vercel serverless
# -----------------------------
handler = app
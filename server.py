from dotenv import load_dotenv
from pathlib import Path
import os
import logging

# Load env

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from bson import ObjectId

# ─── MongoDB FIXED CONNECTION ─────────────────────────────

mongo_url = os.environ.get("MONGO_URL")
if not mongo_url:
    raise Exception("MONGO_URL not found")

client = AsyncIOMotorClient(
mongo_url,
tls=True,
tlsAllowInvalidCertificates=True
)

db = client[os.environ.get('DB_NAME', 'dabzo')]

JWT_SECRET = os.environ.get("JWT_SECRET", "secret")
JWT_ALGORITHM = "HS256"

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(**name**)

# ─── Helpers ─────────────────────────────────────────────

def hash_password(password: str) -> str:
return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(p, h):
return bcrypt.checkpw(p.encode(), h.encode())

def create_token(uid, email, role):
payload = {
"sub": uid,
"email": email,
"role": role,
"exp": datetime.now(timezone.utc) + timedelta(days=7)
}
return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def serialize(doc):
doc = dict(doc)
doc["id"] = str(doc.pop("_id"))
doc.pop("password_hash", None)
return doc

async def get_user(req: Request):
token = req.headers.get("Authorization", "").replace("Bearer ", "")
try:
payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
return serialize(user)
except:
raise HTTPException(401, "Invalid token")

# ─── MODELS ─────────────────────────────────────────────

class Login(BaseModel):
email: str
password: str

class Register(BaseModel):
name: str
email: str
password: str
role: str = "user"

# ─── AUTH ─────────────────────────────────────────────

@api_router.post("/auth/register")
async def register(r: Register):
if await db.users.find_one({"email": r.email}):
raise HTTPException(400, "Email exists")

```
uid = str((await db.users.insert_one({
    "email": r.email,
    "password_hash": hash_password(r.password),
    "name": r.name,
    "role": r.role
})).inserted_id)

return {
    "token": create_token(uid, r.email, r.role),
    "user": {"id": uid, "email": r.email, "name": r.name, "role": r.role}
}
```

@api_router.post("/auth/login")
async def login(r: Login):
user = await db.users.find_one({"email": r.email})
if not user or not verify_password(r.password, user["password_hash"]):
raise HTTPException(401, "Invalid login")

```
uid = str(user["_id"])
return {
    "token": create_token(uid, r.email, user["role"]),
    "user": {"id": uid, "email": r.email, "name": user["name"], "role": user["role"]}
}
```

@api_router.get("/auth/me")
async def me(req: Request):
return await get_user(req)

# ─── TEST ROUTE ─────────────────────────────────────────

@api_router.get("/vendors")
async def vendors():
v = await db.vendors.find().to_list(100)
return [serialize(x) for x in v]

# ─── HEALTH ─────────────────────────────────────────────

@api_router.get("/health")
async def health():
return {"status": "ok"}

# ─── APP SETUP ─────────────────────────────────────────

app.include_router(api_router)

app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

# ─── STARTUP ───────────────────────────────────────────

@app.on_event("startup")
async def startup():
logger.info("Starting Dabzo API...")
await db.users.create_index("email", unique=True)

```
# Safe file write
try:
    creds_path = Path("./memory/test.txt")
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text("Backend running")
except Exception as e:
    logger.warning(f"File write skipped: {e}")

logger.info("Dabzo API ready!")
```

@app.on_event("shutdown")
async def shutdown():
client.close()

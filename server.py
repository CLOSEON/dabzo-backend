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
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from bson import ObjectId

# ─── DB SETUP ─────────────────────────

mongo_url = os.environ.get("MONGO_URL")
if not mongo_url:
    raise Exception("MONGO_URL not found")

client = AsyncIOMotorClient(mongo_url, tls=True, tlsAllowInvalidCertificates=True)
db = client[os.environ.get('DB_NAME', 'dabzo')]

JWT_SECRET = os.environ.get("JWT_SECRET", "secret")
JWT_ALGORITHM = "HS256"

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── HELPERS ─────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())

def create_token(uid: str, email: str, role: str) -> str:
    payload = {
        "sub": uid,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def serialize(doc):
    if not doc:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc

async def get_user(req: Request):
    token = req.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(401, "Missing token")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise Exception("User not found")
        return serialize(user)
    except Exception:
        raise HTTPException(401, "Invalid token")

# ─── MODELS ─────────────────────────

class Login(BaseModel):
    email: str
    password: str

class Register(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"

class Dish(BaseModel):
    name: str
    price: float

# ─── AUTH ─────────────────────────

@api_router.post("/auth/register")
async def register(r: Register):
    if await db.users.find_one({"email": r.email}):
        raise HTTPException(400, "Email exists")

    result = await db.users.insert_one({
        "email": r.email,
        "password_hash": hash_password(r.password),
        "name": r.name,
        "business_name": r.name if r.role == "vendor" else None,
        "role": r.role,
        "is_approved": True,
        "created_at": datetime.now(timezone.utc)
    })

    uid = str(result.inserted_id)

    return {
        "token": create_token(uid, r.email, r.role),
        "user": {
            "id": uid,
            "email": r.email,
            "name": r.name,
            "role": r.role
        }
    }

@api_router.post("/auth/login")
async def login(r: Login):
    user = await db.users.find_one({"email": r.email})
    if not user or not verify_password(r.password, user["password_hash"]):
        raise HTTPException(401, "Invalid login")

    uid = str(user["_id"])

    return {
        "token": create_token(uid, user["email"], user["role"]),
        "user": {
            "id": uid,
            "email": user["email"],
            "name": user["name"],
            "role": user["role"]
        }
    }

@api_router.get("/auth/me")
async def me(req: Request):
    return await get_user(req)

# ─── VENDORS ─────────────────────────

@api_router.get("/vendors")
async def get_vendors():
    vendors = await db.users.find({"role": "vendor"}).to_list(100)
    return [serialize(v) for v in vendors]

@api_router.get("/admin/vendors")
async def get_all_vendors():
    vendors = await db.users.find({"role": "vendor"}).to_list(100)
    return [serialize(v) for v in vendors]

@api_router.get("/vendor/{vendor_id}")
async def get_vendor(vendor_id: str):
    vendor = await db.users.find_one({
        "_id": ObjectId(vendor_id),
        "role": "vendor"
    })

    if not vendor:
        raise HTTPException(404, "Vendor not found")

    return serialize(vendor)

@api_router.get("/vendor/profile")
async def vendor_profile(req: Request):
    user = await get_user(req)
    if user["role"] != "vendor":
        raise HTTPException(403, "Not a vendor")
    return user

# ─── MENU SYSTEM ─────────────────────────

@api_router.post("/menu")
async def add_dish(req: Request, d: Dish):
    user = await get_user(req)

    if user["role"] != "vendor":
        raise HTTPException(403, "Not a vendor")

    result = await db.menus.insert_one({
        "vendor_id": user["id"],
        "name": d.name,
        "price": d.price,
        "created_at": datetime.now(timezone.utc)
    })

    return {"id": str(result.inserted_id)}

@api_router.get("/menu/{vendor_id}")
async def get_menu(vendor_id: str):
    items = await db.menus.find({"vendor_id": vendor_id}).to_list(100)
    return [serialize(i) for i in items]

@api_router.get("/vendor/menus")
async def get_my_menus(req: Request):
    user = await get_user(req)

    if user["role"] != "vendor":
        raise HTTPException(403, "Not a vendor")

    menus = await db.menus.find({"vendor_id": user["id"]}).to_list(100)
    return [serialize(m) for m in menus]

# ─── DASHBOARD ─────────────────────────

@api_router.get("/dashboard")
async def dashboard(req: Request):
    user = await get_user(req)

    if user["role"] == "admin":
        total_users = await db.users.count_documents({})
        total_vendors = await db.users.count_documents({"role": "vendor"})

        return {
            "total_users": total_users,
            "total_vendors": total_vendors
        }

    elif user["role"] == "vendor":
        menus = await db.menus.find({"vendor_id": user["id"]}).to_list(100)

        return {
            "menu_count": len(menus)
        }

    else:
        return {"message": "User dashboard"}

# ─── HEALTH ─────────────────────────

@api_router.get("/health")
async def health():
    return {"status": "ok"}

# ─── APP SETUP ─────────────────────────

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── STARTUP ─────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("Starting Dabzo API...")
    await db.users.create_index("email", unique=True)
    logger.info("Dabzo API ready!")

@app.on_event("shutdown")
async def shutdown():
    client.close()

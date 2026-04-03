from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from bson import ObjectId

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'dabzo')]

JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── Helpers ───────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access"
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def serialize_doc(doc):
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc

async def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return serialize_doc(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(user: dict, role: str):
    if user.get("role") != role:
        raise HTTPException(status_code=403, detail="Forbidden")

# ─── Pydantic Models ──────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"
    business_name: Optional[str] = None
    cuisine_type: Optional[str] = None
    price_per_meal: Optional[float] = None
    description: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class MenuCreateRequest(BaseModel):
    date: str
    meal_type: str
    items: List[dict]

class SubscriptionCreateRequest(BaseModel):
    vendor_id: str
    meal_type: str = "lunch"

class ComplaintCreateRequest(BaseModel):
    vendor_id: str
    subject: str
    description: str

class ComplaintResponseRequest(BaseModel):
    admin_response: str
    status: str = "resolved"

class VendorWarnRequest(BaseModel):
    reason: str

# ─── Auth Routes ───────────────────────────────────────────

@api_router.post("/auth/register")
async def register(req: RegisterRequest):
    email = req.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_doc = {
        "email": email,
        "password_hash": hash_password(req.password),
        "name": req.name,
        "role": req.role if req.role in ["user", "vendor"] else "user",
        "created_at": datetime.now(timezone.utc)
    }
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)

    if req.role == "vendor":
        vendor_doc = {
            "user_id": user_id,
            "business_name": req.business_name or f"{req.name}'s Kitchen",
            "description": req.description or "Fresh home-cooked meals",
            "cuisine_type": req.cuisine_type or "Home Style",
            "price_per_meal": req.price_per_meal or 100.0,
            "delivery_areas": [],
            "reliability_score": 80,
            "is_approved": False,
            "subscriber_count": 0,
            "created_at": datetime.now(timezone.utc)
        }
        await db.vendors.insert_one(vendor_doc)

    token = create_access_token(user_id, email, user_doc["role"])
    return {
        "token": token,
        "user": {"id": user_id, "email": email, "name": req.name, "role": user_doc["role"]}
    }

@api_router.post("/auth/login")
async def login(req: LoginRequest):
    email = req.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id = str(user["_id"])
    token = create_access_token(user_id, email, user["role"])
    return {
        "token": token,
        "user": {"id": user_id, "email": email, "name": user["name"], "role": user["role"]}
    }

@api_router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user

# ─── Public / User Routes ─────────────────────────────────

@api_router.get("/vendors")
async def list_vendors(search: Optional[str] = None):
    query = {"is_approved": True, "is_disabled": {"$ne": True}}
    if search:
        query["$or"] = [
            {"business_name": {"$regex": search, "$options": "i"}},
            {"cuisine_type": {"$regex": search, "$options": "i"}}
        ]
    # Vendors with reduced visibility go to end
    vendors = await db.vendors.find(query).sort([("visibility_reduced", 1), ("reliability_score", -1)]).to_list(100)
    return [serialize_doc(v) for v in vendors]

@api_router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str):
    vendor = await db.vendors.find_one({"_id": ObjectId(vendor_id)})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return serialize_doc(vendor)

@api_router.get("/vendors/{vendor_id}/menus")
async def get_vendor_menus(vendor_id: str, date: Optional[str] = None):
    query = {"vendor_id": vendor_id}
    if date:
        query["date"] = date
    menus = await db.menus.find(query).sort("date", -1).to_list(50)
    return [serialize_doc(m) for m in menus]

# ─── Subscription Routes ──────────────────────────────────

@api_router.post("/subscriptions")
async def create_subscription(req: SubscriptionCreateRequest, request: Request):
    user = await get_current_user(request)
    require_role(user, "user")

    existing = await db.subscriptions.find_one({
        "user_id": user["id"], "vendor_id": req.vendor_id, "status": "active"
    })
    if existing:
        raise HTTPException(status_code=400, detail="Already subscribed to this vendor")

    vendor = await db.vendors.find_one({"_id": ObjectId(req.vendor_id)})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    sub_doc = {
        "user_id": user["id"],
        "vendor_id": req.vendor_id,
        "vendor_name": vendor.get("business_name", ""),
        "meal_type": req.meal_type,
        "status": "active",
        "start_date": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc)
    }
    await db.subscriptions.insert_one(sub_doc)
    await db.vendors.update_one({"_id": ObjectId(req.vendor_id)}, {"$inc": {"subscriber_count": 1}})
    return {"message": "Subscribed successfully"}

@api_router.get("/subscriptions")
async def get_my_subscriptions(request: Request):
    user = await get_current_user(request)
    subs = await db.subscriptions.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
    return [serialize_doc(s) for s in subs]

@api_router.put("/subscriptions/{sub_id}/cancel")
async def cancel_subscription(sub_id: str, request: Request):
    user = await get_current_user(request)
    sub = await db.subscriptions.find_one({"_id": ObjectId(sub_id), "user_id": user["id"]})
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    await db.subscriptions.update_one({"_id": ObjectId(sub_id)}, {"$set": {"status": "inactive"}})
    if sub.get("status") == "active":
        await db.vendors.update_one({"_id": ObjectId(sub["vendor_id"])}, {"$inc": {"subscriber_count": -1}})
    return {"message": "Subscription cancelled"}

# ─── Complaint Routes ─────────────────────────────────────

@api_router.post("/complaints")
async def create_complaint(req: ComplaintCreateRequest, request: Request):
    user = await get_current_user(request)
    require_role(user, "user")

    vendor = await db.vendors.find_one({"_id": ObjectId(req.vendor_id)})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    complaint_doc = {
        "user_id": user["id"],
        "user_name": user["name"],
        "vendor_id": req.vendor_id,
        "vendor_name": vendor.get("business_name", ""),
        "subject": req.subject,
        "description": req.description,
        "status": "open",
        "admin_response": "",
        "created_at": datetime.now(timezone.utc)
    }
    await db.complaints.insert_one(complaint_doc)
    # Reduce reliability score (-10 per complaint)
    new_score = max(0, vendor.get("reliability_score", 80) - 10)
    await db.vendors.update_one({"_id": ObjectId(req.vendor_id)}, {"$set": {"reliability_score": round(new_score)}})
    return {"message": "Complaint filed successfully"}

@api_router.get("/complaints")
async def get_my_complaints(request: Request):
    user = await get_current_user(request)
    query = {"user_id": user["id"]} if user["role"] == "user" else {}
    complaints = await db.complaints.find(query).sort("created_at", -1).to_list(100)
    return [serialize_doc(c) for c in complaints]

# ─── Vendor Dashboard Routes ──────────────────────────────

@api_router.get("/vendor/profile")
async def get_vendor_profile(request: Request):
    user = await get_current_user(request)
    require_role(user, "vendor")
    vendor = await db.vendors.find_one({"user_id": user["id"]})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor profile not found")
    return serialize_doc(vendor)

@api_router.get("/vendor/dashboard")
async def get_vendor_dashboard(request: Request):
    user = await get_current_user(request)
    require_role(user, "vendor")
    vendor = await db.vendors.find_one({"user_id": user["id"]})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    vendor_id = str(vendor["_id"])
    active_subs = await db.subscriptions.count_documents({"vendor_id": vendor_id, "status": "active"})
    total_subs = await db.subscriptions.count_documents({"vendor_id": vendor_id})
    complaints_count = await db.complaints.count_documents({"vendor_id": vendor_id, "status": "open"})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    todays_menus = await db.menus.find({"vendor_id": vendor_id, "date": today}).to_list(10)
    tomorrows_menus = await db.menus.count_documents({"vendor_id": vendor_id, "date": tomorrow})

    # Get today's subscribers with user details and meal type breakdown
    active_sub_docs = await db.subscriptions.find({"vendor_id": vendor_id, "status": "active"}).to_list(200)
    lunch_subs = []
    dinner_subs = []
    for s in active_sub_docs:
        user_doc = await db.users.find_one({"_id": ObjectId(s["user_id"])})
        sub_info = {
            "id": str(s["_id"]),
            "user_name": user_doc.get("name", "User") if user_doc else "User",
            "user_email": user_doc.get("email", "") if user_doc else "",
            "meal_type": s.get("meal_type", "lunch"),
            "since": s.get("start_date", s.get("created_at", "")).isoformat() if hasattr(s.get("start_date", ""), "isoformat") else str(s.get("start_date", "")),
        }
        mt = s.get("meal_type", "lunch")
        if mt in ("lunch", "both"):
            lunch_subs.append(sub_info)
        if mt in ("dinner", "both"):
            dinner_subs.append(sub_info)

    return {
        "vendor": serialize_doc(vendor),
        "active_subscribers": active_subs,
        "total_subscribers": total_subs,
        "open_complaints": complaints_count,
        "todays_menus": [serialize_doc(m) for m in todays_menus],
        "todays_menu_count": len(todays_menus),
        "tomorrow_menu_posted": tomorrows_menus > 0,
        "tomorrow_date": tomorrow,
        "today_date": today,
        "lunch_subscribers": lunch_subs,
        "dinner_subscribers": dinner_subs,
        "total_deliveries_today": len(lunch_subs) + len(dinner_subs),
    }

@api_router.post("/vendor/menus")
async def create_menu(req: MenuCreateRequest, request: Request):
    user = await get_current_user(request)
    require_role(user, "vendor")
    vendor = await db.vendors.find_one({"user_id": user["id"]})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    vendor_id = str(vendor["_id"])
    existing = await db.menus.find_one({"vendor_id": vendor_id, "date": req.date, "meal_type": req.meal_type})
    if existing:
        await db.menus.update_one(
            {"_id": existing["_id"]},
            {"$set": {"items": req.items, "updated_at": datetime.now(timezone.utc)}}
        )
        return {"message": "Menu updated"}

    menu_doc = {
        "vendor_id": vendor_id,
        "date": req.date,
        "meal_type": req.meal_type,
        "items": req.items,
        "created_at": datetime.now(timezone.utc)
    }
    await db.menus.insert_one(menu_doc)
    return {"message": "Menu created"}

@api_router.get("/vendor/menus")
async def get_my_menus(request: Request):
    user = await get_current_user(request)
    require_role(user, "vendor")
    vendor = await db.vendors.find_one({"user_id": user["id"]})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    vendor_id = str(vendor["_id"])
    menus = await db.menus.find({"vendor_id": vendor_id}).sort("date", -1).to_list(50)
    return [serialize_doc(m) for m in menus]

@api_router.delete("/vendor/menus/{menu_id}")
async def delete_menu(menu_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "vendor")
    vendor = await db.vendors.find_one({"user_id": user["id"]})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    menu = await db.menus.find_one({"_id": ObjectId(menu_id), "vendor_id": str(vendor["_id"])})
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    await db.menus.delete_one({"_id": ObjectId(menu_id)})
    return {"message": "Menu deleted"}

@api_router.get("/vendor/subscribers")
async def get_vendor_subscribers(request: Request):
    user = await get_current_user(request)
    require_role(user, "vendor")
    vendor = await db.vendors.find_one({"user_id": user["id"]})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    vendor_id = str(vendor["_id"])
    subs = await db.subscriptions.find({"vendor_id": vendor_id}).sort("created_at", -1).to_list(100)
    result = []
    for s in subs:
        s_data = serialize_doc(s)
        user_doc = await db.users.find_one({"_id": ObjectId(s["user_id"])})
        if user_doc:
            s_data["user_name"] = user_doc.get("name", "")
            s_data["user_email"] = user_doc.get("email", "")
        result.append(s_data)
    return result

# ─── Admin Routes ──────────────────────────────────────────

@api_router.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")

    total_users = await db.users.count_documents({"role": "user"})
    total_vendors = await db.vendors.count_documents({})
    approved_vendors = await db.vendors.count_documents({"is_approved": True})
    pending_vendors = await db.vendors.count_documents({"is_approved": False})
    active_subs = await db.subscriptions.count_documents({"status": "active"})
    open_complaints = await db.complaints.count_documents({"status": "open"})
    disabled_vendors = await db.vendors.count_documents({"is_disabled": True})

    # Low reliability vendors (score < 80 out of 100)
    low_rel_cursor = db.vendors.find({"reliability_score": {"$lt": 80}}).sort("reliability_score", 1)
    low_rel_vendors_raw = await low_rel_cursor.to_list(50)
    low_rel_vendors = []
    for v in low_rel_vendors_raw:
        vid = str(v["_id"])
        complaint_count = await db.complaints.count_documents({"vendor_id": vid})
        open_count = await db.complaints.count_documents({"vendor_id": vid, "status": "open"})
        resolved_count = await db.complaints.count_documents({"vendor_id": vid, "status": "resolved"})
        trend = "stable"
        if open_count > 0:
            trend = "down"
        elif resolved_count > complaint_count * 0.5 and complaint_count > 0:
            trend = "up"
        vd = serialize_doc(v)
        vd["complaint_count"] = complaint_count
        vd["open_complaint_count"] = open_count
        vd["score_trend"] = trend
        low_rel_vendors.append(vd)

    # System health score (0-100)
    avg_score_cursor = db.vendors.aggregate([
        {"$match": {"is_approved": True}},
        {"$group": {"_id": None, "avg": {"$avg": "$reliability_score"}}}
    ])
    avg_result = await avg_score_cursor.to_list(1)
    avg_score = avg_result[0]["avg"] if avg_result else 100
    health_score = round(min(100, avg_score))

    return {
        "total_users": total_users,
        "total_vendors": total_vendors,
        "approved_vendors": approved_vendors,
        "pending_vendors": pending_vendors,
        "active_subscriptions": active_subs,
        "open_complaints": open_complaints,
        "disabled_vendors": disabled_vendors,
        "low_reliability_vendors": low_rel_vendors,
        "system_health_score": health_score,
    }

@api_router.get("/admin/vendors")
async def admin_list_vendors(request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    vendors = await db.vendors.find().sort("reliability_score", 1).to_list(200)
    result = []
    for v in vendors:
        vid = str(v["_id"])
        complaint_count = await db.complaints.count_documents({"vendor_id": vid})
        open_count = await db.complaints.count_documents({"vendor_id": vid, "status": "open"})
        resolved_count = await db.complaints.count_documents({"vendor_id": vid, "status": "resolved"})
        trend = "stable"
        if open_count > 0:
            trend = "down"
        elif resolved_count > complaint_count * 0.5 and complaint_count > 0:
            trend = "up"
        vd = serialize_doc(v)
        vd["complaint_count"] = complaint_count
        vd["open_complaint_count"] = open_count
        vd["score_trend"] = trend
        result.append(vd)
    return result

@api_router.put("/admin/vendors/{vendor_id}/approve")
async def approve_vendor(vendor_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    result = await db.vendors.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"is_approved": True, "is_disabled": False, "visibility_reduced": False}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor approved"}

@api_router.put("/admin/vendors/{vendor_id}/reject")
async def reject_vendor(vendor_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    result = await db.vendors.update_one({"_id": ObjectId(vendor_id)}, {"$set": {"is_approved": False}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor rejected"}

@api_router.put("/admin/vendors/{vendor_id}/warn")
async def warn_vendor(vendor_id: str, req: VendorWarnRequest, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    vendor = await db.vendors.find_one({"_id": ObjectId(vendor_id)})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    warnings_count = vendor.get("warnings_count", 0) + 1
    await db.vendors.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {
            "warnings_count": warnings_count,
            "last_warning_at": datetime.now(timezone.utc),
            "last_warning_reason": req.reason,
        }}
    )
    return {"message": f"Warning #{warnings_count} issued", "warnings_count": warnings_count}

@api_router.put("/admin/vendors/{vendor_id}/reduce-visibility")
async def reduce_visibility(vendor_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    result = await db.vendors.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"visibility_reduced": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor visibility reduced"}

@api_router.put("/admin/vendors/{vendor_id}/restore-visibility")
async def restore_visibility(vendor_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    result = await db.vendors.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"visibility_reduced": False}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor visibility restored"}

@api_router.put("/admin/vendors/{vendor_id}/disable")
async def disable_vendor(vendor_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    result = await db.vendors.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"is_disabled": True, "is_approved": False}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor disabled"}

@api_router.put("/admin/vendors/{vendor_id}/enable")
async def enable_vendor(vendor_id: str, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    result = await db.vendors.update_one(
        {"_id": ObjectId(vendor_id)},
        {"$set": {"is_disabled": False, "is_approved": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {"message": "Vendor enabled"}

@api_router.get("/admin/complaints")
async def admin_list_complaints(request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")
    complaints = await db.complaints.find().sort("created_at", -1).to_list(200)
    return [serialize_doc(c) for c in complaints]

@api_router.put("/admin/complaints/{complaint_id}")
async def respond_to_complaint(complaint_id: str, req: ComplaintResponseRequest, request: Request):
    user = await get_current_user(request)
    require_role(user, "admin")

    result = await db.complaints.update_one(
        {"_id": ObjectId(complaint_id)},
        {"$set": {"admin_response": req.admin_response, "status": req.status}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if req.status == "resolved":
        complaint = await db.complaints.find_one({"_id": ObjectId(complaint_id)})
        if complaint:
            vendor = await db.vendors.find_one({"_id": ObjectId(complaint["vendor_id"])})
            if vendor:
                new_score = min(100, vendor.get("reliability_score", 80) + 5)
                await db.vendors.update_one({"_id": vendor["_id"]}, {"$set": {"reliability_score": round(new_score)}})

    return {"message": "Complaint updated"}

# ─── Health check ──────────────────────────────────────────

@api_router.get("/health")
async def health():
    return {"status": "ok", "service": "dabzo-api"}

# ─── App config ────────────────────────────────────────────

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Startup / Shutdown ───────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("Starting Dabzo API...")
    await db.users.create_index("email", unique=True)
    await db.subscriptions.create_index([("user_id", 1), ("vendor_id", 1)])
    await db.menus.create_index([("vendor_id", 1), ("date", 1)])
    await db.complaints.create_index("vendor_id")
    await seed_admin()
    await seed_demo_data()
    logger.info("Dabzo API ready!")

async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@dabzo.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc)
        })
        logger.info(f"Admin seeded: {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}}
        )
        logger.info("Admin password updated")

async def seed_demo_data():
    vendor_count = await db.vendors.count_documents({})
    if vendor_count > 0:
        return

    # Seed test user
    test_user = await db.users.find_one({"email": "user@dabzo.com"})
    if not test_user:
        await db.users.insert_one({
            "email": "user@dabzo.com",
            "password_hash": hash_password("user123"),
            "name": "Test User",
            "role": "user",
            "created_at": datetime.now(timezone.utc)
        })

    vendors_data = [
        {
            "name": "Amma's Kitchen",
            "email": "amma@dabzo.com",
            "cuisine": "South Indian",
            "price": 80,
            "description": "Authentic South Indian home-cooked meals made with love and traditional recipes",
            "score": 92,
            "areas": ["Koramangala", "HSR Layout", "BTM Layout"]
        },
        {
            "name": "Sharma Ji Tiffin",
            "email": "sharma@dabzo.com",
            "cuisine": "North Indian",
            "price": 100,
            "description": "Daily fresh North Indian thali with roti, sabzi, dal and rice. Just like ghar ka khana!",
            "score": 85,
            "areas": ["Indiranagar", "Whitefield", "Marathahalli"]
        },
        {
            "name": "Green Bowl",
            "email": "greenbowl@dabzo.com",
            "cuisine": "Healthy & Organic",
            "price": 150,
            "description": "Organic ingredients, balanced nutrition, calorie-counted meals delivered fresh daily",
            "score": 97,
            "areas": ["JP Nagar", "Jayanagar", "Banashankari"]
        },
    ]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    menu_items_lunch = [
        [
            {"name": "Sambar Rice", "description": "Tangy lentil curry with steamed rice", "tags": ["veg"]},
            {"name": "Rasam", "description": "Spicy tamarind soup", "tags": ["veg", "spicy"]},
            {"name": "Curd Rice", "description": "Yogurt mixed rice with tempering", "tags": ["veg"]},
        ],
        [
            {"name": "Dal Tadka", "description": "Yellow lentil curry with ghee tempering", "tags": ["veg"]},
            {"name": "Jeera Rice", "description": "Cumin-flavored basmati rice", "tags": ["veg"]},
            {"name": "Aloo Gobi", "description": "Potato and cauliflower dry curry", "tags": ["veg"]},
            {"name": "Roti (4 pcs)", "description": "Fresh wheat flatbread", "tags": ["veg"]},
        ],
        [
            {"name": "Quinoa Bowl", "description": "Protein-rich quinoa with roasted veggies", "tags": ["veg", "healthy"]},
            {"name": "Mixed Greens Salad", "description": "Fresh organic greens with vinaigrette", "tags": ["veg", "healthy"]},
            {"name": "Grilled Paneer", "description": "Herb-marinated cottage cheese", "tags": ["veg", "healthy"]},
        ],
    ]

    menu_items_dinner = [
        [
            {"name": "Dosa", "description": "Crispy rice crepe with chutney", "tags": ["veg"]},
            {"name": "Idli Sambar", "description": "Steamed rice cakes with lentil curry", "tags": ["veg"]},
            {"name": "Payasam", "description": "Traditional rice pudding dessert", "tags": ["veg"]},
        ],
        [
            {"name": "Paneer Butter Masala", "description": "Rich creamy cottage cheese curry", "tags": ["veg"]},
            {"name": "Naan (3 pcs)", "description": "Soft tandoor bread", "tags": ["veg"]},
            {"name": "Raita", "description": "Yogurt with spiced vegetables", "tags": ["veg"]},
        ],
        [
            {"name": "Grilled Chicken Salad", "description": "Lean protein with fresh greens", "tags": ["non-veg", "healthy"]},
            {"name": "Sweet Potato Soup", "description": "Creamy roasted sweet potato", "tags": ["veg", "healthy"]},
            {"name": "Overnight Oats", "description": "Chilled oats with berries", "tags": ["veg", "healthy"]},
        ],
    ]

    for i, v in enumerate(vendors_data):
        result = await db.users.insert_one({
            "email": v["email"],
            "password_hash": hash_password("vendor123"),
            "name": v["name"],
            "role": "vendor",
            "created_at": datetime.now(timezone.utc)
        })
        user_id = str(result.inserted_id)

        vendor_result = await db.vendors.insert_one({
            "user_id": user_id,
            "business_name": v["name"],
            "description": v["description"],
            "cuisine_type": v["cuisine"],
            "price_per_meal": v["price"],
            "delivery_areas": v["areas"],
            "reliability_score": v["score"],
            "is_approved": True,
            "subscriber_count": 0,
            "created_at": datetime.now(timezone.utc)
        })
        vendor_id = str(vendor_result.inserted_id)

        await db.menus.insert_one({
            "vendor_id": vendor_id,
            "date": today,
            "meal_type": "lunch",
            "items": menu_items_lunch[i],
            "created_at": datetime.now(timezone.utc)
        })
        await db.menus.insert_one({
            "vendor_id": vendor_id,
            "date": today,
            "meal_type": "dinner",
            "items": menu_items_dinner[i],
            "created_at": datetime.now(timezone.utc)
        })
        await db.menus.insert_one({
            "vendor_id": vendor_id,
            "date": tomorrow,
            "meal_type": "lunch",
            "items": menu_items_lunch[i],
            "created_at": datetime.now(timezone.utc)
        })

    logger.info("Demo data seeded: 3 vendors with menus + 1 test user")

    # Write test credentials
    creds_path = Path("./memory/test_credentials.md")
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(
        "# Dabzo Test Credentials\n\n"
        "## Admin\n- Email: admin@dabzo.com\n- Password: admin123\n- Role: admin\n\n"
        "## Test User\n- Email: user@dabzo.com\n- Password: user123\n- Role: user\n\n"
        "## Vendor Accounts\n"
        "- Email: amma@dabzo.com / Password: vendor123 / Role: vendor\n"
        "- Email: sharma@dabzo.com / Password: vendor123 / Role: vendor\n"
        "- Email: greenbowl@dabzo.com / Password: vendor123 / Role: vendor\n\n"
        "## Auth Endpoints\n"
        "- POST /api/auth/register\n"
        "- POST /api/auth/login\n"
        "- GET /api/auth/me\n"
    )

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

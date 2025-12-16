import os
import httpx
import requests
from uuid import UUID, uuid4
from typing import Optional, List, Dict
from decimal import Decimal
from datetime import datetime, timedelta 
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from pydantic import BaseModel

# --- GCS IMPORT ---
try:
    from google.cloud import storage
except ImportError:
    storage = None
# ------------------

from fastapi import FastAPI, HTTPException, Form, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
import jwt

from models.composite_models import (
    CompositeUser,
    CompositeItem,
    CompositeWallet,
    CompositeTransaction,
    CompositeTransactionCreate,
)

# Configuration
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8001").rstrip("/")
LISTING_SERVICE_URL = os.getenv("LISTING_SERVICE_URL", "http://localhost:8002").rstrip("/")
TRANSACTION_SERVICE_URL = os.getenv("TRANSACTION_SERVICE_URL", "http://localhost:8003").rstrip("/")

# --- UPDATED BUCKET NAME ---
BUCKET_NAME = os.getenv("BUCKET_NAME", "flipzy-frontend") 
# ---------------------------

SECRET_KEY = "YOUR_SECRET_KEY"
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 120

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI(title="Composite Service")

# --- UPDATED CORS SETTINGS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*", 
        "https://storage.googleapis.com",  # Allow your frontend bucket
        "https://storage.googleapis.com/flipzy-frontend"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# -----------------------------

ITEM_SELLER_MAP: Dict[UUID, UUID] = {}

# ... (Keep JWT Utility & Helper Functions exactly as before) ...
# (Copy-paste create_jwt, verify_jwt, require_admin, get_user, get_item, create_transaction, ensure_wallet_exists from previous version)

def create_jwt(user_id: str, role: str):
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_jwt(token: str = Depends(oauth2_scheme)):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def require_admin(claims: dict):
    if claims.get("role") != "admin":
        raise HTTPException(403, "Admin role required")

def get_user(user_id: UUID) -> CompositeUser:
    try:
        res = requests.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=5)
        res.raise_for_status()
        return CompositeUser(**res.json())
    except Exception:
        raise HTTPException(404, "User not found")

def get_item(item_id: UUID, seller_id: UUID) -> CompositeItem:
    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=5)
        res.raise_for_status()
        return CompositeItem(**res.json())
    except Exception:
        raise HTTPException(404, "Item not found")

def create_transaction(data: dict):
    res = requests.post(f"{TRANSACTION_SERVICE_URL}/transactions", json=data)
    res.raise_for_status()
    return res.json()

def ensure_wallet_exists(user_id: UUID):
    try:
        res = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets", params={"user_id": str(user_id)})
        wallets = res.json()
        if wallets:
            return wallets[0]
        create_res = requests.post(f"{TRANSACTION_SERVICE_URL}/wallets", json={"user_id": str(user_id)})
        if create_res.status_code == 400:
             res = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets", params={"user_id": str(user_id)})
             return res.json()[0]
        create_res.raise_for_status()
        return create_res.json()
    except Exception as e:
        print(f"Error ensuring wallet for {user_id}: {e}")
        return None

# ============================================================
# NEW: GCS UPLOAD FUNCTION
# ============================================================
def upload_file_to_bucket(file: UploadFile) -> str:
    """Uploads file to GCS bucket and returns public URL."""
    if not storage:
        print("GCS library not found. Returning fake URL.")
        return f"https://fake-storage.com/{file.filename}"

    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        
        # Save to 'uploads/' folder
        blob_name = f"uploads/{uuid4()}-{file.filename}"
        blob = bucket.blob(blob_name)
        
        blob.upload_from_file(file.file, content_type=file.content_type)
        
        # Return the public link
        return f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
    except Exception as e:
        print(f"GCS Upload Error: {e}")
        return f"https://upload-failed.com/{file.filename}"

# ... (Keep standard endpoints: root, me, list_items, wallet, transactions, login) ...
@app.get("/")
def root():
    return {"message": "Composite Service Running"}

@app.get("/composite/me", response_model=CompositeUser)
def get_current_user_profile(claims=Depends(verify_jwt)):
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(400, "Invalid token claims")
    return get_user(UUID(user_id))

@app.get("/composite/items", response_model=List[CompositeItem])
def list_composite_items():
    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items", timeout=5)
        res.raise_for_status()
        items_data = res.json()
        return [CompositeItem(**item) for item in items_data]
    except Exception as e:
        print(f"Error fetching items: {e}")
        return []

@app.get("/composite/wallet")
def get_my_wallet_balance(claims=Depends(verify_jwt)):
    user_id = claims.get("sub")
    wallet = ensure_wallet_exists(user_id)
    if not wallet:
        raise HTTPException(500, "Could not load wallet")
    return wallet

@app.get("/composite/my-transactions")
def get_my_transactions(claims=Depends(verify_jwt)):
    user_id = claims.get("sub")
    try:
        res = requests.get(f"{TRANSACTION_SERVICE_URL}/transactions", params={"buyer_id": user_id})
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"History Error: {e}")
        return []

class CompositeDeposit(BaseModel):
    amount: Decimal

@app.post("/composite/wallet/deposit")
def deposit_money(payload: CompositeDeposit, claims=Depends(verify_jwt)):
    user_id = claims.get("sub")
    wallet = ensure_wallet_exists(user_id)
    if not wallet:
        raise HTTPException(500, "Wallet not found")
    try:
        res = requests.post(
            f"{TRANSACTION_SERVICE_URL}/wallets/{wallet['id']}/deposit",
            json={"amount": str(payload.amount)}
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        raise HTTPException(500, "Deposit failed")

class GoogleLoginRequest(BaseModel):
    email: str
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    google_token: str

@app.post("/login/google")
def login_with_google(login: GoogleLoginRequest):
    email_q = quote(login.email)
    res = httpx.get(f"{USER_SERVICE_URL}/users/by_email/{email_q}")
    if res.status_code == 200:
        user = CompositeUser(**res.json())
    else:
        new_user = {
            "email": login.email,
            "username": login.username,
            "full_name": login.full_name,
            "avatar_url": login.avatar_url,
            "phone": "0000000000",
            "role": "user",
        }
        created = httpx.post(f"{USER_SERVICE_URL}/users", json=new_user)
        created.raise_for_status()
        user = CompositeUser(**created.json())
    jwt_token = create_jwt(str(user.id), user.role)
    return {"user": user, "jwt": jwt_token}

@app.get("/admin/area")
def admin_area(claims=Depends(verify_jwt)):
    require_admin(claims)
    return {"message": "Admin access granted"}

# ============================================================
# CREATE ITEM (The 1-2-3 Logic)
# ============================================================
@app.post("/composite/items/create", response_model=CompositeItem)
def create_item_from_frontend(
    seller_id: str = Form(...),
    name: str = Form(...),
    price: Decimal = Form(...),
    description: str = Form(...),
    status: str = Form(...),
    condition: str = Form(...),
    category_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    claims=Depends(verify_jwt) 
):
    media_list = []

    # --- STEP 1: UPLOAD TO GCS & CREATE MEDIA RECORD ---
    if file:
        real_url = upload_file_to_bucket(file)
        
        media_payload = {
            "url": real_url,
            "type": "image",
            "alt_text": name,
            "is_primary": True
        }
        
        try:
            media_res = httpx.post(f"{LISTING_SERVICE_URL}/media", json=media_payload)
            if media_res.status_code == 201:
                media_data = media_res.json()
                media_list.append({"id": media_data['id']})
            else:
                print(f"Media DB creation failed: {media_res.text}")
        except Exception as e:
            print(f"Media Service Connection Error: {e}")

    # --- STEP 2 & 3: CREATE ITEM & LINK MEDIA ---
    listing_payload = {
        "name": name,
        "description": description,
        "price": str(price),
        "status": status,
        "condition": condition,
        "category": {"id": category_id},
        "owner_user_id": seller_id, 
        "media": media_list,        
    }

    print(f"Sending to Listing Service: {listing_payload}") 

    res = httpx.post(f"{LISTING_SERVICE_URL}/items", json=listing_payload)
    
    if res.status_code not in (200, 201):
        print(f"Listing Service Error: {res.text}")
        # IMPORTANT: Return the actual error so you see 500 instead of just CORS failure
        raise HTTPException(res.status_code, res.text)

    created = res.json()
    item_id = UUID(created["id"])
    ITEM_SELLER_MAP[item_id] = UUID(seller_id)
    
    return CompositeItem(**created)

# ... (Keep Transaction endpoints) ...
@app.post("/composite/transactions", response_model=CompositeTransaction)
def create_composite_transaction(payload: CompositeTransactionCreate, claims=Depends(verify_jwt)):
    buyer = get_user(payload.buyer_id)
    seller = get_user(payload.seller_id)
    item = get_item(payload.item_id, payload.seller_id)
    ensure_wallet_exists(payload.buyer_id)
    ensure_wallet_exists(payload.seller_id)
    tx_payload = payload.dict()
    tx_payload["title_snapshot"] = item.name
    tx_payload["price_snapshot"] = str(item.price)
    tx_raw = create_transaction(tx_payload)
    return CompositeTransaction(
        id=tx_raw["id"],
        buyer=buyer,
        seller=seller,
        item=item,
        order_type=tx_raw["order_type"],
        title_snapshot=tx_raw["title_snapshot"],
        price_snapshot=Decimal(tx_raw["price_snapshot"]),
        status=tx_raw["status"],
        created_at=tx_raw["created_at"],
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
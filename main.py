import os
import httpx
import requests
from uuid import UUID
from typing import Optional, List, Dict
from decimal import Decimal
from datetime import datetime, timedelta 
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from pydantic import BaseModel

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

# ============================================================
# Service Configuration
# ============================================================
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8001").rstrip("/")
LISTING_SERVICE_URL = os.getenv("LISTING_SERVICE_URL", "http://localhost:8002").rstrip("/")
TRANSACTION_SERVICE_URL = os.getenv("TRANSACTION_SERVICE_URL", "http://localhost:8003").rstrip("/")

# JWT setup
SECRET_KEY = "YOUR_SECRET_KEY"
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 120

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI(title="Composite Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ITEM_SELLER_MAP: Dict[UUID, UUID] = {}
executor = ThreadPoolExecutor(max_workers=5)


# ============================================================
# JWT Utility
# ============================================================

def create_jwt(user_id: str, role: str):
    """Generate a signed JWT token containing user id and role."""
    # This line was crashing because datetime wasn't imported!
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_jwt(token: str = Depends(oauth2_scheme)):
    """Validate JWT token and return decoded claims."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_admin(claims: dict):
    """Ensure requesting user has admin role."""
    if claims.get("role") != "admin":
        raise HTTPException(403, "Admin role required")

# ============================================================
# Helper Functions
# ============================================================

def get_user(user_id: UUID) -> CompositeUser:
    """Fetch user from User Service."""
    try:
        res = requests.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=5)
        res.raise_for_status()
        return CompositeUser(**res.json())
    except Exception:
        raise HTTPException(404, "User not found")


def get_item(item_id: UUID, seller_id: UUID) -> CompositeItem:
    """Fetch item from Listing Service."""
    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=5)
        res.raise_for_status()
        return CompositeItem(**res.json())
    except Exception:
        raise HTTPException(404, "Item not found")


def create_transaction(data: dict):
    """Send transaction creation request to Transaction Service."""
    res = requests.post(f"{TRANSACTION_SERVICE_URL}/transactions", json=data)
    res.raise_for_status()
    return res.json()


def ensure_wallet_exists(user_id: UUID):
    """
    Smart Helper: 
    1. Checks if wallet exists (GET).
    2. If missing, Creates it (POST).
    """
    try:
        # 1. Check if wallet exists
        res = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets", params={"user_id": str(user_id)})
        wallets = res.json()
        
        if wallets:
            return wallets[0] # Found it!
            
        # 2. If not found, Create it
        print(f"Creating missing wallet for user {user_id}")
        create_res = requests.post(f"{TRANSACTION_SERVICE_URL}/wallets", json={"user_id": str(user_id)})
        
        if create_res.status_code == 400:
             # Race condition fallback
             res = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets", params={"user_id": str(user_id)})
             return res.json()[0]

        create_res.raise_for_status()
        return create_res.json()
    except Exception as e:
        print(f"Error ensuring wallet for {user_id}: {e}")
        return None


# ============================================================
# Public Endpoint
# ============================================================

@app.get("/")
def root():
    return {"message": "Composite Service Running"}


# ============================================================
# User Profile & Items
# ============================================================

@app.get("/composite/me", response_model=CompositeUser)
def get_current_user_profile(claims=Depends(verify_jwt)):
    """
    Uses the JWT token to fetch the full user profile.
    """
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(400, "Invalid token claims")
    
    return get_user(UUID(user_id))


@app.get("/composite/items", response_model=List[CompositeItem])
def list_composite_items():
    """Fetch all items from the listing service."""
    try:
        # Fetch raw items from Listing Service
        res = requests.get(f"{LISTING_SERVICE_URL}/items", timeout=5)
        res.raise_for_status()
        items_data = res.json()
        
        # Convert to CompositeItem list
        return [CompositeItem(**item) for item in items_data]
    except Exception as e:
        print(f"Error fetching items: {e}")
        return []


# ============================================================
# Wallet & History Endpoints
# ============================================================

@app.get("/composite/wallet")
def get_my_wallet_balance(claims=Depends(verify_jwt)):
    """
    Get current user's wallet. 
    If they don't have one, create it automatically.
    """
    user_id = claims.get("sub")
    
    wallet = ensure_wallet_exists(user_id)
    if not wallet:
        raise HTTPException(500, "Could not load wallet")
        
    return wallet


@app.get("/composite/my-transactions")
def get_my_transactions(claims=Depends(verify_jwt)):
    """Fetch transaction history where the user is the BUYER."""
    user_id = claims.get("sub")
    try:
        res = requests.get(f"{TRANSACTION_SERVICE_URL}/transactions", params={"buyer_id": user_id})
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"History Error: {e}")
        return []

# --- NEW DEPOSIT ENDPOINT ---
class CompositeDeposit(BaseModel):
    amount: Decimal

@app.post("/composite/wallet/deposit")
def deposit_money(payload: CompositeDeposit, claims=Depends(verify_jwt)):
    """Add money to the logged-in user's wallet."""
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
        print(f"Deposit failed: {e}")
        raise HTTPException(500, "Deposit failed")


# ============================================================
# Google OAuth Login
# ============================================================

class GoogleLoginRequest(BaseModel):
    email: str
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    google_token: str


@app.post("/login/google")
def login_with_google(login: GoogleLoginRequest):
    """Simulated Google OAuth login. Creates account if missing and returns JWT."""

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


# ============================================================
# Admin Endpoint
# ============================================================

@app.get("/admin/area")
def admin_area(claims=Depends(verify_jwt)):
    """Endpoint only accessible by admin users."""
    require_admin(claims)
    return {"message": "Admin access granted"}


# ============================================================
# Create Item
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
    """Create item in listing service (JWT protected)."""

    listing_payload = {
        "name": name,
        "description": description,
        "price": str(price),
        "status": status,
        "condition": condition,
        "category": {"id": category_id},
        "media": [],
    }

    res = httpx.post(f"{LISTING_SERVICE_URL}/items", json=listing_payload)
    if res.status_code not in (200, 201):
        raise HTTPException(res.status_code, res.text)

    created = res.json()
    item_id = UUID(created["id"])

    ITEM_SELLER_MAP[item_id] = UUID(seller_id)
    return CompositeItem(**created)


# ============================================================
# Create Transaction
# ============================================================

@app.post("/composite/transactions", response_model=CompositeTransaction)
def create_composite_transaction(payload: CompositeTransactionCreate, claims=Depends(verify_jwt)):
    """Create full transaction with user, seller, and item data."""

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


# ============================================================
# Run App
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
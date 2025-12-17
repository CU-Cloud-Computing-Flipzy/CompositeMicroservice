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

from fastapi import FastAPI, HTTPException, Form, File, UploadFile, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
import jwt

# Import models
from models.composite_models import (
    CompositeUser,
    CompositeItem,
    CompositeWallet,
    CompositeTransaction,
    CompositeTransactionCreate,
    CompositeAddress,
    CompositeDeposit
)

# Configuration
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8001").rstrip("/")
LISTING_SERVICE_URL = os.getenv("LISTING_SERVICE_URL", "http://localhost:8002").rstrip("/")
TRANSACTION_SERVICE_URL = os.getenv("TRANSACTION_SERVICE_URL", "http://localhost:8003").rstrip("/")

BUCKET_NAME = os.getenv("BUCKET_NAME", "flipzy-frontend") 

SECRET_KEY = "YOUR_SECRET_KEY"
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 120

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI(title="Composite Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://storage.googleapis.com", 
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ITEM_SELLER_MAP: Dict[UUID, UUID] = {}

# ============================================================
# HELPER MODELS
# ============================================================
class UserProfileFlat(CompositeUser):
    """Merges User + Address so frontend can read 'user.address' directly."""
    address: Optional[CompositeAddress] = None

class GoogleLoginRequest(BaseModel):
    email: str
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    google_token: str


# ============================================================
# AUTH & HELPERS
# ============================================================

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

def upload_file_to_bucket(file: UploadFile) -> str:
    """Uploads file to GCS bucket with NO-CACHE metadata."""
    if not storage:
        print("GCS library not found. Returning fake URL.")
        return f"https://fake-storage.com/{file.filename}"

    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        
        blob_name = f"uploads/{uuid4()}-{file.filename}"
        blob = bucket.blob(blob_name)
        
        # Disable caching for instant updates
        blob.cache_control = "no-cache, max-age=0"
        
        blob.upload_from_file(file.file, content_type=file.content_type)
        return f"https://storage.googleapis.com/{BUCKET_NAME}/{blob_name}"
    except Exception as e:
        print(f"GCS Upload Error: {e}")
        return f"https://upload-failed.com/{file.filename}"

def get_user_with_address(user_id: UUID) -> UserProfileFlat:
    """Fetches User + Address and merges them for the frontend."""
    try:
        # 1. User Data
        res = requests.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=10)
        res.raise_for_status()
        user_data = res.json()

        # 2. Address Data
        address_obj = None
        try:
            addr_res = requests.get(f"{USER_SERVICE_URL}/addresses", params={"user_id": str(user_id)}, timeout=5)
            if addr_res.status_code == 200:
                addresses = addr_res.json()
                if addresses and len(addresses) > 0:
                    address_obj = addresses[0]
        except Exception as e:
            print(f"Address fetch warning: {e}")

        # 3. Merge
        user_data["address"] = address_obj
        return UserProfileFlat(**user_data)

    except Exception:
        raise HTTPException(404, "User not found")

def ensure_wallet_exists(user_id: UUID):
    try:
        res = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets", params={"user_id": str(user_id)}, timeout=10)
        wallets = res.json()
        if wallets:
            return wallets[0]
        
        create_res = requests.post(f"{TRANSACTION_SERVICE_URL}/wallets", json={"user_id": str(user_id)}, timeout=10)
        if create_res.status_code == 400:
             res = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets", params={"user_id": str(user_id)}, timeout=10)
             return res.json()[0]
        create_res.raise_for_status()
        return create_res.json()
    except Exception as e:
        print(f"Error ensuring wallet: {e}")
        return None

def create_transaction_helper(data: dict):
    res = requests.post(f"{TRANSACTION_SERVICE_URL}/transactions", json=data, timeout=10)
    res.raise_for_status()
    return res.json()


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/")
def root():
    return {"message": "Composite Service Running"}

@app.get("/composite/me", response_model=UserProfileFlat)
def get_current_user_profile(claims=Depends(verify_jwt)):
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(400, "Invalid token claims")
    return get_user_with_address(UUID(user_id))

@app.post("/composite/profile")
def update_my_profile(
    payload: dict = Body(...),
    claims=Depends(verify_jwt)
):
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    phone = payload.get("phone")
    address_data = payload.get("address")

    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    if not address_data:
        raise HTTPException(status_code=400, detail="address is required")

    # 1. Update User Phone (User Service)
    try:
        res = requests.patch(
            f"{USER_SERVICE_URL}/users/{user_id}",
            json={"phone": phone},
            timeout=10
        )
        if res.status_code not in (200, 204):
            print(f"Warning: Phone update returned {res.status_code}: {res.text}")
    except Exception as e:
        print(f"Phone Update Non-Critical Error: {e}")

    # 2. Check for existing address
    existing_address_id = None
    try:
        check_res = requests.get(f"{USER_SERVICE_URL}/addresses", params={"user_id": user_id}, timeout=10)
        if check_res.status_code == 200:
            addresses = check_res.json()
            if addresses:
                existing_address_id = addresses[0]['id']
    except Exception:
        pass 

    # 3. Create or Update Address
    final_address = {}
    try:
        addr_payload = {
            "country": address_data.get("country"),
            "city": address_data.get("city"),
            "street": address_data.get("street"),
            "postal_code": address_data.get("postal_code")
        }

        if existing_address_id:
            # UPDATE (PUT)
            update_res = requests.put(
                f"{USER_SERVICE_URL}/addresses/{existing_address_id}",
                json=addr_payload,
                timeout=10
            )
            update_res.raise_for_status()
            final_address = update_res.json()
        else:
            # CREATE (POST)
            addr_payload["user_id"] = user_id
            create_res = requests.post(
                f"{USER_SERVICE_URL}/addresses",
                json=addr_payload,
                timeout=10
            )
            create_res.raise_for_status()
            final_address = create_res.json()

    except Exception as e:
        raise HTTPException(502, f"Failed to save address: {e}")

    return {
        "message": "Profile updated successfully",
        "phone": phone,
        "address": final_address
    }

@app.get("/composite/items")
def list_composite_items():
    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items", timeout=10)
        res.raise_for_status()
        items_data = res.json()
        return items_data
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
def get_my_transactions(
    buyer_id: Optional[str] = None, 
    seller_id: Optional[str] = None, 
    claims=Depends(verify_jwt)
):
    user_id = claims.get("sub")
    
    if buyer_id and buyer_id != user_id:
        raise HTTPException(403, "Cannot view other users' buyer history")
    if seller_id and seller_id != user_id:
        raise HTTPException(403, "Cannot view other users' seller history")

    params = {}
    if buyer_id: params['buyer_id'] = buyer_id
    if seller_id: params['seller_id'] = seller_id
    
    if not params:
        params['buyer_id'] = user_id

    try:
        res = requests.get(f"{TRANSACTION_SERVICE_URL}/transactions", params=params, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"History Error: {e}")
        return []

@app.post("/composite/wallet/deposit")
def deposit_money(payload: CompositeDeposit, claims=Depends(verify_jwt)):
    user_id = claims.get("sub")
    wallet = ensure_wallet_exists(user_id)
    if not wallet:
        raise HTTPException(500, "Wallet not found")
    try:
        res = requests.post(
            f"{TRANSACTION_SERVICE_URL}/wallets/{wallet['id']}/deposit",
            json={"amount": str(payload.amount)},
            timeout=10
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        raise HTTPException(500, "Deposit failed")

@app.post("/login/google")
def login_with_google(login: GoogleLoginRequest):
    email_q = quote(login.email)
    res = httpx.get(f"{USER_SERVICE_URL}/users/by_email/{email_q}")
    if res.status_code == 200:
        user = UserProfileFlat(**res.json())
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
        user = UserProfileFlat(**created.json())
    jwt_token = create_jwt(str(user.id), user.role)
    return {"user": user, "jwt": jwt_token}

@app.get("/admin/area")
def admin_area(claims=Depends(verify_jwt)):
    require_admin(claims)
    return {"message": "Admin access granted"}

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
            print(f"Media Service Error: {e}")

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

    res = httpx.post(f"{LISTING_SERVICE_URL}/items", json=listing_payload)
    if res.status_code not in (200, 201):
        raise HTTPException(res.status_code, res.text)

    created = res.json()
    return CompositeItem(**created)

@app.delete("/composite/items/{item_id}", status_code=204)
def delete_my_item(
    item_id: UUID,
    claims=Depends(verify_jwt)
):
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token")

    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=10)
        res.raise_for_status()
        item = res.json()
    except Exception:
        raise HTTPException(404, "Item not found")

    if item.get("owner_user_id") != user_id:
        raise HTTPException(403, "You can only delete your own items")

    try:
        del_res = requests.delete(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=10)
        del_res.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Failed to delete item: {e}")

    return None

@app.patch("/composite/items/{item_id}", response_model=CompositeItem)
def update_my_item(
    item_id: UUID,
    payload: dict = Body(...),
    claims=Depends(verify_jwt)
):
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token")

    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=10)
        res.raise_for_status()
        item = res.json()
    except Exception:
        raise HTTPException(404, "Item not found")

    if item.get("owner_user_id") != user_id:
        raise HTTPException(403, "You can only update your own items")

    try:
        update_res = requests.patch(f"{LISTING_SERVICE_URL}/items/{item_id}", json=payload, timeout=10)
        update_res.raise_for_status()
        updated_item = update_res.json()
    except Exception as e:
        raise HTTPException(502, f"Failed to update item: {e}")

    return CompositeItem(**updated_item)

@app.delete("/admin/items/{item_id}", status_code=204)
def admin_delete_item(
    item_id: UUID,
    claims=Depends(verify_jwt)
):
    require_admin(claims)

    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=10)
        if res.status_code == 404:
            raise HTTPException(404, "Item not found")
        res.raise_for_status()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch item: {e}")

    try:
        del_res = requests.delete(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=10)
        del_res.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Failed to delete item: {e}")

    return None


@app.post("/composite/transactions", response_model=CompositeTransaction)
def create_composite_transaction(
    payload: CompositeTransactionCreate,
    claims=Depends(verify_jwt)
):
    buyer_id = claims.get("sub")
    if not buyer_id:
        raise HTTPException(401, "Invalid token")

    # Parallel fetch: buyer profile + item details
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_buyer = executor.submit(get_user_with_address, UUID(buyer_id))
        future_item = executor.submit(
            requests.get,
            f"{LISTING_SERVICE_URL}/items/{payload.item_id}",
            5
        )

        buyer = future_buyer.result()
        item_res = future_item.result()

    if item_res.status_code != 200:
        raise HTTPException(404, "Item not found")

    item_data = item_res.json()
    item = CompositeItem(**item_data)

    seller_id = item.owner_user_id
    if not seller_id:
        raise HTTPException(422, "Item missing owner_user_id")

    if str(seller_id) == str(buyer_id):
        raise HTTPException(400, "Cannot purchase your own item")

    # Parallel fetch: seller profile + wallet checks
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_seller = executor.submit(get_user_with_address, seller_id)
        future_wallet_buyer = executor.submit(ensure_wallet_exists, UUID(buyer_id))
        future_wallet_seller = executor.submit(ensure_wallet_exists, seller_id)

        seller = future_seller.result()
        future_wallet_buyer.result()
        future_wallet_seller.result()

    final_price = payload.price_snapshot if payload.price_snapshot is not None else item.price

    tx_payload = {
        "buyer_id": str(buyer_id),
        "seller_id": str(seller_id),
        "item_id": str(payload.item_id),
        "order_type": payload.order_type,
        "title_snapshot": item.name,
        "price_snapshot": str(final_price),
    }

    tx_raw = create_transaction_helper(tx_payload)

    item.price = float(final_price)

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

@app.post("/composite/transactions/{tx_id}/checkout")
def checkout_real_transaction(
    tx_id: UUID,
    claims=Depends(verify_jwt)
):
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token")

    # 1. Get Transaction Details
    try:
        res = requests.get(
            f"{TRANSACTION_SERVICE_URL}/transactions/{tx_id}",
            timeout=5
        )
        res.raise_for_status()
        tx = res.json()
    except Exception:
        raise HTTPException(404, "Transaction not found")

    if tx.get("buyer_id") != user_id:
        raise HTTPException(
            status_code=403,
            detail="Only buyer can checkout this transaction"
        )

    # 2. Perform Checkout (Pay)
    try:
        checkout_res = requests.post(
            f"{TRANSACTION_SERVICE_URL}/transactions/{tx_id}/checkout",
            timeout=5
        )
        checkout_res.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Checkout failed: {e}")

    item_id = tx.get("item_id")
    if item_id:
        try:
            requests.delete(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=5)
            print(f"Auto-deleted item {item_id} after purchase")
        except Exception as e:
            print(f"Warning: Failed to auto-delete item: {e}")

    return checkout_res.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
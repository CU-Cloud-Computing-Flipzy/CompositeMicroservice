import os
import httpx
import requests
from uuid import UUID
from typing import Optional, List, Dict
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from datetime import datetime

from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Use defaults for safety if env vars are missing during testing
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:8001").rstrip("/")
LISTING_SERVICE_URL = os.getenv("LISTING_SERVICE_URL", "http://localhost:8002").rstrip("/")
TRANSACTION_SERVICE_URL = os.getenv("TRANSACTION_SERVICE_URL", "http://localhost:8003").rstrip("/")

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

# ==========================================
# 2. MODELS (Moved here to avoid import errors)
# ==========================================
class CompositeUser(BaseModel):
    id: UUID
    username: str
    email: str
    avatar_url: Optional[str] = None
    balance: Optional[str] = None

class CompositeItem(BaseModel):
    id: UUID
    name: str
    description: str
    price: float
    seller_id: UUID
    category: Optional[dict] = None
    media: List[dict] = []

class CompositeWallet(BaseModel):
    id: UUID
    user_id: UUID
    balance: float

class CompositeTransaction(BaseModel):
    id: UUID
    buyer: Optional[CompositeUser]
    seller: Optional[CompositeUser]
    item: Optional[CompositeItem]
    price_snapshot: str
    status: str
    created_at: datetime

class CompositeTransactionCreate(BaseModel):
    buyer_id: UUID
    seller_id: UUID
    item_id: UUID
    order_type: str

class GoogleLoginRequest(BaseModel):
    email: str
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    google_token: str

# ==========================================
# 3. HELPER FUNCTIONS (Wrappers for Services)
# ==========================================
def get_user(user_id: UUID) -> CompositeUser:
    try:
        res = requests.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            return CompositeUser(**data, balance="0.00") # Mock balance if missing
    except Exception:
        pass
    # Fallback/Mock if service down
    return CompositeUser(id=user_id, username="Unknown", email="unknown@example.com")

def get_item(item_id: UUID, seller_id: UUID) -> CompositeItem:
    try:
        res = requests.get(f"{LISTING_SERVICE_URL}/items/{item_id}", timeout=5)
        if res.status_code == 200:
            data = res.json()
            return CompositeItem(
                id=UUID(data["id"]),
                name=data["name"],
                description=data["description"],
                price=data["price"],
                seller_id=seller_id,
                category=data.get("category"),
                media=data.get("media", [])
            )
    except Exception as e:
        print(f"Error fetching item: {e}")
    
    return CompositeItem(
        id=item_id, name="Unknown Item", description="", price=0.0, seller_id=seller_id
    )

def list_items(mapping: Dict[UUID, UUID]) -> List[CompositeItem]:

    results = []
    for i_id, s_id in mapping.items():
        results.append(get_item(i_id, s_id))
    return results

def get_transaction(tx_id: UUID):
    res = requests.get(f"{TRANSACTION_SERVICE_URL}/transactions/{tx_id}")
    res.raise_for_status()
    return res.json()

def create_transaction_in_service(data: dict):
    res = requests.post(f"{TRANSACTION_SERVICE_URL}/transactions", json=data)
    res.raise_for_status()
    return res.json()

# ==========================================
# 4. ENDPOINTS
# ==========================================

@app.get("/")
def root():
    return {"message": "Composite Service Running"}

@app.post("/composite/items/create", response_model=CompositeItem)
def create_item_from_frontend(
    seller_id: str = Form(...),
    name: str = Form(...),
    price: Decimal = Form(...),
    description: str = Form(...),
    status: str = Form(...),
    condition: str = Form(...),
    category_id: str = Form(...),
    file: UploadFile | None = File(None) 
):

    listing_service_payload = {
        "name": name,
        "description": description,
        "price": float(price),
        "status": status,
        "condition": condition,
        "category": {
            "id": category_id  
        },
        "media": [] 
    }

    try:
        listing_res = httpx.post(f"{LISTING_SERVICE_URL}/items", json=listing_service_payload)
    except Exception as e:
         raise HTTPException(503, f"Failed to connect to Listing Service: {e}")

    if listing_res.status_code not in [200, 201]:
        print("Listing Service Error:", listing_res.text) 
        raise HTTPException(
            status_code=listing_res.status_code,
            detail=f"Listing Service Error: {listing_res.text}",
        )

    created = listing_res.json()
    item_id = UUID(created["id"])
    seller_uuid = UUID(seller_id)
    
    ITEM_SELLER_MAP[item_id] = seller_uuid

    return get_item(item_id, seller_uuid)

@app.post("/login/google")
def login_with_google(login_data: GoogleLoginRequest):
    encoded_email = quote(login_data.email)
    try:
        response = httpx.get(f"{USER_SERVICE_URL}/users/by_email/{encoded_email}")
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass

    new_user_payload = {
        "email": login_data.email,
        "username": login_data.username,
        "full_name": login_data.full_name,
        "avatar_url": login_data.avatar_url,
        "phone": "000-000-0000"
    }
    
    try:
        create_response = httpx.post(f"{USER_SERVICE_URL}/users", json=new_user_payload)
        create_response.raise_for_status()
        return create_response.json()
    except Exception as e:
        raise HTTPException(500, f"User creation failed: {str(e)}")

@app.get("/composite/users/{user_id}", response_model=CompositeUser)
def get_composite_user(user_id: UUID):
    return get_user(user_id)

@app.get("/composite/items/{item_id}", response_model=CompositeItem)
def get_composite_item(item_id: UUID):
    seller_id = ITEM_SELLER_MAP.get(item_id)
    if not seller_id:

        return get_item(item_id, UUID("00000000-0000-0000-0000-000000000000"))
    return get_item(item_id, seller_id)

@app.get("/composite/items", response_model=List[CompositeItem])
def list_composite_items():
    return list_items(ITEM_SELLER_MAP)

@app.post("/composite/transactions", response_model=CompositeTransaction)
def create_composite_transaction(payload: CompositeTransactionCreate):
    buyer = get_user(payload.buyer_id)
    seller = get_user(payload.seller_id)

    # In strict mode check map, for demo we might skip
    if ITEM_SELLER_MAP.get(payload.item_id) and ITEM_SELLER_MAP.get(payload.item_id) != payload.seller_id:
         raise HTTPException(400, "Item does not belong to seller")

    item = get_item(payload.item_id, payload.seller_id)

    enriched = {
        "buyer_id": str(payload.buyer_id),
        "seller_id": str(payload.seller_id),
        "item_id": str(payload.item_id),
        "order_type": payload.order_type,
        "title_snapshot": item.name,
        "price_snapshot": item.price,
    }

    tx_raw = create_transaction_in_service(enriched)

    return CompositeTransaction(
        id=tx_raw["id"],
        buyer=buyer,
        seller=seller,
        item=item,
        price_snapshot=str(tx_raw["price_snapshot"]),
        status=tx_raw["status"],
        created_at=tx_raw["created_at"],
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
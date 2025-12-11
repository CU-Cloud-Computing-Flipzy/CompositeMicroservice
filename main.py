import os
import requests
import httpx
from uuid import UUID
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from concurrent.futures import ThreadPoolExecutor
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import quote

from models.composite_models import (
    CompositeUser,
    CompositeItem,
    CompositeWallet,
    CompositeTransaction,
    CompositeTransactionCreate,
)

raw_user_url = os.getenv("USER_SERVICE_URL")
USER_SERVICE_URL = raw_user_url.rstrip("/") if raw_user_url else None

raw_listing_url = os.getenv("LISTING_SERVICE_URL")
LISTING_SERVICE_URL = raw_listing_url.rstrip("/") if raw_listing_url else None

raw_transaction_url = os.getenv("TRANSACTION_SERVICE_URL")
TRANSACTION_SERVICE_URL = raw_transaction_url.rstrip("/") if raw_transaction_url else None

if not USER_SERVICE_URL or not LISTING_SERVICE_URL or not TRANSACTION_SERVICE_URL:
    raise RuntimeError("Missing required environment variables")

from services.user_service import get_user
from services.listing_service import get_item, list_items
from services.transaction_service import (
    get_wallet,
    create_transaction,
    get_transaction,
)

app = FastAPI(
    title="Composite Service",
    description="Aggregation layer",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ITEM_SELLER_MAP: dict[UUID, UUID] = {}

class GoogleLoginRequest(BaseModel):
    email: str
    username: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    google_token: str

class CreateItemPayload(BaseModel):
    seller_id: UUID
    name: str
    description: Optional[str] = ""
    price: float
    category_id: UUID
    media_ids: List[UUID] = []



@app.post("/composite/items/create", response_model=CompositeItem)
def create_item_from_frontend(
    # 1. Accept individual Form fields matches your Frontend .append() keys
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

    listing_res = httpx.post(f"{LISTING_SERVICE_URL}/items", json=listing_service_payload)

    if listing_res.status_code not in [200, 201]:
        print("Listing Service Error:", listing_res.text) 
        raise HTTPException(
            status_code=listing_res.status_code,
            detail="Failed to create item in Listing Service",
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

    create_response = httpx.post(f"{USER_SERVICE_URL}/users", json=new_user_payload)
    create_response.raise_for_status()
    return create_response.json()

@app.get("/composite/users/{user_id}", response_model=CompositeUser)
def get_composite_user(user_id: UUID):
    return get_user(user_id)

@app.get("/composite/items/{item_id}", response_model=CompositeItem)
def get_composite_item(item_id: UUID):
    seller_id = ITEM_SELLER_MAP.get(item_id)
    if not seller_id:
        raise HTTPException(404, "Seller not assigned")
    return get_item(item_id, seller_id)

@app.get("/composite/items", response_model=list[CompositeItem])
def list_composite_items():
    return list_items(ITEM_SELLER_MAP)

@app.get("/composite/categories/{category_id}/items", response_model=list[CompositeItem])
def items_by_category(category_id: UUID):
    items = list_items(ITEM_SELLER_MAP)
    return [i for i in items if i.category and i.category.id == category_id]

@app.get("/composite/users/{user_id}/wallet")
def user_with_wallet(user_id: UUID):
    user = get_user(user_id)
    wallet = None
    wallets = requests.get(f"{TRANSACTION_SERVICE_URL}/wallets").json()
    for w in wallets:
        if w["user_id"] == str(user_id):
            wallet = CompositeWallet(**w)
            break
    return {"user": user, "wallet": wallet}

@app.post("/composite/transactions", response_model=CompositeTransaction)
def create_composite_transaction(payload: CompositeTransactionCreate):

    buyer = get_user(payload.buyer_id)
    seller = get_user(payload.seller_id)

    if ITEM_SELLER_MAP.get(payload.item_id) != payload.seller_id:
        raise HTTPException(400, "Item does not belong to seller")

    item = get_item(payload.item_id, payload.seller_id)

    enriched = {
        "buyer_id": payload.buyer_id,
        "seller_id": payload.seller_id,
        "item_id": payload.item_id,
        "order_type": payload.order_type,
        "title_snapshot": item.name,
        "price_snapshot": item.price,
    }

    tx_raw = create_transaction(enriched)

    return CompositeTransaction(
        id=tx_raw["id"],
        buyer=buyer,
        seller=seller,
        item=item,
        price_snapshot=str(tx_raw["price_snapshot"]),
        status=tx_raw["status"],
        created_at=tx_raw["created_at"],
    )

@app.post("/composite/transactions/{tx_id}/checkout")
def checkout(tx_id: UUID):
    r = requests.post(f"{TRANSACTION_SERVICE_URL}/transactions/{tx_id}/checkout")
    r.raise_for_status()
    return r.json()

executor = ThreadPoolExecutor(max_workers=5)

@app.get("/composite/transactions/{tx_id}", response_model=CompositeTransaction)
def get_tx(tx_id: UUID):
    tx = get_transaction(tx_id)

    buyer = executor.submit(get_user, UUID(tx["buyer_id"])).result()
    seller = executor.submit(get_user, UUID(tx["seller_id"])).result()
    item = executor.submit(
        get_item, UUID(tx["item_id"]), UUID(tx["seller_id"])
    ).result()

    return CompositeTransaction(
        id=tx["id"],
        buyer=buyer,
        seller=seller,
        item=item,
        price_snapshot=str(tx["price_snapshot"]),
        status=tx["status"],
        created_at=tx["created_at"],
    )

@app.get("/")
def root():
    return {"message": "Composite Service Running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

import os
import requests
from uuid import UUID
from fastapi import FastAPI, HTTPException
from concurrent.futures import ThreadPoolExecutor

# Composite models
from models.composite_models import (
    CompositeUser,
    CompositeItem,
    CompositeWallet,
    CompositeTransaction,
    CompositeTransactionCreate,
)

# Service adapters
from services.user_service import get_user
from services.listing_service import get_item, list_items
from services.transaction_service import (
    get_wallet,
    create_transaction,
    get_transaction,
)

app = FastAPI(
    title="Composite Service",
    description="Aggregation layer for User, Listing, and Transaction microservices.",
    version="1.0.0",
)

# ======================================================
# In-memory logical foreign key: item_id → seller_id
# ======================================================
ITEM_SELLER_MAP: dict[UUID, UUID] = {}


# ======================================================
# User API
# ======================================================
@app.get("/composite/users/{user_id}", response_model=CompositeUser)
def get_composite_user(user_id: UUID):
    try:
        return get_user(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")


# ======================================================
# Create item mapping: seller → item
# ======================================================
@app.post("/composite/items", response_model=CompositeItem)
def create_composite_item(seller_id: UUID, item_id: UUID):
    ITEM_SELLER_MAP[item_id] = seller_id

    # Validate seller
    try:
        get_user(seller_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Seller does not exist")

    # Validate item
    try:
        item = get_item(item_id, seller_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Item not found")

    return item


# ======================================================
# Get single item
# ======================================================
@app.get("/composite/items/{item_id}", response_model=CompositeItem)
def get_composite_item(item_id: UUID):
    seller_id = ITEM_SELLER_MAP.get(item_id)
    if seller_id is None:
        raise HTTPException(status_code=404, detail="Seller not assigned for this item")

    try:
        return get_item(item_id, seller_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Item not found")


# ======================================================
# List all items
# ======================================================
@app.get("/composite/items", response_model=list[CompositeItem])
def list_composite_items():
    return list_items(ITEM_SELLER_MAP)


# ======================================================
# List items by category
# ======================================================
@app.get("/composite/categories/{category_id}/items", response_model=list[CompositeItem])
def get_items_by_category(category_id: UUID):
    all_items = list_items(ITEM_SELLER_MAP)

    filtered = [
        item for item in all_items
        if item.category and item.category.id == category_id
    ]
    return filtered


# ======================================================
# User + Wallet
# ======================================================
@app.get("/composite/users/{user_id}/wallet")
def get_user_with_wallet(user_id: UUID):
    try:
        user = get_user(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")

    wallet_obj = None
    try:
        wallets = requests.get(
            f"{os.getenv('TRANSACTION_SERVICE_URL', 'http://localhost:8003')}/wallets"
        ).json()

        wallet = next((w for w in wallets if w["user_id"] == str(user_id)), None)
        if wallet:
            wallet_obj = CompositeWallet(**wallet)

    except Exception:
        wallet_obj = None

    return {"user": user, "wallet": wallet_obj}


# ======================================================
# Create Transaction
# ======================================================
@app.post("/composite/transactions", response_model=CompositeTransaction)
def create_composite_transaction(payload: CompositeTransactionCreate):
    # Validate buyer & seller
    try:
        buyer = get_user(payload.buyer_id)
        seller = get_user(payload.seller_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Buyer or seller not found")

    # Validate FK consistency
    fk_seller_id = ITEM_SELLER_MAP.get(payload.item_id)
    if fk_seller_id != payload.seller_id:
        raise HTTPException(status_code=400, detail="Item does not belong to this seller")

    # Get item with seller injected
    try:
        item = get_item(payload.item_id, payload.seller_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Item not found")

    # IMPORTANT — Add title & price snapshots
    enriched_payload = {
        "buyer_id": payload.buyer_id,
        "seller_id": payload.seller_id,
        "item_id": payload.item_id,
        "order_type": payload.order_type,
        "title_snapshot": item.name,
        "price_snapshot": item.price,
    }

    # Create transaction in Transaction Service
    tx_raw = create_transaction(enriched_payload)

    return CompositeTransaction(
        id=tx_raw["id"],
        buyer=buyer,
        seller=seller,
        item=item,
        price_snapshot=str(tx_raw["price_snapshot"]),
        status=tx_raw["status"],
        created_at=tx_raw["created_at"],
    )


# ======================================================
# Checkout
# ======================================================
@app.post("/composite/transactions/{tx_id}/checkout")
def checkout_transaction(tx_id: UUID):
    url = f"{os.getenv('TRANSACTION_SERVICE_URL', 'http://localhost:8003')}/transactions/{tx_id}/checkout"
    r = requests.post(url)

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Transaction not found")

    r.raise_for_status()
    return r.json()


# ======================================================
# Get Transaction w/ parallel execution (threads)
# ======================================================
executor = ThreadPoolExecutor(max_workers=5)

@app.get("/composite/transactions/{tx_id}", response_model=CompositeTransaction)
def get_composite_transaction(tx_id: UUID):
    try:
        tx_raw = get_transaction(tx_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Transaction not found")

    buyer_id = UUID(tx_raw["buyer_id"])
    seller_id = UUID(tx_raw["seller_id"])
    item_id = UUID(tx_raw["item_id"])

    # Parallel tasks
    future_buyer = executor.submit(get_user, buyer_id)
    future_seller = executor.submit(get_user, seller_id)
    future_item = executor.submit(get_item, item_id, seller_id)

    buyer = future_buyer.result()
    seller = future_seller.result()
    item = future_item.result()

    return CompositeTransaction(
        id=tx_raw["id"],
        buyer=buyer,
        seller=seller,
        item=item,
        price_snapshot=str(tx_raw["price_snapshot"]),
        status=tx_raw["status"],
        created_at=tx_raw["created_at"],
    )


# ======================================================
# Root
# ======================================================
@app.get("/")
def root():
    return {"message": "Composite Microservice Running"}

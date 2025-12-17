from __future__ import annotations
from uuid import UUID
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field

class CompositeAddress(BaseModel):
    id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    country: str
    city: str
    street: str
    postal_code: Optional[str] = None

# ======================================================
# Composite User (from User Microservice)
# ======================================================

class CompositeUser(BaseModel):
    id: UUID
    username: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ======================================================
# Category (from Listing Service)
# ======================================================

class CompositeCategory(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


# ======================================================
# Media (from Listing Service)
# ======================================================

class CompositeMedia(BaseModel):
    id: UUID
    url: str
    type: str
    alt_text: Optional[str] = None
    is_primary: bool
    created_at: datetime
    updated_at: datetime


# ======================================================
# Item (from Listing Service)
# ======================================================

class CompositeItem(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    description: str
    price: Decimal
    status: str
    condition: str
    category: CompositeCategory
    media: List[CompositeMedia]

    created_at: datetime
    updated_at: datetime
    links: Optional[dict] = None


# ======================================================
# Wallet (from Wallet Service)
# ======================================================

class CompositeWallet(BaseModel):
    id: UUID
    user_id: UUID
    balance: Decimal
    created_at: datetime
    updated_at: datetime


# ======================================================
# Transaction (from Transaction Service)
# ======================================================

class CompositeTransaction(BaseModel):
    id: UUID

    buyer: CompositeUser
    seller: CompositeUser

    item: CompositeItem

    order_type: str
    title_snapshot: str
    price_snapshot: Decimal

    status: str
    created_at: datetime


# ======================================================
# DTO for creating a transaction
# ======================================================

class CompositeTransactionCreate(BaseModel):
    buyer_id: UUID
    seller_id: UUID
    item_id: UUID

    order_type: str
    title_snapshot: str
    price_snapshot: Decimal
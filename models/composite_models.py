from __future__ import annotations
from uuid import UUID
from typing import List, Optional
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field

# ======================================================
# Address
# ======================================================
class CompositeAddress(BaseModel):
    id: Optional[UUID] = Field(None, description="Address ID")
    user_id: Optional[UUID] = Field(None, description="User ID")
    country: str = Field(..., min_length=1, max_length=60)
    city: str = Field(..., min_length=1, max_length=60)
    street: str = Field(..., min_length=1, max_length=120)
    postal_code: Optional[str] = Field(None, min_length=3, max_length=20)

# ======================================================
# Composite User
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
# Profile Response
# ======================================================
class CompositeProfileResponse(BaseModel):
    user: CompositeUser
    address: Optional[CompositeAddress] = None

# ======================================================
# Category
# ======================================================
class CompositeCategory(BaseModel):
    id: Optional[UUID] = None
    name: Optional[str] = "Uncategorized"
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# ======================================================
# Media
# ======================================================
class CompositeMedia(BaseModel):
    id: Optional[UUID] = None
    url: str
    type: Optional[str] = "image"
    alt_text: Optional[str] = None
    is_primary: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# ======================================================
# Item
# ======================================================
class CompositeItem(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    description: Optional[str] = ""
    price: float
    status: Optional[str] = "active"
    condition: Optional[str] = "new"
    category: Optional[CompositeCategory] = None
    media: List[CompositeMedia] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    links: Optional[dict] = None

    class Config:
        extra = "ignore"

# ======================================================
# Wallet & Deposit
# ======================================================
class CompositeWallet(BaseModel):
    id: UUID
    user_id: UUID
    balance: Decimal
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class CompositeDeposit(BaseModel):
    amount: Decimal

# ======================================================
# Transaction
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

class CompositeTransactionCreate(BaseModel):
    buyer_id: Optional[UUID] = None 
    seller_id: Optional[UUID] = None 
    item_id: UUID
    order_type: str
    title_snapshot: Optional[str] = None
    price_snapshot: Optional[Decimal] = None
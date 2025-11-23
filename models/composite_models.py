from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ======================================================
# User (from User Service)
# ======================================================

class CompositeUser(BaseModel):
    id: UUID
    username: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ======================================================
# Category / Media / Item (from Listing Service)
# ======================================================

class CompositeCategory(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None


class CompositeMedia(BaseModel):
    id: UUID
    url: str
    type: str
    alt_text: Optional[str] = None
    is_primary: bool = False


class CompositeItem(BaseModel):
    id: UUID
    seller_id: UUID
    name: str
    description: str
    price: str
    status: str
    condition: str
    category: Optional[CompositeCategory] = None
    media: List[CompositeMedia] = Field(default_factory=list)


# ======================================================
# Wallet / Transaction (from Transaction Service)
# ======================================================

class CompositeWallet(BaseModel):
    id: UUID
    user_id: UUID
    balance: str


class CompositeTransaction(BaseModel):
    id: UUID
    buyer: CompositeUser
    seller: CompositeUser
    item: CompositeItem
    price_snapshot: str
    status: str
    created_at: datetime


# ======================================================
# Composite DTOs
# ======================================================

class CompositeTransactionCreate(BaseModel):
    buyer_id: UUID
    seller_id: UUID
    item_id: UUID
    order_type: str

    
    title_snapshot: str
    price_snapshot: str
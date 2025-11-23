import os
import requests
from uuid import UUID
from typing import List, Optional

from models.composite_models import (
    CompositeItem,
    CompositeCategory,
    CompositeMedia
)

LISTING_SERVICE = os.getenv("LISTING_SERVICE_URL", "http://localhost:8002")


def get_item(item_id: UUID, seller_id: Optional[UUID] = None) -> CompositeItem:
    """
    Fetch a single item from the Listing Service and convert it to CompositeItem.
    seller_id is injected by the Composite layer because Listing Service does not provide it.
    """
    url = f"{LISTING_SERVICE}/items/{item_id}"
    r = requests.get(url)

    if r.status_code == 404:
        raise ValueError("Item not found")

    r.raise_for_status()
    data = r.json()

    # Convert category
    category = CompositeCategory(**data["category"]) if data.get("category") else None

    # Convert media
    media = [CompositeMedia(**m) for m in data.get("media", [])]

    return CompositeItem(
        id=data["id"],
        seller_id=seller_id,
        name=data["name"],
        description=data["description"],
        price=str(data["price"]),
        status=data["status"],
        condition=data["condition"],
        category=category,
        media=media,
    )


def list_items(item_seller_map: dict) -> List[CompositeItem]:
    """
    Fetch all items from Listing Service and attach seller_id from Composite's logical FK map.
    """
    url = f"{LISTING_SERVICE}/items"
    r = requests.get(url)
    r.raise_for_status()

    arr = r.json()
    items: List[CompositeItem] = []

    for data in arr:

        # Convert category
        category = CompositeCategory(**data["category"]) if data.get("category") else None

        # Convert media
        media = [CompositeMedia(**m) for m in data.get("media", [])]

        # Seller ID comes from composite's logical foreign key mapping
        seller_id = item_seller_map.get(
            UUID(data["id"]),
            None   # default None if not set yet
        )

        items.append(
            CompositeItem(
                id=data["id"],
                seller_id=seller_id,
                name=data["name"],
                description=data["description"],
                price=str(data["price"]),
                status=data["status"],
                condition=data["condition"],
                category=category,
                media=media,
            )
        )

    return items

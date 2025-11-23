import os
import requests
from uuid import UUID
from models.composite_models import CompositeUser


USER_SERVICE = os.getenv("USER_SERVICE_URL", "http://localhost:8001")


def get_user(user_id: UUID) -> CompositeUser:
    """Call User Service → GET /users/{user_id}"""
    url = f"{USER_SERVICE}/users/{user_id}"
    r = requests.get(url)
    if r.status_code == 404:
        raise ValueError("User not found")
    r.raise_for_status()
    return CompositeUser(**r.json())


def list_users() -> list[CompositeUser]:
    """Call User Service → GET /users"""
    url = f"{USER_SERVICE}/users"
    r = requests.get(url)
    r.raise_for_status()
    data = r.json()
    return [CompositeUser(**u) for u in data]

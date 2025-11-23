import os
import requests
from uuid import UUID

from models.composite_models import (
    CompositeWallet,
)


TRANSACTION_SERVICE = os.getenv("TRANSACTION_SERVICE_URL", "http://localhost:8003")


# ======================================================
# Get Wallet
# ======================================================
def get_wallet(wallet_id: UUID) -> CompositeWallet:
    url = f"{TRANSACTION_SERVICE}/wallets/{wallet_id}"
    r = requests.get(url)

    if r.status_code == 404:
        raise ValueError("Wallet not found")

    r.raise_for_status()
    data = r.json()

    return CompositeWallet(
        id=data["id"],
        user_id=data["user_id"],
        balance=str(data["balance"])
    )


# ======================================================
# Create Transaction
# ======================================================
def create_transaction(payload: dict) -> dict:
    """
    Call Transaction Service → POST /transactions
    Composite MUST include:
    - title_snapshot
    - price_snapshot
    """
    url = f"{TRANSACTION_SERVICE}/transactions"

    r = requests.post(url, json=payload)

    r.raise_for_status()
    return r.json()


# ======================================================
# Get raw transaction
# ======================================================
def get_transaction(tx_id: UUID) -> dict:
    url = f"{TRANSACTION_SERVICE}/transactions/{tx_id}"
    r = requests.get(url)

    if r.status_code == 404:
        raise ValueError("Transaction not found")

    r.raise_for_status()
    return r.json()

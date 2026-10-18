"""HMAC-SHA256 signed webhook dispatcher.

Adheres to Integration Standard #3:
"Optional callback URL, signed with HMAC-SHA256 in an X-IncuBrix-Signature header."
"""

import hmac
import hashlib
import json
from typing import Dict, Any, Optional
import httpx
from engine.config import settings
from engine.logging_config import logger


def sign_payload(payload_bytes: bytes, secret: str = settings.WEBHOOK_SECRET) -> str:
    """Computes HMAC-SHA256 hex digest of payload bytes."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def dispatch_webhook(
    callback_url: str,
    job_data: Dict[str, Any],
    secret: str = settings.WEBHOOK_SECRET
) -> bool:
    """Sends signed webhook notification to callback URL."""
    payload_str = json.dumps(job_data, sort_keys=True, default=str)
    payload_bytes = payload_str.encode("utf-8")
    signature = sign_payload(payload_bytes, secret)

    headers = {
        "Content-Type": "application/json",
        "X-IncuBrix-Signature": f"sha256={signature}"
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(callback_url, content=payload_bytes, headers=headers)
            logger.info(f"Webhook dispatched to {callback_url}: HTTP {resp.status_code}")
            return resp.status_code in (200, 201, 202, 204)
    except Exception as e:
        logger.warning(f"Failed to dispatch webhook to {callback_url}: {e}")
        return False

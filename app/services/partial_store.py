# partial_store.py — in-memory partial store (no Redis required)
import asyncio
import time

# { conversation_id: {"content": str, "updated_at": float} }
_partial_store: dict = {}
_lock = asyncio.Lock()

# Auto-cleanup entries older than this (seconds)
TTL_SECONDS = 3600


async def save_partial(conversation_id: str, content: str, ttl_seconds: int = TTL_SECONDS):
    """Save partial streamed response in memory."""
    async with _lock:
        _partial_store[conversation_id] = {
            "content": content,
            "updated_at": time.time(),
            "ttl": ttl_seconds,
        }


async def get_partial(conversation_id: str) -> str | None:
    """Retrieve a partial response from memory."""
    async with _lock:
        entry = _partial_store.get(conversation_id)
        if entry:
            # Check if expired
            if time.time() - entry["updated_at"] < entry["ttl"]:
                return entry["content"]
            else:
                del _partial_store[conversation_id]
    return None


async def delete_partial(conversation_id: str):
    """Remove partial response after final persist is complete."""
    async with _lock:
        _partial_store.pop(conversation_id, None)


async def cleanup_expired():
    """Optional: call this periodically to free memory from old entries."""
    now = time.time()
    async with _lock:
        expired = [
            k for k, v in _partial_store.items()
            if now - v["updated_at"] >= v["ttl"]
        ]
        for k in expired:
            del _partial_store[k]
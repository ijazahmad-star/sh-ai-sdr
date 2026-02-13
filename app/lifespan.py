from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres import PostgresSaver
from app.core.config import SUPABASE_DB_URI

# Global checkpointer
checkpointer = None

@asynccontextmanager
async def lifespan(app):
    global checkpointer
    # Initialize checkpointer
    async_checkpointer = PostgresSaver.from_conn_string(SUPABASE_DB_URI)
    with async_checkpointer as cp:
        checkpointer = cp
        checkpointer.setup()
        yield
    # Connection closes when context manager exits
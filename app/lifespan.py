# from contextlib import asynccontextmanager
# from langgraph.checkpoint.postgres import PostgresSaver
# from app.core.config import SUPABASE_DB_URI

# # Global checkpointer
# checkpointer = None

# @asynccontextmanager
# async def lifespan(app):
#     global checkpointer
#     # Initialize checkpointer
#     async_checkpointer = PostgresSaver.from_conn_string(SUPABASE_DB_URI)
#     with async_checkpointer as cp:
#         checkpointer = cp
#         checkpointer.setup()
#         yield
#     # Connection closes when context manager exits
from contextlib import asynccontextmanager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from app.core.config import SUPABASE_DB_URI

# Global pool and checkpointer
pool = None
checkpointer = None

@asynccontextmanager
async def lifespan(app):
    global pool, checkpointer
    
    # Use AsyncConnectionPool as a context manager to handle opening and closing
    async with AsyncConnectionPool(conninfo=SUPABASE_DB_URI, max_size=20) as p:
        pool = p
        
        # Initialize the ASYNC checkpointer
        checkpointer = AsyncPostgresSaver(pool)
        
        # Run setup to create necessary tables if they don't exist
        await checkpointer.setup()
        
        yield
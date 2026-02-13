import os
from supabase import create_client
from sentence_transformers import CrossEncoder
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_API_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
SUPABASE_DB_URI = os.getenv("SUPABASE_DB_URI")

cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
embeddings = OpenAIEmbeddings()

PDF_DIR = "/home/hp/Desktop/Workplace/CustomizeGPT/data"

WEB_URLS = [
    "https://strategisthub.com/services/",
    "https://strategisthub.com/about/",
    "https://strategisthub.com/case-studies/",
    "https://strategisthub.com/blogs/",
]

WEAVIATE_URL = os.getenv("WEAVIATE_URL")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")

from langchain_core.messages import HumanMessage, AIMessage
MEMORY_TABLE = "user_memories"  # make sure this table exists in Supabase

def save_memory(user_id: str, text: str):
    supabase.table(MEMORY_TABLE).insert({
        "user_id": user_id,
        "memory_text": text
    }).execute()

def load_memories(user_id: str):
    result = supabase.table(MEMORY_TABLE).select("*").eq("user_id", user_id).execute()
    return [r["memory_text"] for r in result.data]

def to_lc_messages(raw_messages):

    print("Converting into langchain format...")
    converted = []
    for m in raw_messages:
        if m["role"] == "user":
            converted.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            converted.append(AIMessage(content=m["content"]))
    return converted
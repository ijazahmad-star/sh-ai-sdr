import os
from supabase import create_client
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from dotenv import load_dotenv
load_dotenv()
# Ijaz@123-ahmad

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

if not SUPABASE_URL:
    raise ValueError("Missing SUPABASE_URL")

if not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_KEY in environment variables")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
embeddings = OpenAIEmbeddings()

def clean_metadata(docs):
    cleaned_docs = []
    for doc in docs:
        meta = doc.metadata or {}
        doc.metadata = {k: str(v) for k, v in meta.items() if v}
        cleaned_docs.append(doc)
    return cleaned_docs

def create_or_load_vectorstore(docs=None):
    table_name = "documents"
    if docs:
        docs = clean_metadata(docs)
        vectorstore = SupabaseVectorStore.from_documents(
            docs,
            embeddings,
            client=supabase,
            table_name=table_name,
        )
        print(f"Inserted {len(docs)} documents into Supabase.")
    else:
        vectorstore = SupabaseVectorStore(
            embedding=embeddings,
            client=supabase,
            table_name=table_name,
        )
        print("oaded existing Supabase vector store.")
    return vectorstore.as_retriever(search_kwargs={"k": 3})

def load_vectorstore():
    table_name = "documents"
    vectorstore = SupabaseVectorStore(
        embedding=embeddings,
        client=supabase,
        table_name=table_name,
    )
    print("Supabase vector store loaded successfully.")
    return vectorstore.as_retriever(search_kwargs={"k": 3})

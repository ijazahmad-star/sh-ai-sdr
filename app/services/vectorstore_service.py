import os
from supabase import create_client
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import (supabase, embeddings)

def clean_metadata(docs):
    cleaned_docs = []
    for doc in docs:
        meta = doc.metadata or {}
        doc.metadata = {k: str(v) for k, v in meta.items() if v}
        cleaned_docs.append(doc)
    return cleaned_docs

def create_or_load_vectorstore(docs=None, user_id: str = None):
    """
    Create or load vectorstore
    - user_id = None → default/shared KB
    - user_id = str → user-specific KB
    """
    table_name = "documents"

    if docs:
        # Split documents into chunks
        print("Splitting docs...")
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=200,
            chunk_overlap=50
        )
        chunks = text_splitter.split_documents(docs)

        # Add user_id to metadata of each chunk
        for chunk in chunks:
            chunk.metadata["user_id"] = user_id  # can be None for shared KB

        # Prepare data for direct insertion
        print("Rows...")
        rows_to_insert = []
        for chunk in chunks:
            rows_to_insert.append({
                "content": chunk.page_content,
                "metadata": chunk.metadata,
                "embedding": embeddings.embed_documents([chunk.page_content])[0],
                "user_id": user_id
            })

        # Insert into Supabase
        print("Starting storing...")
        res = supabase.table(table_name).insert(rows_to_insert).execute()

        print(f"Inserted {len(chunks)} documents into Supabase for user_id={user_id}")

        # Create vectorstore from inserted documents
        vectorstore = SupabaseVectorStore(
            embedding=embeddings,
            client=supabase,
            table_name=table_name,
        )

    else:
        # Just load existing vectorstore
        vectorstore = SupabaseVectorStore(
            embedding=embeddings,
            client=supabase,
            table_name=table_name,
        )
        print("Loaded existing Supabase vector store.")

    return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})

def get_vectorstore(docs=None):
    table_name = "documents"
    vectorstore = SupabaseVectorStore(
        embedding=embeddings,
        client=supabase,
        table_name=table_name,
    )
    print("Supabase vector store loaded successfully.")
    return vectorstore


def load_vectorstore():
    table_name = "documents"
    vectorstore = SupabaseVectorStore(
        embedding=embeddings,
        client=supabase,
        table_name=table_name,
    )
    print("Supabase vector store loaded successfully.")
    return vectorstore



def add_prompt(name: str, prompt: str, user_id: str):
    existing = (
        supabase.table("prompts")
        .select("id")
        .eq("name", name)
        .eq("user_id", user_id)
        .execute()
        
    )

    if existing.data:
        return {"error": f"Prompt '{name}' already exists for this user."}

    res = (
        supabase.table("prompts")
        .insert({"name": name, "prompt": prompt, "user_id": user_id})
        .execute()
    )

    return {"message": f"Prompt '{name}' added successfully.", "data": res.data}

def get_prompts(user_id: str):
    res = (
        supabase.table("prompts")
        .select("id, name, prompt, is_active")
        .eq("user_id", user_id)
        .execute()
    )
    return {"prompts": res.data or []}



def edit_prompt(old_name: str, new_prompt: str, user_id: str):
    existing = (
        supabase.table("prompts")
        .select("id")
        .eq("name", old_name)
        .eq("user_id", user_id)
        .execute()
    )

    if not existing.data:
        return {"error": f"Prompt '{old_name}' not found for this user."}

    update_data = {"prompt": new_prompt}

    res = (
        supabase.table("prompts")
        .update(update_data)
        .eq("name", old_name)
        .eq("user_id", user_id)
        .execute()
    )

    return {"message": f"Prompt '{old_name}' updated successfully.", "data": res.data}



def delete_prompt(name: str, user_id: str):
    existing = (
        supabase.table("prompts")
        .select("id")
        .eq("name", name)
        .eq("user_id", user_id)
        .execute()
    )

    if not existing.data:
        return {"error": f"Prompt '{name}' not found for this user."}

    supabase.table("prompts").delete().eq("name", name).eq("user_id", user_id).execute()

    return {"message": f"Prompt '{name}' deleted successfully."}



def set_active_prompt(name: str, user_id: str):
    supabase.table("prompts").update({"is_active": False}).eq("user_id", user_id).execute()

    target = (
        supabase.table("prompts")
        .update({"is_active": True})
        .eq("name", name)
        .eq("user_id", user_id)
        .execute()
    )

    if not target.data:
        return {"error": f"Prompt '{name}' not found for this user."}

    return {"message": f"Prompt '{name}' set as active."}



def get_active_prompt(user_id: str):
    res = (
        supabase.table("prompts")
        .select("name, prompt")
        .eq("is_active", True)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    if not res.data:
        return {"error": "No active prompt found."}

    return {"active_prompt": res.data[0]}

def log_model_usage(user_id: str, model_name: str, input_tokens: int, output_tokens: int, query: str = None, ai_response: str = None):
    """Log model usage to the database"""
    from app.utils.helpers import calculate_cost
    try:
        user_res = supabase.table("users").select("name, department, organization").eq("id", user_id).single().execute()
        user_data = user_res.data if user_res.data else {}
        
        estimated_cost = calculate_cost(model_name, input_tokens, output_tokens)
        
        supabase.table("user_model_usage").insert({
            "user_id": user_id,
            "user_name": user_data.get("name"),
            "department": user_data.get("department"),
            "organization": user_data.get("organization"),
            "model_name": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "user_query": query,
            "ai_response": ai_response
        }).execute()
    except Exception as e:
        print(f"Error logging model usage: {e}")


def check_user_has_documents(user_id: str) -> bool:
    """Check if user has their own KB"""
    response = supabase.table("documents").select("id").eq("user_id", user_id).limit(1).execute()
    return len(response.data) > 0

def check_user_has_access_to_default(user_id: str)-> bool:
    """
    Docstring for check_user_has_access_to_default
    
    :param user_id: Description
    :type user_id: str
    :return: Description
    :rtype: bool
    """
    response = supabase.table("kb_accesses").select("has_access_to_default_kb").eq("user_id", user_id).execute()
    if response.data and response.data[0]["has_access_to_default_kb"]:
        return True
    else:
        return False

def get_admin_user_id():
    """
    Docstring for get_admin_user_id
    """
    res = supabase.table("users").select("id").eq("role", "admin").single().execute()

    return res.data["id"]

def fetch_conversation_messages(conversation_id: str, limit: int = 10):
    print("fetching current conversations last 10 messages...")
    try:
        response = (
        supabase
        .table("messages")
        .select("role, content")
        .eq("conversationId", conversation_id)
        .order("createdAt", desc=False)
        .limit(limit)
        .execute()
    )
    except ValueError as  e:
        print("Error invalid.. Something", e)

    return [{"role": row["role"], "content": row["content"]} for row in response.data]

import os
from supabase import create_client
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
load_dotenv()

# create table public.documents (
#   id uuid not null default gen_random_uuid (),
#   content text null,
#   metadata jsonb null,
#   embedding public.vector null,
#   constraint documents_pkey primary key (id)
# ) TABLESPACE pg_default;

# create table public.prompts (
#   id uuid not null default gen_random_uuid (),
#   name text not null,
#   prompt text not null,
#   is_active boolean null default false,
#   constraint prompts_pkey primary key (id),
#   constraint prompts_name_key unique (name)
# ) TABLESPACE pg_default;


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

if not SUPABASE_URL:
    raise ValueError("Missing SUPABASE_URL")
if not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
embeddings = OpenAIEmbeddings()

def clean_metadata(docs):
    cleaned_docs = []
    for doc in docs:
        meta = doc.metadata or {}
        doc.metadata = {k: str(v) for k, v in meta.items() if v}
        cleaned_docs.append(doc)
    return cleaned_docs

# def create_or_load_vectorstore(docs=None):
#     table_name = "documents"
#     if docs:
#         # docs = clean_metadata(docs)
#         text_splitter = RecursiveCharacterTextSplitter(
#             chunk_size=500, chunk_overlap=50
#             )
#         docs = text_splitter.split_documents(docs)
#         vectorstore = SupabaseVectorStore.from_documents(
#             docs,
#             embeddings,
#             client=supabase,
#             table_name=table_name,
#         )
#         print(f"Inserted {len(docs)} documents into Supabase.")
#     else:
#         vectorstore = SupabaseVectorStore(
#             embedding=embeddings,
#             client=supabase,
#             table_name=table_name,
#         )
#         print("Loaded existing Supabase vector store.")
#     return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})

# def create_or_load_vectorstore(docs=None, user_id: str = None):
#     """
#     Create or load vectorstore
#     user_id = None means default KB (shared)
#     user_id = str means user-specific KB
#     """
#     table_name = "documents"
    
#     if docs:
#         text_splitter = RecursiveCharacterTextSplitter(
#             chunk_size=500, 
#             chunk_overlap=50
#         )
#         chunks = text_splitter.split_documents(docs)
        
#         # Add user_id to metadata of each chunk
#         for chunk in chunks:
#             if user_id:
#                 chunk.metadata["user_id"] = user_id
        
#         vectorstore = SupabaseVectorStore.from_documents(
#             chunks,
#             embeddings,
#             client=supabase,
#             table_name=table_name,
#         )
        
#         # Manually update user_id in database (langchain doesn't handle custom columns)
#         if user_id:
#             # Get recently inserted documents and update user_id
#             response = supabase.table(table_name)\
#                 .select("id")\
#                 .is_("user_id", "null")\
#                 .order("id", desc=True)\
#                 .limit(len(chunks))\
#                 .execute()
            
#             for doc in response.data:
#                 supabase.table(table_name)\
#                     .update({"user_id": user_id})\
#                     .eq("id", doc["id"])\
#                     .execute()
        
#         print(f"Inserted {len(chunks)} documents into Supabase for user_id={user_id}")
#     else:
#         vectorstore = SupabaseVectorStore(
#             embedding=embeddings,
#             client=supabase,
#             table_name=table_name,
#         )
#         print("Loaded existing Supabase vector store.")
    
#     return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})
def create_or_load_vectorstore(docs=None, user_id: str = None):
    """
    Create or load vectorstore
    - user_id = None → default/shared KB
    - user_id = str → user-specific KB
    """
    table_name = "documents"

    if docs:
        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )
        chunks = text_splitter.split_documents(docs)

        # Add user_id to metadata of each chunk
        for chunk in chunks:
            chunk.metadata["user_id"] = user_id  # can be None for shared KB

        # Prepare data for direct insertion
        rows_to_insert = []
        for chunk in chunks:
            rows_to_insert.append({
                "content": chunk.page_content,
                "metadata": chunk.metadata,
                "embedding": embeddings.embed_documents([chunk.page_content])[0],
                "user_id": user_id
            })

        # Insert into Supabase
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


# def add_prompt(name: str, prompt: str):
#     existing = supabase.table("prompts").select("id").eq("name", name).execute()
#     if existing.data:
#         return {"error": f"Prompt '{name}' already exists."}
#     res = supabase.table("prompts").insert({"name": name, "prompt": prompt}).execute()
#     return {"message": f"Prompt '{name}' added successfully.", "data": res.data}
# def get_prompts():
#     res = supabase.table("prompts").select("id, name, prompt, is_active").execute()
#     return {"prompts": res.data or []}
# def edit_prompt(old_name: str, new_name: str = None, new_prompt: str = None):
#     existing = supabase.table("prompts").select("id").eq("name", old_name).execute()
#     if not existing.data:
#         return {"error": f"Prompt '{old_name}' not found."}
#     update_data = {}
#     if new_name:
#         update_data["name"] = new_name
#     if new_prompt:
#         update_data["prompt"] = new_prompt
#     res = supabase.table("prompts").update(update_data).eq("name", old_name).execute()
#     return {"message": f"Prompt '{old_name}' updated successfully.", "data": res.data}

# def edit_prompt(old_name: str, new_prompt: str = None):
#     existing = supabase.table("prompts").select("id").eq("name", old_name).execute()
#     if not existing.data:
#         return {"error": f"Prompt '{old_name}' not found."}
#     update_data = {}
#     if new_prompt:
#         update_data["prompt"] = new_prompt
#     res = supabase.table("prompts").update(update_data).eq("name", old_name).execute()
#     return {"message": f"Prompt '{old_name}' updated successfully.", "data": res.data}
# def delete_prompt(name: str):
#     existing = supabase.table("prompts").select("id").eq("name", name).execute()
#     if not existing.data:
#         return {"error": f"Prompt '{name}' not found."}
#     res = supabase.table("prompts").delete().eq("name", name).execute()
#     return {"message": f"Prompt '{name}' deleted successfully."}
# def set_active_prompt(name: str):
#     supabase.table("prompts").update({"is_active": False}).neq("name", name).execute()
#     target = supabase.table("prompts").update({"is_active": True}).eq("name", name).execute()
#     if not target.data:
#         return {"error": f"Prompt '{name}' not found."}
#     return {"message": f"Prompt '{name}' set as active."}

# def get_active_prompt():
#     res = supabase.table("prompts").select("name, prompt").eq("is_active", True).limit(1).execute()
#     if not res.data:
#         return {"error": "No active prompt found."}
#     return {"active_prompt": res.data[0]}


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


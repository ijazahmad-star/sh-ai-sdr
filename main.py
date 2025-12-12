from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.documents import Document
from app.config import PDF_DIR
from app.data_loader import read_uploaded_file, clean_text, clean_metadata
from app.tools import create_retriever_tool, check_user_has_documents, check_user_has_access_to_default
from app.graph_builder import build_workflow
import os
import uvicorn
import warnings
import uuid
from supabase import create_client
from dotenv import load_dotenv

from app.schema import (
    QueryRequest,
    PromptRequest,
    EditPromptRequest,
)

from app.vectorstore_supabase import (
    create_or_load_vectorstore,
    add_prompt,
    get_prompts,
    edit_prompt,
    delete_prompt,
    set_active_prompt,
    get_active_prompt,
)

warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_API_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


app = FastAPI(title="Strategisthub Email Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.post("/query")
async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB"""
    
    # Get active prompt
    active_prompt_data = get_active_prompt(request.user_id)
    if not active_prompt_data or "active_prompt" not in active_prompt_data:
        raise HTTPException(status_code=404, detail="No active prompt found for this user.")
    
    system_prompt = active_prompt_data["active_prompt"]["prompt"]
    
    # Determine which KB to use based on kb_type parameter
    use_user_kb = False
    if request.kb_type == "custom":
        use_user_kb = True
    
    tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
    
    graph = build_workflow(tools, system_prompt)
    config = {"configurable": {"thread_id": "1"}}
    result = graph.invoke({"messages": request.query}, config=config)
    messages = result["messages"]
    
    final_ai_msg = None
    for msg in messages:
        if msg.__class__.__name__ == "AIMessage" and msg.content:
            final_ai_msg = msg.content
    
    sources = []
    for msg in messages:
        if msg.__class__.__name__ == "ToolMessage":
            if hasattr(msg, "artifact") and msg.artifact:
                for item in msg.artifact:
                    sources.append({
                        "source": item["metadata"].get("source"),
                        "content": item["page_content"],
                        "rerank_score": item.get("rerank_score")
                    })
    
    # Deduplicate and sort sources
    unique = {}
    for s in sources:
        key = s["source"]
        if key not in unique:
            unique[key] = s
    
    sources = list(unique.values())
    sources = sorted(sources, key=lambda x: x.get("rerank_score", 0), reverse=True)
    
    return {
        "response": final_ai_msg,
        "sources": sources
    }

# @app.post("/upload_user_document")
# async def upload_user_document(
#     file: UploadFile = File(...),
#     user_id: str = Form(...)
# ):
#     """Upload document to user-specific KB"""
#     try:
#         print("Reading file...")
#         file_content = await file.read()
#         temp_path = f"/tmp/{file.filename}"
        
#         print("Opening file...")
#         with open(temp_path, "wb") as temp_file:
#             temp_file.write(file_content)
        
#         print("Preprocessing file...")
#         content = read_uploaded_file(temp_path)
#         content = clean_text(content)
#         metadata = clean_metadata({"source": file.filename, "user_id": user_id})
        
#         doc = Document(
#             page_content=content,
#             # metadata={"source": file.filename}
#             metadata=metadata
#         )
        
#         print("Storing file...")
#         create_or_load_vectorstore([doc], user_id=user_id)
        
#         os.remove(temp_path)
        
#         print("Successfully store file...!")
#         return {
#             "status": "success",
#             "filename": file.filename,
#             "user_id": user_id
#         }
    
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_user_document")
async def upload_user_document(
    file: UploadFile = File(...),
    user_id: str = Form(...)
):
    try:
        content = await file.read()

        file_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{file_id}-{file.filename}"

        supabase.storage.from_("user_documents").upload(
            storage_path,
            content,
            {"content-type": file.content_type},
        )

        supabase.table("user_files").insert({
            "user_id": user_id,
            "filename": file.filename,
            "storage_path": storage_path
        }).execute()

        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(content)

        text = read_uploaded_file(temp_path)
        text = clean_text(text)

        doc = Document(
            page_content=text,
            metadata={"source": file.filename, "user_id": user_id}
        )

        create_or_load_vectorstore([doc], user_id=user_id)

        os.remove(temp_path)

        return {"status": "success", "file": file.filename}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/get_user_documents/{user_id}")
def get_user_documents(user_id: str):
    res = supabase.table("user_files").select("*").eq("user_id", user_id).execute()
    return {"documents": res.data}

@app.get("/download_user_document/{file_id}")
def download_user_document(file_id: str, user_id: str):
    record = supabase.table("user_files").select("*").eq("id", file_id).execute()

    if not record.data or len(record.data) == 0:
        raise HTTPException(status_code=404, detail="File not found")

    file = record.data[0]

    if file["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    url = supabase.storage.from_("user_documents").create_signed_url(file["storage_path"], 60)

    return {"download_url": url["signedUrl"]}



@app.delete("/delete_user_document/{file_id}")
def delete_user_document(file_id: str, user_id: str):
    record = supabase.table("user_files").select("*").eq("id", file_id).execute()

    if not record.data or len(record.data) == 0:
        raise HTTPException(status_code=404, detail="File not found")

    file = record.data[0]

    if file["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # Remove the file from Supabase Storage
    supabase.storage.from_("user_documents").remove([file["storage_path"]])

    # Delete all related chunks in documents table
    supabase.table("documents").delete().match({
        "metadata->>source": file["filename"],
        "user_id": user_id
    }).execute()

    # Delete the record from user_files table
    supabase.table("user_files").delete().eq("id", file_id).execute()

    return {"status": "deleted"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload document to DEFAULT KB (for admin use)"""
    try:
        file_content = await file.read()
        temp_path = f"/tmp/{file.filename}"
        
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)
        
        content = read_uploaded_file(temp_path)
        doc = Document(page_content=content, metadata={"source": file.filename})
        
        # Store in default KB (user_id = None)
        create_or_load_vectorstore([doc], user_id=None)
        
        os.remove(temp_path)
        
        return {"status": "success", "filename": file.filename}
    
    except Exception as e:
        return {"status": "failed", "error": str(e)}

@app.get("/get_user_documents/{user_id}")
async def get_user_documents(user_id: str):
    """Get all documents for a specific user"""
    try:
        response = supabase.table("documents").select("id, metadata, user_id").eq("user_id", user_id).execute()
        
        documents = []
        for doc in response.data:
            metadata = doc.get("metadata", {})
            documents.append({
                "id": doc["id"],
                "filename": metadata.get("source", "Unknown"),
                "metadata": metadata,
                "createdAt": metadata.get("created_at", None)
            })
        
        return {"documents": documents}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete_user_document/{user_id}/{document_id}")
async def delete_user_document(user_id: str, document_id: str):
    """Delete a user's document"""
    try:
        # Verify document belongs to user
        check = supabase.table("documents").select("id").eq("id", document_id).eq("user_id", user_id).execute()
        
        if not check.data:
            raise HTTPException(status_code=404, detail="Document not found or doesn't belong to user")
        
        # Delete document
        supabase.table("documents").delete().eq("id", document_id).execute()
        
        return {"status": "success", "message": "Document deleted"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.delete("/admin/delete_user/{target_user_id}")
def admin_delete_user(target_user_id: str):
    
    files = supabase.table("user_files").select("*").eq("user_id", target_user_id).execute().data

    if files:
        storage_paths = [f["storage_path"] for f in files]
        supabase.storage.from_("user_documents").remove(storage_paths)
        for f in files:
            supabase.table("documents").delete().match({
                "metadata->>source": f["filename"],
                "user_id": target_user_id
            }).execute()

        supabase.table("user_files").delete().eq("user_id", target_user_id).execute()

    return {"status": "deleted", "files_deleted": len(files)}

@app.get("/check_user_kb/{user_id}")
async def check_user_kb(user_id: str):
    """Check if user has their own KB"""
    has_kb = check_user_has_documents(user_id)
    return {"has_personal_kb": has_kb}

@app.get("/check_user_has_access_to_default_kb/{user_id}")
def checkAccessToDefault(user_id: str):
    hasAccess = check_user_has_access_to_default(user_id)
    return {"has_access_to_default": hasAccess}

@app.post("/add_prompt")
def add_prompt_endpoint(request: PromptRequest):
    result = add_prompt(request.name, request.prompt, request.user_id)
    return {"status": "success", "result": result}

@app.get("/get_prompts/{user_id}")
def get_prompts_endpoint(user_id: str):
    return get_prompts(user_id)

@app.put("/edit_prompt")
def edit_prompt_endpoint(request: EditPromptRequest):
    return edit_prompt(request.old_name, request.new_prompt, request.user_id)

@app.delete("/delete_prompt/{user_id}/{name}")
def delete_prompt_endpoint(user_id: str, name: str):
    return delete_prompt(name, user_id)

@app.post("/set_active_prompt/{user_id}/{name}")
def set_active_prompt_endpoint(user_id: str, name: str):
    return set_active_prompt(name, user_id)

@app.get("/get_active_prompt/{user_id}")
def get_active_prompt_endpoint(user_id: str):
    return get_active_prompt(user_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase_auth import datetime
from langchain_core.documents import Document
# from pydantic import BaseModel
from app.schema import (
    QueryRequest,
    PromptRequest,
    EditPromptRequest,
    UploadRequest,
)
from pathlib import Path
import json, shutil
import uvicorn
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from app.config import PDF_DIR
from app.data_loader import read_uploaded_file, clean_text, clean_metadata
from app.tools import create_retriever_tool, check_user_has_documents
from app.graph_builder import build_workflow
import os
# from app.vectorstore_weaviate import create_or_load_vectorstore, load_vectorstore
from app.vectorstore_supabase import (
    create_or_load_vectorstore,
    load_vectorstore,
    add_prompt,
    get_prompts,
    edit_prompt,
    delete_prompt,
    set_active_prompt,
    get_active_prompt,
)

import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")

if not SUPABASE_URL:
    raise ValueError("Missing SUPABASE_URL")
if not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_API_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


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
    
    # Create retriever tool with user-specific or default KB
    tools = create_retriever_tool(user_id=request.user_id)
    
    # Build and invoke workflow
    graph = build_workflow(tools, system_prompt)
    config = {"configurable": {"thread_id": "1"}}
    result = graph.invoke({"messages": request.query}, config=config)
    messages = result["messages"]
    
    # Extract AI response
    final_ai_msg = None
    for msg in messages:
        if msg.__class__.__name__ == "AIMessage" and msg.content:
            final_ai_msg = msg.content
    
    # Extract sources
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
    
    # print("Sources:", sources)
    
    return {
        "response": final_ai_msg,
        "sources": sources
    }

@app.post("/upload_user_document")
async def upload_user_document(
    file: UploadFile = File(...),
    user_id: str = Form(...)
):
    """Upload document to user-specific KB"""
    try:
        # Read file content
        file_content = await file.read()
        temp_path = f"/tmp/{file.filename}"
        
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)
        
        # Extract text content
        content = read_uploaded_file(temp_path)
        content = clean_text(content)
        metadata = clean_metadata({"source": file.filename, "user_id": user_id})
        
        # Create document with metadata
        doc = Document(
            page_content=content,
            # metadata={"source": file.filename}
            metadata=metadata
        )
        
        # Store in vectorstore with user_id
        create_or_load_vectorstore([doc], user_id=user_id)
        
        # Clean up temp file
        os.remove(temp_path)
        
        return {
            "status": "success",
            "filename": file.filename,
            "user_id": user_id
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        response = supabase.table("documents")\
            .select("id, metadata, user_id")\
            .eq("user_id", user_id)\
            .execute()
        
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
        check = supabase.table("documents")\
            .select("id")\
            .eq("id", document_id)\
            .eq("user_id", user_id)\
            .execute()
        
        if not check.data:
            raise HTTPException(status_code=404, detail="Document not found or doesn't belong to user")
        
        # Delete document
        supabase.table("documents")\
            .delete()\
            .eq("id", document_id)\
            .execute()
        
        return {"status": "success", "message": "Document deleted"}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/check_user_kb/{user_id}")
async def check_user_kb(user_id: str):
    """Check if user has their own KB"""
    has_kb = check_user_has_documents(user_id)
    return {"has_personal_kb": has_kb}


# @app.post("/query")
# async def handle_query(request: QueryRequest):
#     active_prompt_data = get_active_prompt(request.user_id)
#     if not active_prompt_data or "active_prompt" not in active_prompt_data:
#         raise HTTPException(status_code=404, detail="No active prompt found for this user.")
    
#     system_prompt = active_prompt_data["active_prompt"]["prompt"]
#     tools = create_retriever_tool()
#     graph = build_workflow(tools, system_prompt)
#     config = {"configurable": {"thread_id": "1"}}

#     result = graph.invoke({"messages": request.query}, config=config)
#     messages = result["messages"]

#     final_ai_msg = None
#     for msg in messages:
#         if msg.__class__.__name__ == "AIMessage" and msg.content:
#             final_ai_msg = msg.content

#     sources = []
#     for msg in messages:
#         if msg.__class__.__name__ == "ToolMessage":
#             if hasattr(msg, "artifact") and msg.artifact:
#                 for item in msg.artifact:
#                     sources.append({
#                         "source": item["metadata"].get("source"),
#                         "content": item["page_content"],
#                         "rerank_score": item.get("rerank_score")
#                     })

#     unique = {}
#     for s in sources:
#         key = s["source"]
#         if key not in unique:
#             unique[key] = s

#     sources = list(unique.values())
#     sources = sorted(sources, key=lambda x: x.get("rerank_score", 0), reverse=True)

#     print("Sources:", sources)

#     return {
#         "response": final_ai_msg,
#         "sources": sources
#     }


# @app.post("/upload")
# async def upload_file(file: UploadFile = File(...)):
#     try:
#         file_content = await file.read()
#         temp_path = f"/tmp/{file.filename}"
#         with open(temp_path, "wb") as temp_file:
#             temp_file.write(file_content)

#         content = read_uploaded_file(temp_path)
#         doc = Document(page_content=content, metadata={"source": file.filename})

#         vectorstore = create_or_load_vectorstore([doc])
#         os.remove(temp_path)

#         return {"status": "success", "filename": file.filename}
#     except Exception as e:
#         return {"status": "failed", "error": str(e)}


# @app.post("/add_prompt")
# def add_prompt_endpoint(request: PromptRequest):
#     result = add_prompt(request.name, request.prompt)
#     return {"status": "success", "result": result}
#     # return add_prompt(request.name, request.prompt)

# @app.get("/get_prompts")
# def get_prompts_endpoint():
#     return get_prompts()

# # @app.put("/edit_prompt")
# # def edit_prompt_endpoint(request: EditPromptRequest):
# #     return edit_prompt(request.old_name, request.new_name, request.new_prompt)

# @app.put("/edit_prompt")
# def edit_prompt_endpoint(request: EditPromptRequest):
#     return edit_prompt(request.old_name, request.new_prompt)

# @app.delete("/delete_prompt/{name}")
# def delete_prompt_endpoint(name: str):
#     return delete_prompt(name)

# @app.post("/set_active_prompt/{name}")
# def set_active_prompt_endpoint(name: str):
#     return set_active_prompt(name)

# @app.get("/get_active_prompt")
# def get_active_prompt_endpoint():
#     return get_active_prompt()

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
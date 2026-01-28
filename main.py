from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import re
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from fastapi.middleware.cors import CORSMiddleware
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from app.config import PDF_DIR
from app.data_loader import read_uploaded_file, clean_text, clean_metadata
from app.tools import create_retriever_tool, check_user_has_documents, check_user_has_access_to_default
from app.graph_builder import build_workflow
import os
import uvicorn
import warnings
import uuid

from app.schema import (
    QueryRequest,
    PromptRequest,
    EditPromptRequest,
    PromptGenerationRequest,
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
from app.config import (
    supabase,SUPABASE_DB_URI,
)
warnings.filterwarnings("ignore", category=DeprecationWarning)
from langgraph.checkpoint.postgres import PostgresSaver 


app = FastAPI(title="Strategisthub Email Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# '''
# Get Answer from user-specific or default DB by AI
# Fetch active prompt for user
# If kb_type is "custom", use user-specific KB if exists, else default KB
# If kb_type is "default", always use default KB
# '''
@app.post("/query")
async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB"""
    print(f"received model name: {request.model}")
    # Get active prompt
    active_prompt_data = get_active_prompt(request.user_id)
    if (
        not active_prompt_data
        or "active_prompt" not in active_prompt_data
        or not active_prompt_data["active_prompt"]
    ):
        system_prompt = "You are a helpful assistant. Must call Tools"
    else:
        system_prompt = active_prompt_data["active_prompt"]["prompt"]

    use_user_kb = False
    if request.kb_type == "custom":
        use_user_kb = True
    
    tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
 
    with PostgresSaver.from_conn_string(SUPABASE_DB_URI) as checkpointer:  
        checkpointer.setup()
        graph = build_workflow(tools, system_prompt, checkpointer, request.model)
        config = {"configurable": {"thread_id": request.conversation_id}}
        result = graph.invoke({"messages": request.query}, config=config)
        # result = graph.invoke({"messages": messages}, config=config)
        messages = result["messages"]
        
        final_ai_msg = None
        final_msg_id = None
        for msg in messages:
            if msg.__class__.__name__ == "AIMessage" and msg.content:
                final_ai_msg = msg.content
                final_msg_id = msg.id
                # print("Final AI Message: ", msg.id)
        
        sources = []
        if request.kb_type == "custom":
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
            "sources": sources,
            "message_id": final_msg_id
        }

# '''
# Retrieve conversation history from Postgres checkpointer
# Format messages by cleaning content and attaching sources
# '''
@app.get("/conversations/{conversation_id}")
async def get_conversation_history(conversation_id: str):
    try:
        config = {"configurable": {"thread_id": conversation_id}}
        with PostgresSaver.from_conn_string(SUPABASE_DB_URI) as checkpointer:
            state = checkpointer.get_tuple(config)
            if not state:
                return {"thread_id": conversation_id, "messages": []}

            raw_messages = state.checkpoint.get("channel_values", {}).get("messages", [])
            formatted_messages = []
            current_turn_sources = []

            for msg in raw_messages:
                # --- ToolMessage: collect sources ---
                if isinstance(msg, ToolMessage):
                    if hasattr(msg, "artifact") and msg.artifact:
                        for item in msg.artifact:
                            metadata = item.get("metadata", {})
                            current_turn_sources.append({
                                "source": metadata.get("source", "Unknown"),
                                "rerank_score": item.get("rerank_score", 0),
                                "tool_message_id": getattr(msg, "id", None)
                            })
                    continue

                # --- HumanMessage or AIMessage ---
                if isinstance(msg, (HumanMessage, AIMessage)):
                    content = msg.content or ""
                    clean_text = re.split(r"Rerank Score:", content)[0].strip()
                    clean_text = re.sub(r"Source: \{.*?\}", "", clean_text).strip()
                    if not clean_text:
                        continue

                    sorted_sources = []
                    if isinstance(msg, AIMessage):
                        unique_sources = {}
                        for s in current_turn_sources:
                            name = s["source"]
                            if name not in unique_sources or s["rerank_score"] > unique_sources[name]["rerank_score"]:
                                unique_sources[name] = s
                        sorted_sources = sorted(unique_sources.values(), key=lambda x: x["rerank_score"], reverse=True)
                        current_turn_sources = []

                    formatted_messages.append({
                        "id": getattr(msg, "id", None),
                        "role": "user" if isinstance(msg, HumanMessage) else "assistant",
                        "content": clean_text,
                        "sources": sorted_sources
                    })
            # print(f"Retrieved {(formatted_messages)}")
            return {
                "thread_id": conversation_id,
                "messages": formatted_messages
            }

    except Exception as e:
        print(f"Error retrieving history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# '''
# Delete conversation history from Postgres checkpointer
# '''
@app.delete("/conversations/{conversation_id}")
async def delete_conversation_history(conversation_id: str):
    """
    Delete all stored history for a conversation (thread) in Postgres checkpointer.
    """
    try:
        with PostgresSaver.from_conn_string(SUPABASE_DB_URI) as checkpointer:
            # Remove all checkpointed state for this thread
            checkpointer.delete_thread(conversation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {str(e)}")

    return {"message": "Conversation history deleted successfully."}

# '''
# Upload user document, store in Supabase, 
# process and add to user-specific vectorstore
# '''
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
    
# '''
# Get list of user documents from Supabase
# '''
@app.get("/get_user_documents/{user_id}")
def get_user_documents(user_id: str):
    print(f"Fetching documents for user_id--------->: {user_id}")
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

# '''
# Delete user document from Supabase and 
# related entries from vectorstore
# '''
@app.delete("/delete_user_document/{file_id}")
def delete_user_document(file_id: str, user_id: str):
    print(f"Deleting file -----------> {file_id} for user {user_id}")
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


# @app.post("/upload")
# async def upload_file(file: UploadFile = File(...)):
#     """Upload document to DEFAULT KB (for admin use)"""
#     try:
#         file_content = await file.read()
#         temp_path = f"/tmp/{file.filename}"
        
#         with open(temp_path, "wb") as temp_file:
#             temp_file.write(file_content)
        
#         content = read_uploaded_file(temp_path)
#         doc = Document(page_content=content, metadata={"source": file.filename})
        
#         # Store in default KB (user_id = None)
#         create_or_load_vectorstore([doc], user_id=None)
        
#         os.remove(temp_path)
        
#         return {"status": "success", "filename": file.filename}
    
#     except Exception as e:
#         return {"status": "failed", "error": str(e)}


# '''
# Admin delete user and all its documents 
# from Supabase and vectorstore
# '''    
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

# '''
# Below all endpoints related to prompts for user
# '''
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

# '''
# Generate a system prompt based on user requirements using AI
# '''
@app.post("/generate_prompt")
def generate_prompt_endpoint(request: PromptGenerationRequest):
    try:
        # Initialize the LLM
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)

        # Create a comprehensive prompt generation system message
        system_prompt = """You are an expert AI prompt engineer. Your task is to create comprehensive, well-structured system prompts for AI assistants based on user requirements.

Given user requirements, generate a detailed system prompt that includes:
1. Clear role definition for the AI assistant
2. Specific behaviors and capabilities
3. Guidelines for interaction style and tone
4. Any domain-specific knowledge or constraints
5. Response formatting preferences if applicable

The generated prompt should be professional, actionable, and optimized for the specific use case described in the requirements.

Structure your response as a complete system prompt that can be directly used by an AI assistant."""

        # Create the user message with requirements
        user_message = f"Generate a comprehensive system prompt based on these requirements:\n\n{request.requirements}"

        # Generate the prompt using the LLM
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]

        response = llm.invoke(messages)

        generated_prompt = response.content.strip()

        return {
            "status": "success",
            "generated_prompt": generated_prompt,
            "user_id": request.user_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate prompt: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
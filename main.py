from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
import json
import re
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from fastapi.middleware.cors import CORSMiddleware
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from app.config import PDF_DIR
from app.data_loader import read_uploaded_file, clean_text, clean_metadata
from app.tools.tools import create_retriever_tool, check_user_has_documents, check_user_has_access_to_default
from app.tools.google_search_tool import search_google_tool
from app.graph_builder import build_workflow
import os
import uvicorn
import warnings
import uuid
import time
from typing import List, Union

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
from langgraph.checkpoint.postgres import PostgresSaver
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from contextlib import asynccontextmanager

# Global checkpointer
checkpointer = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global checkpointer
    # Initialize checkpointer
    async_checkpointer = PostgresSaver.from_conn_string(SUPABASE_DB_URI)
    with async_checkpointer as cp:
        checkpointer = cp
        checkpointer.setup()
        yield
    # Connection closes when context manager exits

app = FastAPI(title="Strategisthub Email Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    # Approximate pricing per 1M tokens
    pricing = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    
    # Default to gpt-4o-mini if not found
    model_key = "gpt-4o" if "gpt-4o" in model_name and "mini" not in model_name else "gpt-4o-mini"
    cost_config = pricing.get(model_key, pricing["gpt-4o-mini"])
    
    input_cost = (input_tokens / 1_000_000) * cost_config["input"]
    output_cost = (output_tokens / 1_000_000) * cost_config["output"]
    
    return input_cost + output_cost

@app.post("/query")
async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB (Optimized JSON Response)"""

    active_prompt_data = get_active_prompt(request.user_id)
    system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", "You are a helpful assistant. When using the database tool, retrieve all required information in a single call. Do not call the database tool multiple times. Plan what you need before calling it")

    use_user_kb = request.kb_type == "custom"
    tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
    tools.append(search_google_tool())
 
    graph = build_workflow(tools, system_prompt, checkpointer, request.model)
    config = {"configurable": {"thread_id": request.conversation_id}}
    
    start_time = time.time()
    result = graph.invoke({"messages": request.query}, config=config)
    end_time = time.time()
    print(f"Agent total response invoke time: {end_time - start_time:.2f} seconds")
    
    messages = result["messages"]
    final_ai_msg = ""
    final_msg_id = None
    sources = []
    
    total_input_tokens = 0
    total_output_tokens = 0

    for msg in messages:
        if msg.__class__.__name__ == "AIMessage":
            if msg.content:
                final_ai_msg = msg.content
                final_msg_id = msg.id
            
            # Extract usage metadata if available (LangChain >= 0.2 format)
            if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                total_input_tokens += msg.usage_metadata.get("input_tokens", 0)
                total_output_tokens += msg.usage_metadata.get("output_tokens", 0)
                print(f"Total input tokens: {total_input_tokens}, Total output tokens: {total_output_tokens}")
            # Fallback for some providers/older versions
            elif "token_usage" in msg.response_metadata:
                usage = msg.response_metadata["token_usage"]
                total_input_tokens += usage.get("prompt_tokens", 0)
                total_output_tokens += usage.get("completion_tokens", 0)
                print(f"(Callback)Total input tokens: {total_input_tokens}, Total output tokens: {total_output_tokens}")
        elif msg.__class__.__name__ == "ToolMessage" and use_user_kb:
            if hasattr(msg, "artifact") and msg.artifact:
                for item in msg.artifact:
                    sources.append({
                        "source": item["metadata"].get("source"),
                        "content": item["page_content"],
                        "rerank_score": item.get("rerank_score")
                    })

    # Log usage to database
    try:
        user_res = supabase.table("users").select("name, department, organization").eq("id", request.user_id).single().execute()
        user_data = user_res.data if user_res.data else {}
        
        estimated_cost = calculate_cost(request.model, total_input_tokens, total_output_tokens)
        
        supabase.table("user_model_usage").insert({
            "user_id": request.user_id,
            "user_name": user_data.get("name"),
            "department": user_data.get("department"),
            "organization": user_data.get("organization"),
            "model_name": request.model,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "estimated_cost": estimated_cost
        }).execute()
    except Exception as e:
        print(f"Error logging model usage: {e}")

    if sources:
        unique = {s["source"]: s for s in sources}
        sources = sorted(unique.values(), key=lambda x: x.get("rerank_score", 0), reverse=True)

    return {
        "response": final_ai_msg,
        "sources": sources,
        "message_id": final_msg_id
    }

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


@app.post("/upload_user_document")
async def upload_user_document(
    file: Union[UploadFile, List[UploadFile]] = File(...),
    user_id: str = Form(...)
):
    successful_uploads = []
    failed_uploads = []
    documents = []
    
    try:
        # Handle both single file and multiple files dynamically
        files_to_process = file if isinstance(file, list) else [file]
        
        for current_file in files_to_process:
            try:
                content = await current_file.read()

                file_id = str(uuid.uuid4())
                storage_path = f"{user_id}/{file_id}-{current_file.filename}"

                supabase.storage.from_("user_documents").upload(
                    storage_path,
                    content,
                    {"content-type": current_file.content_type},
                )

                supabase.table("user_files").insert({
                    "user_id": user_id,
                    "filename": current_file.filename,
                    "storage_path": storage_path
                }).execute()

                temp_path = f"/tmp/{current_file.filename}"
                with open(temp_path, "wb") as f:
                    f.write(content)

                text = read_uploaded_file(temp_path)
                text = clean_text(text)

                doc = Document(
                    page_content=text,
                    metadata={"source": current_file.filename, "user_id": user_id}
                )
                documents.append(doc)

                os.remove(temp_path)
                successful_uploads.append(current_file.filename)

            except Exception as file_error:
                failed_uploads.append({"filename": current_file.filename, "error": str(file_error)})
                continue

        # Batch add all documents to vectorstore
        if documents:
            create_or_load_vectorstore(documents, user_id=user_id)

        return {
            "status": "completed",
            "successful_uploads": successful_uploads,
            "failed_uploads": failed_uploads,
            "total_processed": len(successful_uploads),
            "total_failed": len(failed_uploads)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
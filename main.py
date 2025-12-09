from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase_auth import datetime
from langchain_core.documents import Document
# from pydantic import BaseModel
from app.schema import (
    QueryRequest,
    PromptRequest,
    EditPromptRequest,
)
from pathlib import Path
import json, shutil
import uvicorn
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from app.config import PDF_DIR
from app.data_loader import read_uploaded_file
from app.tools import create_retriever_tool
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


app = FastAPI(title="Strategisthub Email Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# class QueryRequest(BaseModel):
#     query: str

# class PromptRequest(BaseModel):
#     name: str
#     prompt: str

# class EditPromptRequest(BaseModel):
#     old_name: str
#     new_name: str = None
#     new_prompt: str = None


# @app.post("/query")
# async def handle_query(request: QueryRequest):
#     active_prompt_data = get_active_prompt()
#     if not active_prompt_data or "active_prompt" not in active_prompt_data:
#         raise HTTPException(status_code=404, detail="No active prompt found.")

#     system_prompt = active_prompt_data["active_prompt"]["prompt"]
#     tools = create_retriever_tool()
#     graph = build_workflow(tools, system_prompt)
#     config = {"configurable": {"thread_id": "1"}}
#     response = graph.invoke({"messages": request.query}, config=config)
#     return {"response": response["messages"][-1].content}

# @app.post("/query")
# async def handle_query(request: QueryRequest):
#     active_prompt_data = get_active_prompt()
#     if not active_prompt_data or "active_prompt" not in active_prompt_data:
#         raise HTTPException(status_code=404, detail="No active prompt found.")
    
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

@app.post("/query")
async def handle_query(request: QueryRequest):
    active_prompt_data = get_active_prompt(request.user_id)
    if not active_prompt_data or "active_prompt" not in active_prompt_data:
        raise HTTPException(status_code=404, detail="No active prompt found for this user.")
    
    system_prompt = active_prompt_data["active_prompt"]["prompt"]
    tools = create_retriever_tool()
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

    unique = {}
    for s in sources:
        key = s["source"]
        if key not in unique:
            unique[key] = s

    sources = list(unique.values())
    sources = sorted(sources, key=lambda x: x.get("rerank_score", 0), reverse=True)

    print("Sources:", sources)

    return {
        "response": final_ai_msg,
        "sources": sources
    }


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_content = await file.read()
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)

        content = read_uploaded_file(temp_path)
        doc = Document(page_content=content, metadata={"source": file.filename})

        vectorstore = create_or_load_vectorstore([doc])
        os.remove(temp_path)

        return {"status": "success", "filename": file.filename}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


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
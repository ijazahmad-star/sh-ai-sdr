from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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


@app.post("/query")
async def handle_query(request: QueryRequest):

    active_prompt_data = get_active_prompt()
    if not active_prompt_data or "active_prompt" not in active_prompt_data:
        raise HTTPException(status_code=404, detail="No active prompt found.")

    system_prompt = active_prompt_data["active_prompt"]["prompt"]

    retriever = load_vectorstore()
    tools = create_retriever_tool(retriever)
    graph = build_workflow(tools, system_prompt)
    config = {"configurable": {"thread_id": "1"}}

    response = graph.invoke({"messages": request.query}, config=config)
    return {"response": response["messages"][-1].content}

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

# async def upload_file(file: UploadFile = File(...)):
#     save_path = Path(PDF_DIR) / file.filename
#     with open(save_path, "wb") as buffer:
#         shutil.copyfileobj(file.file, buffer)

#     content = read_uploaded_file(str(save_path))
#     doc = Document(page_content=content, metadata={"source": file.filename})

#     try:
#         vectorstore = create_or_load_vectorstore([doc])
#         return {"status": "success", "filename": file.filename}
#     except Exception as e:
#         return {"status": "failed", "error": str(e)}

@app.post("/add_prompt")
def add_prompt_endpoint(request: PromptRequest):
    return add_prompt(request.name, request.prompt)

@app.get("/get_prompts")
def get_prompts_endpoint():
    return get_prompts()

@app.put("/edit_prompt")
def edit_prompt_endpoint(request: EditPromptRequest):
    return edit_prompt(request.old_name, request.new_name, request.new_prompt)

@app.delete("/delete_prompt/{name}")
def delete_prompt_endpoint(name: str):
    return delete_prompt(name)

@app.post("/set_active_prompt/{name}")
def set_active_prompt_endpoint(name: str):
    return set_active_prompt(name)

@app.get("/get_active_prompt")
def get_active_prompt_endpoint():
    return get_active_prompt()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
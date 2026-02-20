from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import warnings
from typing import List, Union
from app.models.schemas import (
    QueryRequest,
    PromptGenerationRequest,
)

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from app.lifespan import lifespan

app = FastAPI(title="Strategisthub Email Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/query")
async def handle_query(request: QueryRequest):
    from app.api.queries import handle_query as query_handler
    return await query_handler(request)

@app.post("/query/stream")
async def handle_query_stream(request: QueryRequest):
    from app.api.queries import handle_query_stream as query_stream_handler
    return await query_stream_handler(request)

@app.get("/conversations/{conversation_id}")
async def get_conversation_history(conversation_id: str):
    from app.api.conversations import get_conversation_history as get_history
    return await get_history(conversation_id)

@app.delete("/conversations/{conversation_id}")
async def delete_conversation_history(conversation_id: str):
    from app.api.conversations import delete_conversation_history as delete_history
    return await delete_history(conversation_id)


@app.post("/upload_user_document")
async def upload_user_document(
    file: Union[UploadFile, List[UploadFile]] = File(...),
    user_id: str = Form(...)
):
    from app.api.documents import upload_user_document as upload_doc
    return await upload_doc(file, user_id)

@app.get("/get_user_documents/{user_id}")
def get_user_documents(user_id: str):
    from app.api.documents import get_user_documents as get_docs
    return get_docs(user_id)

@app.get("/download_user_document/{file_id}")
def download_user_document(file_id: str, user_id: str):
    from app.api.documents import download_user_document as download_doc
    return download_doc(file_id, user_id)

@app.delete("/delete_user_document/{file_id}")
def delete_user_document(file_id: str, user_id: str):
    from app.api.documents import delete_user_document as delete_doc
    return delete_doc(file_id, user_id)

@app.delete("/admin/delete_user/{target_user_id}")
def admin_delete_user(target_user_id: str):
    from app.api.documents import admin_delete_user as admin_delete
    return admin_delete(target_user_id)

@app.post("/generate_prompt")
def generate_prompt_endpoint(request: PromptGenerationRequest):
    from app.api.prompts import generate_prompt_endpoint as generate_prompt
    return generate_prompt(request)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
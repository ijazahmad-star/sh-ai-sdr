from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.documents import Document
from pydantic import BaseModel
from pathlib import Path
import shutil
import uvicorn
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from app.config import PDF_DIR, WEB_URLS
from app.data_loader import read_uploaded_file
from app.tools import create_retriever_tool
from app.graph_builder import build_workflow
from app.vectorstore_weaviate import create_or_load_vectorstore, load_vectorstore
# from app.vectorstore_supabase import create_or_load_vectorstore, load_vectorstore
from app.system_prompt import EMAIL_SYSTEM_PROMPT


app = FastAPI(title="Strategisthub Email Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or "http://localhost:5173"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


PROMPT_PATH = Path("app/system_prompt.py")

class QueryRequest(BaseModel):
    query: str

class PromptRequest(BaseModel):
    new_prompt: str

@app.post("/query")
async def handle_query(request: QueryRequest):
    retriever = load_vectorstore()
    tools = create_retriever_tool(retriever)
    graph = build_workflow(tools, EMAIL_SYSTEM_PROMPT)
    config = {"configurable": {"thread_id": "1"}}
    response = graph.invoke({"messages": request.query}, config=config)
    return {"response": response["messages"][-1].content}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    save_path = Path(PDF_DIR) / file.filename
    # with open(save_path, "wb") as buffer:
    #     shutil.copyfileobj(file.file, buffer)

    content = read_uploaded_file(str(save_path))
    doc = Document(page_content=content, metadata={"source": file.filename})

    try:
        vectorstore = create_or_load_vectorstore([doc])
        return {"status": "success", "filename": file.filename}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# @app.get("/get-prompt")
# def get_prompt():
#     if not PROMPT_PATH.exists():
#         return {"EMAIL_SYSTEM_PROMPT": ""}
#     content = PROMPT_PATH.read_text()
#     return {"EMAIL_SYSTEM_PROMPT": content}


@app.post("/update-prompt")
def update_prompt(request: PromptRequest):
    new_prompt = request.new_prompt
    if not new_prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    new_content = f'EMAIL_SYSTEM_PROMPT = """{new_prompt.strip()}"""\n'
    PROMPT_PATH.write_text(new_content)

    return {
        "message": "System prompt file cleared and rewritten successfully",
        "system_prompt": new_prompt
    }



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


"""
Below code is for basic ui that made using gradio
you can test your model using this code locally. 
"""

# from app.config import PDF_DIR, WEB_URLS, EMAIL_SYSTEM_PROMPT
# from app.data_loader import load_pdfs_from_directory, load_from_websites
# # from app.vectorstore import build_vectorstore
# from app.tools import create_retriever_tool
# from app.graph_builder import build_workflow
# from app.ui import launch_ui
# from app.vectorstore_weaviate import create_or_load_vectorstore
# import warnings
# warnings.filterwarnings("ignore", category=DeprecationWarning)

# print("Loading documents...")
# pdf_docs = load_pdfs_from_directory(PDF_DIR)
# web_docs = load_from_websites(WEB_URLS)
# all_docs = pdf_docs + web_docs
# #
# print("Building vector store...")
# # retriever = build_vectorstore(all_docs)
# retriever = create_or_load_vectorstore(all_docs)

# print("Setting up tools...")
# tools = create_retriever_tool(retriever)

# print("Building LangGraph workflow...")
# app = build_workflow(tools, EMAIL_SYSTEM_PROMPT)
# config = {"configurable": {"thread_id": "1"}}

# print("\n\nLaunching Strategisthub Email Assistant UI...")
# ui = launch_ui(app, config)
# ui.launch()

# from fastapi import FastAPI, UploadFile, File
# from pydantic import BaseModel
# import shutil
# from pathlib import Path
# import uvicorn

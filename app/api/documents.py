from fastapi import UploadFile, File, Form, HTTPException
from app.core.config import supabase
from app.services.data_loader_service import read_uploaded_file, clean_text
from app.services.vectorstore_service import create_or_load_vectorstore
from langchain_core.documents import Document
import uuid
import os
from typing import List, Union

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

def get_user_documents(user_id: str):
    print(f"Fetching documents for user_id--------->: {user_id}")
    res = supabase.table("user_files").select("*").eq("user_id", user_id).execute()
    return {"documents": res.data}

def download_user_document(file_id: str, user_id: str):
    record = supabase.table("user_files").select("*").eq("id", file_id).execute()

    if not record.data or len(record.data) == 0:
        raise HTTPException(status_code=404, detail="File not found")

    file = record.data[0]

    if file["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    url = supabase.storage.from_("user_documents").create_signed_url(file["storage_path"], 60)

    return {"download_url": url["signedUrl"]}

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
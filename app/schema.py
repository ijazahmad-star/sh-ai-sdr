from pydantic import BaseModel
from typing import Optional

# class QueryRequest(BaseModel):
#     user_id: str
#     query: str
# class QueryRequest(BaseModel):
#     query: str
#     user_id: str
#     kb_type: Optional[str] = "default" 


class UploadRequest(BaseModel):
    user_id: Optional[str] = None  # None = default KB

class QueryRequest(BaseModel):
    query: str
    user_id: str
    kb_type: Optional[str] = "default" 

class PromptRequest(BaseModel):
    name: str
    prompt: str
    user_id: str

class EditPromptRequest(BaseModel):
    old_name: str
    new_name: str = None
    new_prompt: str = None
    user_id: str
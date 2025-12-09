from pydantic import BaseModel

class QueryRequest(BaseModel):
    query: str
    user_id: str

class PromptRequest(BaseModel):
    name: str
    prompt: str
    user_id: str

class EditPromptRequest(BaseModel):
    old_name: str
    new_name: str = None
    new_prompt: str = None
    user_id: str
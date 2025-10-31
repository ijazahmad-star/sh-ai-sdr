from pydantic import BaseModel

class QueryRequest(BaseModel):
    query: str

class PromptRequest(BaseModel):
    name: str
    prompt: str

class EditPromptRequest(BaseModel):
    old_name: str
    new_name: str = None
    new_prompt: str = None
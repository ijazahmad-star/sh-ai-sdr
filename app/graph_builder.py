from langgraph.graph import StateGraph, MessagesState
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
# from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END
import os
from dotenv import load_dotenv
import os
from supabase import create_client
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_API_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

MEMORY_TABLE = "user_memories"  # make sure this table exists in Supabase

def save_memory(user_id: str, text: str):
    supabase.table(MEMORY_TABLE).insert({
        "user_id": user_id,
        "memory_text": text
    }).execute()

def load_memories(user_id: str):
    result = supabase.table(MEMORY_TABLE).select("*").eq("user_id", user_id).execute()
    return [r["memory_text"] for r in result.data]



def build_workflow(tools, system_prompt):
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(tools)
    # api_key = os.getenv("GOOGLE_API_KEY")
    # model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, google_api_key = api_key).bind_tools(tools)

    tool_node = ToolNode(tools)

    def call_model(state: MessagesState):
        response = model.invoke([SystemMessage(content=system_prompt)] + state["messages"])
        return {"messages": [response]}

    def should_continue(state: MessagesState):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)

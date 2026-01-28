from langgraph.graph import StateGraph, MessagesState
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
# from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END
import os

def build_workflow(tools, system_prompt, checkpointer, modal_name: str):
    model = ChatOpenAI(model=modal_name, temperature=0).bind_tools(tools)
    print(f"Using model: {modal_name}")
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

    return workflow.compile(checkpointer=checkpointer)

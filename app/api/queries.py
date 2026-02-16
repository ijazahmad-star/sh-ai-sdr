from fastapi import HTTPException
from app.models.schemas import QueryRequest
from app.services.vectorstore_service import get_active_prompt, log_model_usage
from app.services.tools_service import create_retriever_tool, search_google_tool
from app.services.llm_service import build_workflow
from app.lifespan import checkpointer
from app.core.config import supabase
import time

async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB (Optimized JSON Response)"""

    active_prompt_data = get_active_prompt(request.user_id)
    system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", "You are a helpful assistant. When using the database tool, retrieve all required information in a single call. Do not call the database tool multiple times. Plan what you need before calling it")

    use_user_kb = request.kb_type == "custom"
    tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
    tools.append(search_google_tool())
 
    graph = build_workflow(tools, system_prompt, checkpointer, request.model)
    config = {"configurable": {"thread_id": request.conversation_id}}
    
    start_time = time.time()
    result = graph.invoke({"messages": request.query}, config=config)
    end_time = time.time()
    print(f"Agent total response invoke time: {end_time - start_time:.2f} seconds")
    
    messages = result["messages"]
    final_ai_msg = ""
    final_msg_id = None
    sources = []
    
    total_input_tokens = 0
    total_output_tokens = 0

    # Find the last AIMessage to calculate tokens only for the recent response
    last_ai_msg = None
    for msg in messages:
        if msg.__class__.__name__ == "AIMessage":
            last_ai_msg = msg  # Overwrite to get the last one
            if msg.content:
                final_ai_msg = msg.content
                final_msg_id = msg.id

    # Extract usage metadata only from the last AIMessage
    if last_ai_msg:
        if hasattr(last_ai_msg, "usage_metadata") and last_ai_msg.usage_metadata:
            total_input_tokens = last_ai_msg.usage_metadata.get("input_tokens", 0)
            total_output_tokens = last_ai_msg.usage_metadata.get("output_tokens", 0)
            print(f"Total input tokens: {total_input_tokens}, Total output tokens: {total_output_tokens}")
        # Fallback for some providers/older versions
        elif "token_usage" in last_ai_msg.response_metadata:
            usage = last_ai_msg.response_metadata["token_usage"]
            total_input_tokens = usage.get("prompt_tokens", 0)
            total_output_tokens = usage.get("completion_tokens", 0)
            print(f"(Callback)Total input tokens: {total_input_tokens}, Total output tokens: {total_output_tokens}")

    # Log usage to database
    log_model_usage(request.user_id, request.model, total_input_tokens, total_output_tokens, request.query, final_ai_msg)

    # Collect sources from ToolMessages
    for msg in messages:
        if msg.__class__.__name__ == "ToolMessage" and use_user_kb:
            if hasattr(msg, "artifact") and msg.artifact:
                for item in msg.artifact:
                    sources.append({
                        "source": item["metadata"].get("source"),
                        "content": item["page_content"],
                        "rerank_score": item.get("rerank_score")
                    })

    if sources:
        unique = {s["source"]: s for s in sources}
        sources = sorted(unique.values(), key=lambda x: x.get("rerank_score", 0), reverse=True)

    return {
        "response": final_ai_msg,
        "sources": sources,
        "message_id": final_msg_id
    }
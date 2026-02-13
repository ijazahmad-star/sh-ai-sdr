from fastapi import HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.postgres import PostgresSaver
from app.core.config import SUPABASE_DB_URI
import re

async def get_conversation_history(conversation_id: str):
    try:
        config = {"configurable": {"thread_id": conversation_id}}
        with PostgresSaver.from_conn_string(SUPABASE_DB_URI) as checkpointer:
            state = checkpointer.get_tuple(config)
            if not state:
                return {"thread_id": conversation_id, "messages": []}

            raw_messages = state.checkpoint.get("channel_values", {}).get("messages", [])
            formatted_messages = []
            current_turn_sources = []

            for msg in raw_messages:
                # --- ToolMessage: collect sources ---
                if isinstance(msg, ToolMessage):
                    if hasattr(msg, "artifact") and msg.artifact:
                        for item in msg.artifact:
                            metadata = item.get("metadata", {})
                            current_turn_sources.append({
                                "source": metadata.get("source", "Unknown"),
                                "rerank_score": item.get("rerank_score", 0),
                                "tool_message_id": getattr(msg, "id", None)
                            })
                    continue

                # --- HumanMessage or AIMessage ---
                if isinstance(msg, (HumanMessage, AIMessage)):
                    content = msg.content or ""
                    clean_text = re.split(r"Rerank Score:", content)[0].strip()
                    clean_text = re.sub(r"Source: \{.*?\}", "", clean_text).strip()
                    if not clean_text:
                        continue

                    sorted_sources = []
                    if isinstance(msg, AIMessage):
                        unique_sources = {}
                        for s in current_turn_sources:
                            name = s["source"]
                            if name not in unique_sources or s["rerank_score"] > unique_sources[name]["rerank_score"]:
                                unique_sources[name] = s
                        sorted_sources = sorted(unique_sources.values(), key=lambda x: x["rerank_score"], reverse=True)
                        current_turn_sources = []

                    formatted_messages.append({
                        "id": getattr(msg, "id", None),
                        "role": "user" if isinstance(msg, HumanMessage) else "assistant",
                        "content": clean_text,
                        "sources": sorted_sources
                    })
            # print(f"Retrieved {(formatted_messages)}")
            return {
                "thread_id": conversation_id,
                "messages": formatted_messages
            }

    except Exception as e:
        print(f"Error retrieving history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def delete_conversation_history(conversation_id: str):
    """
    Delete all stored history for a conversation (thread) in Postgres checkpointer.
    """
    try:
        with PostgresSaver.from_conn_string(SUPABASE_DB_URI) as checkpointer:
            # Remove all checkpointed state for this thread
            checkpointer.delete_thread(conversation_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {str(e)}")

    return {"message": "Conversation history deleted successfully."}
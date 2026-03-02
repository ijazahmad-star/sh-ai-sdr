from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import QueryRequest
from app.services.vectorstore_service import get_active_prompt, log_model_usage
from app.services.tools_service import create_retriever_tool, search_google_tool, linkedin_tool
from app.services.llm_service import build_workflow
from app.lifespan import checkpointer
from langchain_core.messages import HumanMessage, AIMessage
from app.services.partial_store import save_partial, delete_partial, get_partial
import time
import json
import asyncio
import traceback
import contextlib
import uuid
from app.utils.helpers import LINKEDIN_SYSTEM_PROMPT, EMAIL_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT

async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB (Optimized JSON Response)"""

    active_prompt_data = get_active_prompt(request.user_id)
    
    # Combine SDR and Lead initial messages if source is email
    if request.lead_source == "email" and request.sdr_message and request.lead_message:
        request.query = (
            f"First inital conversation with client/lead \n"
            f"{request.sdr_message}\n"
            f"{request.lead_message} \n\n"
            f"This is our first message."
        )

    system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", LINKEDIN_SYSTEM_PROMPT)

    use_user_kb = request.kb_type == "custom"
    tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
    tools.append(search_google_tool())
    tools.append(linkedin_tool())
 
    graph = build_workflow(tools, system_prompt, checkpointer, request.model)
    config = {"configurable": {"thread_id": request.conversation_id}}
    
    start_time = time.time()
    result = graph.invoke({"messages": [request.query]}, config=config)
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

# ---------------------------------------------------------------------------
# Final persist helper
# ---------------------------------------------------------------------------
async def _persist_final(graph, config, content: str, message_id: str):
    try:
        print(f"[persist] Writing final message {message_id} ({len(content)} chars)...")
        await asyncio.shield(
            graph.aupdate_state(
                config,
                {"messages": [AIMessage(content=content, id=message_id)]}
            )
        )
        print(f"[persist] Done for {message_id}")
    except Exception as e:
        print(f"[persist] Error: {e}")
        raise


# ---------------------------------------------------------------------------
# Restore any saved partial from a previous cancelled stream
# ---------------------------------------------------------------------------
async def _restore_partial_if_exists(graph, config, conversation_id: str):
    """
    If the previous stream was cancelled, a partial response was saved
    to the in-memory store. Restore it to LangGraph before the next turn.
    """
    partial = await get_partial(conversation_id)
    if partial:
        print(f"[restore] Found partial response for {conversation_id}, restoring...")
        try:
            restore_id = "lc_run--" + str(uuid.uuid4())
            await graph.aupdate_state(
                config,
                {"messages": [AIMessage(content=partial, id=restore_id)]}
            )
            await delete_partial(conversation_id)
            print(f"[restore] Partial restored successfully")
        except Exception as e:
            print(f"[restore] Failed to restore partial: {e}")
            await delete_partial(conversation_id)  # clear it anyway to avoid loop


# ---------------------------------------------------------------------------
# Main streaming handler
# ---------------------------------------------------------------------------
async def handle_query_stream(request: QueryRequest):
    PARTIAL_CHAR_THRESHOLD = 512
    PARTIAL_TIME_THRESHOLD = 3.0
    print(f"[Database] Received DB: {request.kb_type}. and model: {request.model}")
    async def event_generator():
        accumulated_response = ""
        final_msg_id = "lc_run--" + str(uuid.uuid4())
        sources = []
        total_input_tokens = 0
        total_output_tokens = 0
        graph = None
        config = None

        try:
            # ------------------------------------------------------------------
            # 1. Setup
            # ------------------------------------------------------------------

            # Combine SDR and Lead initial messages if source is email
            if request.lead_source == "email" and request.sdr_message and request.lead_message:
                request.query = (
                    f"Initial conversation with Lead:\n\n"
                    f"SDR Message: {request.sdr_message}\n"
                    f"Lead Message: {request.lead_message}\n\n"
                    f"this is our first conversation with the Lead."
                )

            active_prompt_data = get_active_prompt(request.user_id)
            if request.lead_source == "email":
                system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", EMAIL_SYSTEM_PROMPT)
            elif request.lead_source == "linkedin":
                system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", LINKEDIN_SYSTEM_PROMPT)
            else:
                system_prompt = (
                    active_prompt_data
                    .get("active_prompt", {})
                    .get("prompt", DEFAULT_SYSTEM_PROMPT)
                )
            # print(f"Using system prompt: {system_prompt[:100]}...")
            use_user_kb = request.kb_type == "custom"
            tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
            tools.append(search_google_tool())
            tools.append(linkedin_tool())

            graph = build_workflow(tools, system_prompt, checkpointer, request.model)
            config = {"configurable": {"thread_id": request.conversation_id}}

            # ------------------------------------------------------------------
            # 2. Restore partial from previous cancelled stream (if any)
            #    This runs BEFORE the new HumanMessage is added, so the
            #    partial AIMessage gets inserted cleanly into history first.
            # ------------------------------------------------------------------
            await _restore_partial_if_exists(graph, config, request.conversation_id)

            chars_since_partial = 0
            last_partial_time = time.time()
            partial_save_task: asyncio.Task | None = None

            # ------------------------------------------------------------------
            # 3. Stream events
            # ------------------------------------------------------------------
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=request.query)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    if hasattr(chunk, "content") and chunk.content:
                        token = chunk.content
                        accumulated_response += token
                        chars_since_partial += len(token)

                        yield f"data: {json.dumps({'type': 'content', 'data': token})}\n\n"

                        now = time.time()
                        should_flush = (
                            chars_since_partial >= PARTIAL_CHAR_THRESHOLD
                            or (now - last_partial_time) >= PARTIAL_TIME_THRESHOLD
                        )
                        if should_flush:
                            chars_since_partial = 0
                            last_partial_time = now
                            if partial_save_task is None or partial_save_task.done():
                                snapshot = accumulated_response
                                partial_save_task = asyncio.create_task(
                                    save_partial(request.conversation_id, snapshot)
                                )

                elif kind == "on_chat_model_end":
                    output = event.get("data", {}).get("output", {})
                    if hasattr(output, "id") and output.id:
                        final_msg_id = output.id
                    if hasattr(output, "usage_metadata") and output.usage_metadata:
                        total_input_tokens = output.usage_metadata.get("input_tokens", 0)
                        total_output_tokens = output.usage_metadata.get("output_tokens", 0)

                elif kind == "on_tool_end" and use_user_kb:
                    output = event.get("data", {}).get("output", {})
                    if hasattr(output, "artifact") and output.artifact:
                        for item in output.artifact:
                            sources.append({
                                "source": item["metadata"].get("source", "Unknown"),
                                "content": item.get("page_content", ""),
                                "rerank_score": item.get("rerank_score", 0),
                            })

            # ------------------------------------------------------------------
            # 4. Wait for any in-flight partial save to finish
            # ------------------------------------------------------------------
            if partial_save_task and not partial_save_task.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await partial_save_task

            # ------------------------------------------------------------------
            # 5. Persist FINAL complete message to LangGraph checkpointer (once)
            # ------------------------------------------------------------------
            if accumulated_response and graph and config:
                await _persist_final(graph, config, accumulated_response, final_msg_id)

            # ------------------------------------------------------------------
            # 6. Clean up partial store (stream completed successfully)
            # ------------------------------------------------------------------
            await delete_partial(request.conversation_id)

            # ------------------------------------------------------------------
            # 7. Deduplicate & sort sources
            # ------------------------------------------------------------------
            if sources:
                unique = {s["source"]: s for s in sources}
                sources = sorted(unique.values(), key=lambda x: x.get("rerank_score", 0), reverse=True)

            # ------------------------------------------------------------------
            # 8. Log usage
            # ------------------------------------------------------------------
            log_model_usage(
                request.user_id,
                request.model,
                total_input_tokens,
                total_output_tokens,
                request.query,
                accumulated_response,
            )

            # ------------------------------------------------------------------
            # 9. Send done event
            # ------------------------------------------------------------------
            yield f"data: {json.dumps({'type': 'done', 'message_id': final_msg_id, 'sources': sources})}\n\n"

        # ----------------------------------------------------------------------
        # Client disconnected mid-stream
        # DO NOT touch graph/DB — psycopg connection may be broken.
        # Save partial to in-memory store; it will be restored on next request.
        # ----------------------------------------------------------------------
        except asyncio.CancelledError:
            print("[stream] Client disconnected (CancelledError)")

            # Save whatever we have to in-memory store (no DB call)
            # This will be restored to LangGraph at the start of the next request
            if accumulated_response:
                await save_partial(request.conversation_id, accumulated_response)
                print(f"[cancel] Saved {len(accumulated_response)} chars to partial store")

                log_model_usage(
                    request.user_id,
                    request.model,
                    total_input_tokens,
                    total_output_tokens,
                    request.query,
                    accumulated_response,
                )

            yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"

        # ----------------------------------------------------------------------
        # Any other unexpected error
        # ----------------------------------------------------------------------
        except Exception as e:
            print(f"[stream] Error: {e}")
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
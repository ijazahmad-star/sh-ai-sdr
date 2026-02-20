from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from app.models.schemas import QueryRequest
from app.services.vectorstore_service import get_active_prompt, log_model_usage
from app.services.tools_service import create_retriever_tool, search_google_tool
from app.services.llm_service import build_workflow
from app.lifespan import checkpointer
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
import time
import json
import asyncio
import traceback
import contextlib
import uuid

system_prompt_default ="""
You are a highly skilled Sales Development Representative (SDR). Your role is to engage with users professionally, understand their needs, and respond with accurate, helpful, and persuasive information.
You communicate in a confident, clear, and convincing tone while remaining polite and respectful. Your goal is to build trust, highlight value, and guide the user toward the most suitable solution based on their requirements.

Guidelines:
Answer user queries to the best of your knowledge using clear and structured responses.
Maintain a persuasive but non-pushy tone.
Focus on benefits, value, and outcomes rather than just features.
Ask relevant follow-up questions when needed to better understand the user’s needs.
If any required information is missing, politely request clarification instead of making assumptions.
If you do not have enough information to provide an accurate answer, clearly and respectfully state that and ask for the necessary details.
Keep responses concise, professional, and solution-oriented.
Always aim to move the conversation forward constructively.
Your objective is to qualify, inform, and guide the user effectively while delivering an excellent conversational experience.
"""

async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB (Optimized JSON Response)"""

    active_prompt_data = get_active_prompt(request.user_id)
    system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", system_prompt_default)

    use_user_kb = request.kb_type == "custom"
    tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
    tools.append(search_google_tool())
 
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

# Assumes QueryRequest has attributes: user_id, conversation_id, kb_type, model, query
# and that build_workflow, get_active_prompt, create_retriever_tool, search_google_tool,
# checkpointer, log_model_usage are available in the module scope.

# Persist helper - run safely in background or awaited
async def _persist_state(graph, config, content, message_id=None):
    try:
        # We shield the update_state call so that if the client cancels the request,
        # the background database write (which takes some time) doesn't get 
        # killed mid-transaction.
        print(f"Starting shielded persist for {message_id}...")
        await asyncio.shield(
            graph.aupdate_state(
                config,
                {"messages": [AIMessage(content=content, id=message_id)]}
            )
        )
        print(f"Persist finished for {message_id}")
    except Exception as e:
        # Log but do not raise so streaming is not interrupted
        print(f"Persist error: {e}")

async def handle_query_stream(request: QueryRequest):
    """Handle user query with streaming response, periodic partial persists, and final persist."""

    # Configuration for periodic persists
    FLUSH_CHAR_THRESHOLD = 512        # persist after ~512 characters accumulated
    FLUSH_TIME_SECONDS = 3.0         # OR persist at least every 3 seconds

    async def event_generator():
        try:
            # 1. Setup Graph and Context
            active_prompt_data = get_active_prompt(request.user_id)
            system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", "You are a helpful assistant.")

            use_user_kb = request.kb_type == "custom"
            tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
            tools.append(search_google_tool())

            # Build the workflow (graph) and thread config
            graph = build_workflow(tools, system_prompt, checkpointer, request.model)
            config = {"configurable": {"thread_id": request.conversation_id}}

            # Tracking variables
            accumulated_response = ""
            final_msg_id = "lc_run--" + str(uuid.uuid4())
            # final_msg_id = None
            sources = []
            total_input_tokens = 0
            total_output_tokens = 0

            # Persist debounce state
            chars_since_flush = 0
            last_flush_time = time.time()
            # Track background persist task to avoid unbounded concurrency
            background_persist_task = None

            # 2. Use astream_events for token-level streaming
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=request.query)]},
                config=config,
                version="v2"
            ):
                kind = event.get("event")

                # Stream LLM tokens as they arrive
                if kind == "on_chat_model_stream":
                    chunk_data = event.get("data", {})
                    chunk_content = chunk_data.get("chunk", {})

                    if hasattr(chunk_content, "content") and chunk_content.content:
                        content_chunk = chunk_content.content
                        accumulated_response += content_chunk
                        chars_since_flush += len(content_chunk)

                        # Yield token chunk to client immediately
                        yield f"data: {json.dumps({'type': 'content', 'data': content_chunk})}\n\n"

                        # Decide whether to flush partial persist:
                        now = time.time()
                        if chars_since_flush >= FLUSH_CHAR_THRESHOLD or (now - last_flush_time) >= FLUSH_TIME_SECONDS:
                            chars_since_flush = 0
                            last_flush_time = now

                            # If there is an outstanding background persist, don't spawn another; let it finish.
                            if background_persist_task and not background_persist_task.done():
                                # Optionally cancel and replace if you want newer-only writes:
                                # background_persist_task.cancel()
                                pass

                            # Launch a background persist (non-blocking)
                            background_persist_task = asyncio.create_task(
                                _persist_state(graph, config, accumulated_response, message_id=final_msg_id)
                            )

                # Capture final message ID and metadata
                elif kind == "on_chat_model_end":
                    output = event.get("data", {}).get("output", {})
                    if hasattr(output, "id"):
                        final_msg_id = output.id

                    # Track token usage
                    if hasattr(output, "usage_metadata") and output.usage_metadata:
                        total_input_tokens = output.usage_metadata.get("input_tokens", 0)
                        total_output_tokens = output.usage_metadata.get("output_tokens", 0)

                # Capture tool call results (sources)
                elif kind == "on_tool_end" and use_user_kb:
                    output = event.get("data", {}).get("output", {})
                    if hasattr(output, "artifact") and output.artifact:
                        for item in output.artifact:
                            sources.append({
                                "source": item["metadata"].get("source", "Unknown"),
                                "content": item.get("page_content", ""),
                                "rerank_score": item.get("rerank_score", 0)
                            })

                # Optionally handle other event kinds (errors, interrupts) here

            # 3. Post-stream processing: ensure any background persist finished and persist final response
            # Wait for the last background persist to finish (if any)
            if background_persist_task:
                with contextlib.suppress(asyncio.CancelledError):
                    await background_persist_task

            # Persist the final accumulated response (await to ensure durable write)
            if accumulated_response:
                try:
                    await _persist_state(graph, config, accumulated_response, message_id=final_msg_id)
                except Exception as persist_err:
                    print(f"Final persist error: {persist_err}")

            # Deduplicate and sort sources (if any)
            if sources:
                unique_sources = {s["source"]: s for s in sources}.values()
                sources = sorted(unique_sources, key=lambda x: x.get("rerank_score", 0), reverse=True)

            # Log final stats
            log_model_usage(
                request.user_id,
                request.model,
                total_input_tokens,
                total_output_tokens,
                request.query,
                accumulated_response
            )

            # Send final done event with message id and sources
            yield f"data: {json.dumps({'type': 'done', 'message_id': final_msg_id, 'sources': sources})}\n\n"

        except asyncio.CancelledError:
            # Client cancelled (disconnect)
            print("Stream cancelled by client (CancelledError path)")
            if accumulated_response:
                # Shielding is already handled inside _persist_state
                try:
                    print(f"Saving partial response on cancellation ({len(accumulated_response)} chars)")
                    await _persist_state(graph, config, accumulated_response, message_id=final_msg_id)
                except Exception as update_err:
                    print(f"Error updating state on cancellation: {update_err}")

                # Log usage to database
                log_model_usage(
                    request.user_id,
                    request.model,
                    total_input_tokens,
                    total_output_tokens,
                    request.query,
                    accumulated_response
                )

            yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"

        except Exception as e:
            print(f"Error in stream: {str(e)}")
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
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
from app.utils.helpers import LINKEDIN_SYSTEM_PROMPT
system_prompt_default ="""

You are “StrategistHub SDR Copilot” — an embedded assistant inside StrategistHub’s outreach tool.
Your job is to help SDRs run high-quality, personalized LinkedIn + email outreach to one prospect per chat, and to keep messaging consistent, compliant, and high-signal, must utilize tools first.

## 1) Core mission
For the prospect in this chat, generate:
- the best next outreach message (LinkedIn or email) based on the current stage
- 1–3 alternative variants (optional, when helpful)
- a short rationale (internal) for why it’s tailored
- what to do next if they reply (branch suggestions)
- a clean note to log in CRM (summary + tags)

Your output must be immediately usable by an SDR with minimal editing.

## 2) Inputs you will receive (treat as source of truth)
You may receive some or all:
- Channel: "linkedin" | "email"
- Stage: "connect" | "first_touch" | "follow_up_1" | "follow_up_2" | "re_engage" | "reply_handling"
- Prospect: name, role, company, LinkedIn URL, location (optional)
- Signals: hiring, funding, product launch, tech stack, posts, interviews, job ads, website copy, pain points
- Conversation history: prior messages + timestamps + their replies (if any)
- Offer focus (one): "AI agents/workflows" | "voice AI for support/onboarding + CRM updates" | "MVP/product build" | "modernization"
- Approved proof points: ONLY the set passed in as “ApprovedProofPoints”
- Hard constraints: max chars, tone, forbidden phrases, CTA type, etc.
- Compliance constraints: opt-out requirements, regulated topics, do-not-contact flags

If a key field is missing, do NOT interrogate the SDR. Make a best effort with what’s available and use neutral placeholders like {{FirstName}} or {{Company}}.

## 3) Non-negotiable rules (quality + trust)
- Don’t fabricate facts, metrics, partnerships, or “we saw…” claims.
- Don’t imply you scraped private data. Use only the provided Signals.
- Don’t guilt, pressure, or nag. No manipulative language.
- Never mention “AI wrote this,” “as an AI,” or internal policies.
- Never ask for sensitive personal data. Avoid protected-class inferences.
- Keep it human: no corporate buzzwords (“leverage”, “synergy”, “seamless”, “game-changing”).
- Avoid fluff openers (“Hope you’re well”, “Loved your profile”, “Just circling back”).
- Always be respectful of platform rules and anti-spam norms.
- If the prospect asks to stop, comply: provide a polite stop acknowledgement template.

## 4) StrategistHub positioning (what we do — keep it consistent)
StrategistHub is a senior-led product engineering partner that helps startups/SMBs:
- Build new products (MVP → scale)
- Modernize legacy systems
- Automate workflows with AI agents
- (When relevant) Voice AI agents for support/onboarding + CRM updates

Use ONLY the proof points in ApprovedProofPoints (e.g., specific projects, outcomes, industries).
If no proof point cleanly matches, don’t force it — use role-based value instead.

## 5) Message style guide (default)
Write like a sharp SDR typing quickly:
- Short, specific, and context-first
- 1 clear idea per message
- 1 simple CTA (yes/no or two-choice)
- Prefer 1–2 sentences on LinkedIn; 2–6 short lines on email
- Mention ONE concrete signal, then connect it to ONE likely pain, then a clear next step

### CTAs (choose one)
- “Worth a quick 15-min chat next week?”
- “Open to a quick call, or should I send 2–3 bullets here?”
- “If you’re not the right person, who owns this at {{Company}}?”

## 6) Channel constraints
### LinkedIn connection request (if Stage = connect)
- Max 300 characters unless a different limit is provided
- No links
- No pitch dump — just relevance + lightweight reason to connect

### LinkedIn message (first_touch / follow-ups)
- First touch: 1–2 sentences (max ~300–500 chars unless specified)
- Follow-ups: even shorter; add new info or angle, not “checking in”
- Never send more than 2 follow-ups unless SDR explicitly requests more

### Email
- Subject: 2–6 words, specific, no hype
- Body: 2–6 short lines, easy scan
- Include opt-out line if required by constraints (e.g., “Reply ‘unsub’ to opt out.”)

## 7) Personalization hierarchy (use the best available)
1) Direct signal from their recent activity (post, hiring, launch, funding, product update)
2) Role + company context (what’s hard for someone in that seat)
3) Industry pain point (generic but credible)
Never invent step (1). If not present, use (2) or (3).

## 8) Reply handling (Stage = reply_handling)
If they reply, classify it into one:
- Interested → propose 2 time options + 1-line agenda
- Curious / asks questions → answer briefly + propose next step
- Not now → offer to follow up in X weeks + ask what timing looks like
- Price/budget → give a simple starting range only if provided; otherwise propose discovery call
- Referral → ask for intro + draft a 2-line forwardable blurb
- Objection (“we have a team”) → acknowledge + offer a wedge (audit, pilot, automation slice)
- Unsubscribe/stop → comply template

## 9) Final instruction
Optimize for replies, not poetry. Be direct, specific, and helpful.
When in doubt: shorter, more concrete, fewer claims.

"""

async def handle_query(request: QueryRequest):
    """Handle user query with user-specific or default KB (Optimized JSON Response)"""

    active_prompt_data = get_active_prompt(request.user_id)
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

# # Assumes QueryRequest has attributes: user_id, conversation_id, kb_type, model, query
# # and that build_workflow, get_active_prompt, create_retriever_tool, search_google_tool,
# # checkpointer, log_model_usage are available in the module scope.

# # Persist helper - run safely in background or awaited
# async def _persist_state(graph, config, content, message_id=None):
#     try:
#         # We shield the update_state call so that if the client cancels the request,
#         # the background database write (which takes some time) doesn't get 
#         # killed mid-transaction.
#         print(f"Starting shielded persist for {message_id}...")
#         await asyncio.shield(
#             graph.aupdate_state(
#                 config,
#                 {"messages": [AIMessage(content=content, id=message_id)]}
#             )
#         )
#         print(f"Persist finished for {message_id}")
#     except Exception as e:
#         # Log but do not raise so streaming is not interrupted
#         print(f"Persist error: {e}")

# async def handle_query_stream(request: QueryRequest):
#     """Handle user query with streaming response, periodic partial persists, and final persist."""

#     # Configuration for periodic persists
#     FLUSH_CHAR_THRESHOLD = 512        # persist after ~512 characters accumulated
#     FLUSH_TIME_SECONDS = 3.0         # OR persist at least every 3 seconds

#     async def event_generator():
#         try:
#             # 1. Setup Graph and Context
#             active_prompt_data = get_active_prompt(request.user_id)
#             system_prompt = active_prompt_data.get("active_prompt", {}).get("prompt", "You are a helpful assistant.")

#             use_user_kb = request.kb_type == "custom"
#             tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
#             tools.append(search_google_tool())

#             # Build the workflow (graph) and thread config
#             graph = build_workflow(tools, system_prompt, checkpointer, request.model)
#             config = {"configurable": {"thread_id": request.conversation_id}}

#             # Tracking variables
#             accumulated_response = ""
#             final_msg_id = "lc_run--" + str(uuid.uuid4())
#             # final_msg_id = None
#             sources = []
#             total_input_tokens = 0
#             total_output_tokens = 0

#             # Persist debounce state
#             chars_since_flush = 0
#             last_flush_time = time.time()
#             # Track background persist task to avoid unbounded concurrency
#             background_persist_task = None

#             # 2. Use astream_events for token-level streaming
#             async for event in graph.astream_events(
#                 {"messages": [HumanMessage(content=request.query)]},
#                 config=config,
#                 version="v2"
#             ):
#                 kind = event.get("event")

#                 # Stream LLM tokens as they arrive
#                 if kind == "on_chat_model_stream":
#                     chunk_data = event.get("data", {})
#                     chunk_content = chunk_data.get("chunk", {})

#                     if hasattr(chunk_content, "content") and chunk_content.content:
#                         content_chunk = chunk_content.content
#                         accumulated_response += content_chunk
#                         chars_since_flush += len(content_chunk)

#                         # Yield token chunk to client immediately
#                         yield f"data: {json.dumps({'type': 'content', 'data': content_chunk})}\n\n"

#                         # Decide whether to flush partial persist:
#                         now = time.time()
#                         if chars_since_flush >= FLUSH_CHAR_THRESHOLD or (now - last_flush_time) >= FLUSH_TIME_SECONDS:
#                             chars_since_flush = 0
#                             last_flush_time = now

#                             # If there is an outstanding background persist, don't spawn another; let it finish.
#                             if background_persist_task and not background_persist_task.done():
#                                 # Optionally cancel and replace if you want newer-only writes:
#                                 # background_persist_task.cancel()
#                                 pass

#                             # Launch a background persist (non-blocking)
#                             background_persist_task = asyncio.create_task(
#                                 _persist_state(graph, config, accumulated_response, message_id=final_msg_id)
#                             )

#                 # Capture final message ID and metadata
#                 elif kind == "on_chat_model_end":
#                     output = event.get("data", {}).get("output", {})
#                     if hasattr(output, "id"):
#                         final_msg_id = output.id

#                     # Track token usage
#                     if hasattr(output, "usage_metadata") and output.usage_metadata:
#                         total_input_tokens = output.usage_metadata.get("input_tokens", 0)
#                         total_output_tokens = output.usage_metadata.get("output_tokens", 0)

#                 # Capture tool call results (sources)
#                 elif kind == "on_tool_end" and use_user_kb:
#                     output = event.get("data", {}).get("output", {})
#                     if hasattr(output, "artifact") and output.artifact:
#                         for item in output.artifact:
#                             sources.append({
#                                 "source": item["metadata"].get("source", "Unknown"),
#                                 "content": item.get("page_content", ""),
#                                 "rerank_score": item.get("rerank_score", 0)
#                             })

#                 # Optionally handle other event kinds (errors, interrupts) here

#             # 3. Post-stream processing: ensure any background persist finished and persist final response
#             # Wait for the last background persist to finish (if any)
#             if background_persist_task:
#                 with contextlib.suppress(asyncio.CancelledError):
#                     await background_persist_task

#             # Persist the final accumulated response (await to ensure durable write)
#             if accumulated_response:
#                 try:
#                     await _persist_state(graph, config, accumulated_response, message_id=final_msg_id)
#                 except Exception as persist_err:
#                     print(f"Final persist error: {persist_err}")

#             # Deduplicate and sort sources (if any)
#             if sources:
#                 unique_sources = {s["source"]: s for s in sources}.values()
#                 sources = sorted(unique_sources, key=lambda x: x.get("rerank_score", 0), reverse=True)

#             # Log final stats
#             log_model_usage(
#                 request.user_id,
#                 request.model,
#                 total_input_tokens,
#                 total_output_tokens,
#                 request.query,
#                 accumulated_response
#             )

#             # Send final done event with message id and sources
#             yield f"data: {json.dumps({'type': 'done', 'message_id': final_msg_id, 'sources': sources})}\n\n"

#         except asyncio.CancelledError:
#             # Client cancelled (disconnect)
#             print("Stream cancelled by client (CancelledError path)")
#             if accumulated_response:
#                 # Shielding is already handled inside _persist_state
#                 try:
#                     print(f"Saving partial response on cancellation ({len(accumulated_response)} chars)")
#                     await _persist_state(graph, config, accumulated_response, message_id=final_msg_id)
#                 except Exception as update_err:
#                     print(f"Error updating state on cancellation: {update_err}")

#                 # Log usage to database
#                 log_model_usage(
#                     request.user_id,
#                     request.model,
#                     total_input_tokens,
#                     total_output_tokens,
#                     request.query,
#                     accumulated_response
#                 )

#             yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"

#         except Exception as e:
#             print(f"Error in stream: {str(e)}")
#             traceback.print_exc()
#             yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

#     return StreamingResponse(event_generator(), media_type="text/event-stream")


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
            active_prompt_data = get_active_prompt(request.user_id)
            system_prompt = (
                active_prompt_data
                .get("active_prompt", {})
                .get("prompt", system_prompt_default)
            )

            use_user_kb = request.kb_type == "custom"
            tools = create_retriever_tool(user_id=request.user_id, force_user_kb=use_user_kb)
            # tools.append(search_google_tool())
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
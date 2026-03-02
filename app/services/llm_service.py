from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
import time
from typing import Annotated
import operator

# def build_workflow(tools, system_prompt, checkpointer, model_name: str):
#     model = ChatOpenAI(
#         model=model_name,
#         temperature=0
#     ).bind_tools(tools)

#     tool_node = ToolNode(tools)

#     def agent(state: MessagesState):
#         messages = [SystemMessage(content=system_prompt)] + state["messages"]
#         # start_time = time.time()
#         response = model.invoke(messages)
#         # end_time = time.time()
#         # print(f"Agent total response time: {end_time - start_time:.2f} seconds")    
#         return {"messages": [response]}

#     def should_continue(state: MessagesState):
#         last = state["messages"][-1]
#         if not last.tool_calls:
#             return END
#         return "tools"

#     workflow = StateGraph(MessagesState)

#     workflow.add_node("agent", agent)
#     workflow.add_node("tools", tool_node)

#     workflow.add_edge(START, "agent")
#     workflow.add_conditional_edges("agent", should_continue)
#     workflow.add_edge("tools", "agent")


#     # start_compile = time.time()
#     app = workflow.compile(checkpointer=checkpointer)
#     # end_compile = time.time()
#     # print(f"Graph compilation took: {end_compile - start_compile:.4f} seconds")
#     return app


def build_workflow(tools, system_prompt, checkpointer, model_name: str):
    model = ChatOpenAI(
        model=model_name,
        temperature=0
    ).bind_tools(tools)

    # Parallel tool execution
    def parallel_tool_node(state: MessagesState):
        """Execute all tool calls in parallel"""
        last_message = state["messages"][-1]
        
        if not last_message.tool_calls:
            return {"messages": []}
        
        # Create tasks for all tool calls
        tool_results = []
        
        # Execute all tools in parallel
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(last_message.tool_calls)) as executor:
            futures = {}
            for tool_call in last_message.tool_calls:
                tool_name = tool_call["name"]
                tool_input = tool_call["args"]
                tool = next((t for t in tools if t.name == tool_name), None)
                if tool:
                    futures[executor.submit(tool.run, tool_input)] = tool_call
            
            # Collect results
            for future in concurrent.futures.as_completed(futures):
                tool_call = futures[future]
                try:
                    result = future.result()
                    tool_results.append(
                        ToolMessage(
                            content=result,
                            tool_call_id=tool_call["id"],
                            name=tool_call["name"]
                        )
                    )
                except Exception as e:
                    tool_results.append(
                        ToolMessage(
                            content=f"Error: {str(e)}",
                            tool_call_id=tool_call["id"],
                            name=tool_call["name"]
                        )
                    )
        
        return {"messages": tool_results}

    def agent(state: MessagesState):
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        
        response = model.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: MessagesState):
        last = state["messages"][-1]
        if not last.tool_calls:
            return END
        return "tools"

    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", agent)
    workflow.add_node("tools", parallel_tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    app = workflow.compile(checkpointer=checkpointer)
    return app



# def build_workflow(tools, system_prompt, checkpointer, model_name: str):
#     model = ChatOpenAI(
#         model=model_name,
#         temperature=0
#     ).bind_tools(tools)

#     tool_node = ToolNode(tools)

#     class ParallelState(MessagesState):
#         reasoning_paths: list[str]  # Store multiple reasoning attempts
#         final_answer: str

#     def agent(state: ParallelState):
#         messages = [SystemMessage(content=system_prompt)] + state["messages"]
#         response = model.invoke(messages)
#         return {"messages": [response]}

#     def parallel_reasoner(state: ParallelState):
#         """Generate multiple reasoning approaches in parallel"""
#         import concurrent.futures
        
#         def generate_reasoning(attempt_num):
#             messages = [SystemMessage(content=system_prompt)] + state["messages"]
#             messages.append(HumanMessage(
#                 content=f"Approach {attempt_num}: Think through this differently"
#             ))
#             response = model.invoke(messages)
#             return response.content
        
#         with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
#             futures = [executor.submit(generate_reasoning, i) for i in range(3)]
#             reasoning_paths = [f.result() for f in concurrent.futures.as_completed(futures)]
        
#         return {"reasoning_paths": reasoning_paths}

#     def should_continue(state: ParallelState):
#         last = state["messages"][-1]
#         if not last.tool_calls:
#             return END
#         return "tools"

#     workflow = StateGraph(ParallelState)
#     workflow.add_node("agent", agent)
#     workflow.add_node("tools", tool_node)
#     workflow.add_node("parallel_reasoner", parallel_reasoner)

#     workflow.add_edge(START, "agent")
#     workflow.add_conditional_edges("agent", should_continue)
#     workflow.add_edge("tools", "agent")

#     app = workflow.compile(checkpointer=checkpointer)
#     return app


# def build_workflow(tools, system_prompt, checkpointer, model_name: str):
#     model = ChatOpenAI(
#         model=model_name,
#         temperature=0
#     ).bind_tools(tools)

#     tool_node = ToolNode(tools)

#     class DecomposedState(MessagesState):
#         subtasks: list[str]
#         subtask_results: Annotated[list, operator.add]

#     def agent(state: DecomposedState):
#         messages = [SystemMessage(content=system_prompt)] + state["messages"]
#         response = model.invoke(messages)
#         return {"messages": [response]}

#     def decompose_task(state: DecomposedState):
#         """Break task into parallel subtasks"""
#         messages = [SystemMessage(content=system_prompt)] + state["messages"]
#         messages.append(HumanMessage(
#             content="Break this task into 3 independent subtasks that can be done in parallel"
#         ))
#         response = model.invoke(messages)
#         # Parse response to extract subtasks
#         subtasks = response.content.split("\n")
#         return {"subtasks": subtasks}

#     def should_continue(state: DecomposedState):
#         last = state["messages"][-1]
#         if not last.tool_calls:
#             return END
#         return "tools"

#     workflow = StateGraph(DecomposedState)
#     workflow.add_node("agent", agent)
#     workflow.add_node("tools", tool_node)
#     workflow.add_node("decompose", decompose_task)

#     workflow.add_edge(START, "agent")
#     workflow.add_conditional_edges("agent", should_continue)
#     workflow.add_edge("tools", "agent")

#     app = workflow.compile(checkpointer=checkpointer)
#     return app
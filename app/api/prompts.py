from fastapi import HTTPException
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.models.schemas import PromptRequest, EditPromptRequest, PromptGenerationRequest
from app.services.vectorstore_service import add_prompt, get_prompts, edit_prompt, delete_prompt, set_active_prompt

def generate_prompt_endpoint(request: PromptGenerationRequest):
    try:
        # Initialize the LLM
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)

        # Create a comprehensive prompt generation system message
        system_prompt = """You are an expert AI prompt engineer. Your task is to create comprehensive, well-structured system prompts for AI assistants based on user requirements.

                    Given user requirements, generate a detailed system prompt that includes:
                    1. Clear role definition for the AI assistant
                    2. Specific behaviors and capabilities
                    3. Guidelines for interaction style and tone
                    4. Any domain-specific knowledge or constraints
                    5. Response formatting preferences if applicable

                    The generated prompt should be professional, actionable, and optimized for the specific use case described in the requirements.

                    Structure your response as a complete system prompt that can be directly used by an AI assistant."""

        # Create the user message with requirements
        user_message = f"Generate a comprehensive system prompt based on these requirements:\n\n{request.requirements}"

        # Generate the prompt using the LLM
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]

        response = llm.invoke(messages)

        generated_prompt = response.content.strip()

        return {
            "status": "success",
            "generated_prompt": generated_prompt,
            "user_id": request.user_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate prompt: {str(e)}")

# Other prompt endpoints can be added here, like add, edit, delete, etc., but since they are simple, they can be inlined in main.py
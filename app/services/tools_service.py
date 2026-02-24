from langchain.tools import tool
from app.core.config import (supabase, embeddings)
import time
from langchain_community.tools import DuckDuckGoSearchRun
from app.services.vectorstore_service import get_admin_user_id, check_user_has_documents
from app.services.reranked_service import rerank_with_cross_encoder
from app.services.linkedin_service import fetch_linkedin_data as linkedin_fetcher_tool

def create_retriever_tool(user_id: str = None, force_user_kb: bool = False):
    """
    Create retriever tool for specific user or default KB
    
    Args:
        user_id: User ID
        force_user_kb: If True, force use of user KB (if available). 
                      If False, use default KB.
    """
    use_user_kb = False
    filter_user_id = None

    if force_user_kb and user_id:
        use_user_kb = check_user_has_documents(user_id)
        filter_user_id = user_id
    
    if not force_user_kb:
        user_id = get_admin_user_id()
        filter_user_id = user_id

    # kb_type = f"user-specific KB (user_id={user_id})" if use_user_kb else f"Admin-specific KB (user_id={filter_user_id})"
    
    @tool(response_format="content_and_artifact")
    def retrieve_documents(query: str):
        """Retrieve relevant documents from Supabase vector database based on semantic similarity."""
        query_embedding = embeddings.embed_query(query)
        # print(f"Retrieving from {kb_type}...")
        
        start_retrieval = time.time()
        response = supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_count": 3,
                "filter_user_id": filter_user_id
            }
        ).execute()
        end_retrieval = time.time()
        print(f"Vector retrieval (DB call) took: {end_retrieval - start_retrieval:.4f} seconds")
        
        if not response.data:
            return "No matching documents found.", []
        
        # print(f"Got {len(response.data)} documents from {kb_type}")
        
        docs = [
            {
                "page_content": doc["content"],
                "metadata": doc["metadata"],
                "similarity": doc["similarity"]
            }
            for doc in response.data
        ]
        
        # Rerank and get top 3
        reranked = rerank_with_cross_encoder(query, docs)
        top_docs = reranked[:2]
        
        serialized = "\n\n".join(
            f"Rerank Score: {d['rerank_score']:.3f}\nSource: {d['metadata']}\nContent: {d['page_content']}"
            for d in top_docs
        )
        
        return serialized, top_docs
    
    return [retrieve_documents]

def search_google_tool():    
    """
    Create Google Search tool
    """   
    return DuckDuckGoSearchRun()

def linkedin_tool():
    """
    Return the LinkedIn scraper tool.
    """
    return linkedin_fetcher_tool
from langchain.tools import tool
from app.config import (supabase, cross_encoder, embeddings)

def rerank_with_cross_encoder(query, docs):
    """Re-rank documents using cross-encoder"""
    print("Re-Ranking the results...")
    pairs = [(query, d["page_content"]) for d in docs]
    scores = cross_encoder.predict(pairs)
    ranked = [
        {**doc, "rerank_score": float(score)}
        for doc, score in zip(docs, scores)
    ]
    ranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return ranked

def check_user_has_documents(user_id: str) -> bool:
    """Check if user has their own KB"""
    response = supabase.table("documents").select("id").eq("user_id", user_id).limit(1).execute()
    return len(response.data) > 0

def check_user_has_access_to_default(user_id: str)-> bool:
    """
    Docstring for check_user_has_access_to_default
    
    :param user_id: Description
    :type user_id: str
    :return: Description
    :rtype: bool
    """
    response = supabase.table("kb_accesses").select("has_access_to_default_kb").eq("user_id", user_id).execute()
    if response.data and response.data[0]["has_access_to_default_kb"]:
        return True
    else:
        return False

def get_admin_user_id():
    """
    Docstring for get_admin_user_id
    """
    res = supabase.table("users").select("id").eq("role", "admin").single().execute()

    return res.data["id"]


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
        print("Admin User Id: ", user_id)
        filter_user_id = user_id

    kb_type = f"user-specific KB (user_id={user_id})" if use_user_kb else f"Admin-specific KB (user_id={filter_user_id})"
    
    print(f"Using {kb_type}")
    
    @tool(response_format="content_and_artifact")
    def retrieve_documents(query: str):
        """Retrieve relevant documents from Supabase vector database based on semantic similarity."""
        query_embedding = embeddings.embed_query(query)
        print(f"Retrieving from {kb_type}...")
        
        response = supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_count": 3,
                "filter_user_id": filter_user_id
            }
        ).execute()
        
        if not response.data:
            return "No matching documents found.", []
        
        print(f"Got {len(response.data)} documents from {kb_type}")
        
        docs = []
        for doc in response.data:
            docs.append({
                "page_content": doc["content"],
                "metadata": doc["metadata"],
                "similarity": doc["similarity"]
            })
        
        # Rerank and get top 3
        reranked = rerank_with_cross_encoder(query, docs)
        top_docs = reranked[:3]
        
        serialized = "\n\n".join(
            f"Rerank Score: {d['rerank_score']:.3f}\nSource: {d['metadata']}\nContent: {d['page_content']}"
            for d in top_docs
        )
        
        return serialized, top_docs
    
    return [retrieve_documents]
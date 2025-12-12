from langchain_openai import OpenAIEmbeddings
from supabase import create_client
from langchain.tools import tool
import os
from sentence_transformers import CrossEncoder
from dotenv import load_dotenv

load_dotenv()

# Load cross-encoder
cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

# Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_API_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
embeddings = OpenAIEmbeddings()

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
    response = supabase.table("kb_access").select("hasAccessToDefaultKB").eq("userId", user_id).execute()
    if response.data and response.data[0]["hasAccessToDefaultKB"]:
        print("User has access to the default KB")
        return True
    else:
        print("User does not have access to the default KB")
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
    
    # Determine which KB to use
    use_user_kb = False
    filter_user_id = None

    if force_user_kb and user_id:
        use_user_kb = check_user_has_documents(user_id)
        filter_user_id = user_id
    
    if not force_user_kb:
        user_id = get_admin_user_id()
        print("Admin User Id: ", user_id)
        filter_user_id = user_id

    
    # filter_user_id = user_id if use_user_kb else None
    kb_type = f"user-specific KB (user_id={user_id})" if use_user_kb else f"Admin-specific KB (user_id={filter_user_id})"
    
    print(f"Using {kb_type}")
    
    @tool(response_format="content_and_artifact")
    def retrieve_documents(query: str):
        """Retrieve relevant documents from Supabase vector database based on semantic similarity."""
        query_embedding = embeddings.embed_query(query)
        print(f"Retrieving from {kb_type}...")
        
        # Call match_documents with user_id filter
        response = supabase.rpc(
            "match_documents",
            {
                "query_embedding": query_embedding,
                "match_count": 5,  # Get more for reranking
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


# def create_retriever_tool(user_id: str = None):
#     """
#     Create retriever tool for specific user or default KB
#     If user_id is provided and user has documents, use their KB
#     Otherwise, use default KB (user_id = NULL)
#     """
    
#     # Check if we should use user-specific or default KB
#     use_user_kb = False
#     if user_id:
#         use_user_kb = check_user_has_documents(user_id)
    
#     filter_user_id = user_id if use_user_kb else None
#     kb_type = f"user-specific KB (user_id={user_id})" if use_user_kb else "default KB"
    
#     print(f"Using {kb_type}")
    
#     @tool(response_format="content_and_artifact")
#     def retrieve_documents(query: str):
#         """Retrieve relevant documents from Supabase vector database based on semantic similarity."""
#         query_embedding = embeddings.embed_query(query)
#         print(f"Retrieving from {kb_type}...")
        
#         # Call match_documents with user_id filter
#         response = supabase.rpc(
#             "match_documents",
#             {
#                 "query_embedding": query_embedding,
#                 "match_count": 5,  # Get more for reranking
#                 "filter_user_id": filter_user_id
#             }
#         ).execute()
        
#         if not response.data:
#             return "No matching documents found.", []
        
#         print(f"Got {len(response.data)} documents from {kb_type}")
        
#         docs = []
#         for doc in response.data:
#             docs.append({
#                 "page_content": doc["content"],
#                 "metadata": doc["metadata"],
#                 "similarity": doc["similarity"]
#             })
        
#         # Rerank and get top 3
#         reranked = rerank_with_cross_encoder(query, docs)
#         top_docs = reranked[:3]
        
#         serialized = "\n\n".join(
#             f"Rerank Score: {d['rerank_score']:.3f}\nSource: {d['metadata']}\nContent: {d['page_content']}"
#             for d in top_docs
#         )
        
#         return serialized, top_docs
    
#     return [retrieve_documents]

# def create_retriever_tool(user_id: str = None):
#     """
#     Create retriever tool for specific user or default KB
#     If user_id is provided and user has documents, use their KB
#     Otherwise, use default KB (user_id = NULL)
#     """
    
#     # Check if we should use user-specific or default KB
#     use_user_kb = False
#     if user_id:
#         use_user_kb = check_user_has_documents(user_id)
    
#     filter_user_id = user_id if use_user_kb else None
#     kb_type = f"user-specific KB (user_id={user_id})" if use_user_kb else "default KB"
    
#     print(f"Using {kb_type}")
    
#     @tool(response_format="content_and_artifact")
#     def retrieve_documents(query: str):
#         f"""Retrieve relevant documents from Supabase ({kb_type})."""
#         query_embedding = embeddings.embed_query(query)
#         print(f"Retrieving from {kb_type}...")
        
#         # Call match_documents with user_id filter
#         response = supabase.rpc(
#             "match_documents",
#             {
#                 "query_embedding": query_embedding,
#                 "match_count": 5,  # Get more for reranking
#                 "filter_user_id": filter_user_id
#             }
#         ).execute()
        
#         if not response.data:
#             return "No matching documents found.", []
        
#         print(f"Got {len(response.data)} documents from {kb_type}")
        
#         docs = []
#         for doc in response.data:
#             docs.append({
#                 "page_content": doc["content"],
#                 "metadata": doc["metadata"],
#                 "similarity": doc["similarity"]
#             })
        
#         # Rerank and get top 3
#         reranked = rerank_with_cross_encoder(query, docs)
#         top_docs = reranked[:3]
        
#         serialized = "\n\n".join(
#             f"Rerank Score: {d['rerank_score']:.3f}\nSource: {d['metadata']}\nContent: {d['page_content']}"
#             for d in top_docs
#         )
        
#         return serialized, top_docs
    
#     return [retrieve_documents]
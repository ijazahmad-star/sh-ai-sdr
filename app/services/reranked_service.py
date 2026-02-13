from app.core.config import (supabase, cross_encoder, embeddings)
import time

def rerank_with_cross_encoder(query, docs):
    """Re-rank documents using cross-encoder"""
    start_rerank = time.time()
    print("Re-Ranking the results...")
    pairs = [(query, d["page_content"]) for d in docs]
    scores = cross_encoder.predict(pairs)
    ranked = [
        {**doc, "rerank_score": float(score)}
        for doc, score in zip(docs, scores)
    ]
    ranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    end_rerank = time.time()
    print(f"Reranking took: {end_rerank - start_rerank:.4f} seconds")
    return ranked

def rerank_on_similarity(docs):
    """Re-rank documents using similarity score"""
    start_rerank = time.time()
    print("Re-Ranking the results based on similarity...")

    ranked = sorted(
        docs,
        key=lambda x: float(x.get("similarity", 0)),
        reverse=True
    )

    end_rerank = time.time()
    print(f"Reranking took: {end_rerank - start_rerank:.4f} seconds")
    return ranked
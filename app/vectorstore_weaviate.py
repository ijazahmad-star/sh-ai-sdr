import os
from weaviate import connect_to_weaviate_cloud
from weaviate.classes.config import Property, DataType
from langchain_openai import OpenAIEmbeddings
from langchain_weaviate import WeaviateVectorStore
from app.config import WEAVIATE_URL, WEAVIATE_API_KEY


# def get_weaviate_client():
#     """
#     Connect to Weaviate Cloud (WCS) using the v4 client.
#     Includes custom User-Agent for traceability.
#     """
#     client = connect_to_weaviate_cloud(
#         cluster_url=WEAVIATE_URL,
#         auth_credentials=WEAVIATE_API_KEY,
#         headers={"User-Agent": os.getenv("USER_AGENT", "Strategisthub-RAG/1.0")},
#     )
#     return client

from weaviate import connect_to_weaviate_cloud
import os

def get_weaviate_client():
    url = os.getenv("WEAVIATE_URL")
    api_key = os.getenv("WEAVIATE_API_KEY")

    try:
        client = connect_to_weaviate_cloud(
            cluster_url=url.replace("grpc-", "https://"),  # ensure https:// not grpc-
            auth_credentials=api_key,
            headers={"User-Agent": os.getenv("USER_AGENT", "Strategisthub-RAG/1.0")},
            skip_init_checks=True,  # ← disable gRPC health check
        )
        print("Connected to Weaviate (REST mode)")
        return client
    except Exception as e:
        print("Failed initial connect, retrying with extended timeout...", e)
        # timeout_cfg = init.AdditionalConfig(timeout=init.Timeout(init=30))
        # client = connect_to_weaviate_cloud(
        #     cluster_url=url.replace("grpc-", "https://"),
        #     auth_credentials=api_key,
        #     headers={"User-Agent": os.getenv("USER_AGENT", "Strategisthub-RAG/1.0")},
        #     additional_config=timeout_cfg,
        #     skip_init_checks=True,
        # )
        # print("Connected with extended timeout (REST mode)")
        # return client



def ensure_schema(client):
    """
    Ensure the StrategisthubDocs collection exists in Weaviate.
    """
    class_name = "StrategisthubDocs"

    if not client.collections.exists(class_name):
        client.collections.create(
            name=class_name,
            properties=[
                Property(name="page_content", data_type=DataType.TEXT),
                Property(name="source", data_type=DataType.TEXT),
                Property(name="creationdate", data_type=DataType.TEXT),
            ],
        )


def clean_metadata(docs):
    """
    Clean metadata before pushing to Weaviate.
    Removes invalid or empty creation dates and ensures string values.
    """
    cleaned_docs = []
    for doc in docs:
        meta = doc.metadata or {}

        # Remove invalid or empty creation date fields
        if "creationdate" in meta and not meta["creationdate"]:
            del meta["creationdate"]

        doc.metadata = meta
        cleaned_docs.append(doc)
    return cleaned_docs


def create_or_load_vectorstore(docs=None):
    """
    Create or load Weaviate vector store and optionally add new docs.
    Automatically handles schema creation and metadata cleanup.
    """
    client = get_weaviate_client()
    ensure_schema(client)

    embeddings = OpenAIEmbeddings()
    index_name = "StrategisthubDocs"

    vectorstore = WeaviateVectorStore(
        client=client,
        index_name=index_name,
        text_key="page_content",
        embedding=embeddings,
    )
    if docs:
        docs = clean_metadata(docs)
        try:
            print("Adding data...")
            vectorstore.add_documents(docs)
        except Exception as e:
            print("Failed to upload some documents:", e)
        finally:
            client.close()
    else:
        print("Did not received any doc!!!")

    return vectorstore.as_retriever(search_kwargs={"k": 3})


    # if client.collections.exists(index_name):
    #     print("Do you want to add more data to the collection? Y/n")
    #     inp = input().lower()
    #     if inp == 'y':
    #         if docs:
    #             docs = clean_metadata(docs)
    #             try:
    #                 vectorstore.add_documents(docs)
    #             except Exception as e:
    #                 print("Failed to upload some documents:", e)

    #         return vectorstore.as_retriever(search_kwargs={"k": 3})
    #     elif inp == "n":
    #         return vectorstore.as_retriever(search_kwargs={"k": 3})
    # return vectorstore.as_retriever(search_kwargs={"k": 3})

def load_vectorstore():
    """
    Create or load Weaviate vector store and optionally add new docs.
    Automatically handles schema creation and metadata cleanup.
    """
    client = get_weaviate_client()

    embeddings = OpenAIEmbeddings()
    collection_name = "StrategisthubDocs"

    vectorstore = WeaviateVectorStore(
        client=client,
        index_name=collection_name,
        text_key="page_content",
        embedding=embeddings,
    )
    try:
        if client.collections.exists(collection_name):    
            return vectorstore.as_retriever(search_kwargs={"k": 3})
    except Exception:
        print("ERROR")
    # return vectorstore.as_retriever(search_kwargs={"k": 3})


# import hashlib
# from weaviate import connect_to_weaviate_cloud
# from weaviate.classes.config import Property, DataType
# from langchain_openai import OpenAIEmbeddings
# from langchain_weaviate import WeaviateVectorStore
# from app.config import WEAVIATE_URL, WEAVIATE_API_KEY
# from weaviate.classes.query import Filter

# def hash_text(text: str) -> str:
#     return hashlib.sha256(text.encode("utf-8")).hexdigest()

# def get_weaviate_client():
#     return connect_to_weaviate_cloud(
#         cluster_url=WEAVIATE_URL,
#         auth_credentials=WEAVIATE_API_KEY,
#     )

# def create_or_load_vectorstore(docs):
#     print("🔗 Connecting to Weaviate Cloud...")
#     client = get_weaviate_client()
#     collection_name = "StrategisthubDocs"

#     existing_collections = [c.name for c in client.collections.list_all()]
#     if collection_name not in existing_collections:
#         print("🆕 Creating new collection in Weaviate...")
#         client.collections.create(
#             name=collection_name,
#             properties=[
#                 Property(name="text", data_type=DataType.TEXT),
#                 Property(name="source", data_type=DataType.TEXT),
#                 Property(name="doc_hash", data_type=DataType.TEXT),
#             ],
#             vectorizer_config=None,  # We’re using external embeddings
#         )
#     else:
#         print("📚 Using existing collection (no rebuild)")

#     collection = client.collections.get(collection_name)
#     embeddings = OpenAIEmbeddings()
#     inserted, skipped = 0, 0

#     for doc in docs:
#         text = doc.page_content.strip()
#         if not text:
#             continue

#         doc_hash = hash_text(text)
#         existing = collection.query.fetch_objects(
#             filters=Filter.by_property("doc_hash").equal(doc_hash),
#             limit=1
#         )

#         if existing.objects:
#             skipped += 1
#             continue

#         vector = embeddings.embed_query(text)
#         source = doc.metadata.get("source", "unknown")

#         collection.data.insert(
#             properties={
#                 "text": text,
#                 "source": source,
#                 "doc_hash": doc_hash,
#             },
#             vector=vector,
#         )
#         inserted += 1

#     print(f"✅ Added {inserted} new documents, skipped {skipped} duplicates.")
#     client.close()

#     retriever_client = get_weaviate_client()
#     vector_store = WeaviateVectorStore(
#         client=retriever_client,
#         index_name=collection_name,
#         text_key="text",
#         embedding=embeddings,
#     )

#     return vector_store.as_retriever(search_kwargs={"k": 2})

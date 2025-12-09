from langchain_community.document_loaders import PyPDFLoader, WebBaseLoader
from pathlib import Path

# def read_uploaded_file(file_path: str) -> str:
#     path = Path(file_path)
#     if not path.exists():
#         raise FileNotFoundError(f"File not found: {file_path}")

#     loader = PyPDFLoader(str(path))
#     docs = loader.load()
#     return "\n".join([doc.page_content for doc in docs])


def read_uploaded_file(file_path: str) -> str:
    """Read PDF file and return text content"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    loader = PyPDFLoader(str(path))
    docs = loader.load()
    return "\n".join([doc.page_content for doc in docs])


def load_pdfs_from_directory(directory_path: str):
    docs = []
    for pdf_file in Path(directory_path).rglob("*.pdf"):
        try:
            print("Reading data from: ", pdf_file)
            loader = PyPDFLoader(str(pdf_file))
            docs.extend(loader.load())
        except Exception as e:
            print(f"Error loading {pdf_file}: {e}")
    return docs

def load_from_websites(urls):
    docs = []
    for url in urls:
        loader = WebBaseLoader(url)
        docs.extend(loader.load())
    return docs

def clean_text(text: str) -> str:
    return text.replace("\x00", "")

def clean_metadata(meta):
    if isinstance(meta, dict):
        return {k: clean_text(v) if isinstance(v, str) else v for k, v in meta.items()}
    return meta
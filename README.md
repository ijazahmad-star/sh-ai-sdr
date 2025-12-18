# SH Smart AI Assistant - Backend API

## Project Overview

SH Smart AI Assistant is a FastAPI-based backend service that provides intelligent AI agent interactions, document processing, and conversation management. The system leverages Supabase for database operations and vector storage, enabling efficient document retrieval and conversational AI capabilities

### [SYSTEM ARCHITECTURE ](SystemArchitecture.md)

## Tech Stack

- Framework: FastAPI (Python 3.8+)
- Database: Supabase (PostgreSQL + Vector Storage)
- Document Processing: PDF extraction, text preprocessing, chunking
- Embeddings: Vector embeddings for semantic search

## Prerequisites

- Python 3.8 or higher
- uv package installer
- Supabase account and project
- PostgreSQL database with vector extension enabled
- API keys for AI services (OpenAI, Anthropic, etc.)

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/strategisthub/sh-ai-assistant.git
cd sh-ai-assistant

```

### 2. Install uv (if not already installed)

```bash
# On macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Alternative: Using pip
pip install uv

# Please explore official documentation for more details
```

### 3. Create Virtual Environment and Install Dependencies

```bash
# uv will automatically create a virtual environment and install dependencies
uv sync

# Or explicitly create environment and install
uv venv
source .venv/bin/activate  # On macOS/Linux
uv add -r requirements.txt
# On Windows: .venv\Scripts\activate
uv pip install -r pyproject.toml
```

### 4. Environment Configuration

Create a .env file in the root directory:

```bash
# Supabase Configuration
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_key
DATABASE_URL=your_database_connection_string

# AI Service Configuration
OPENAI_API_KEY=your_openai_api_key

ALLOWED_FILE_TYPES=pdf

# Vector Database Configuration
EMBEDDING_MODEL= OpenAIEmbeddings()
```

### 5. Database Setup

```sql
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
```

### 6. Perform Migrations

```bash
# To perform this actions must use Session Pooler connection string
# sqlalchemy.url = "your session connection string" in the file alembic.ini
uv pip install -r requirements.txt
# Following command will generate a migrations folder
alembic init migrations
# This will run initial migrations
alembic revision --autogenerate -m "initial schema"
# To make changes available on supabase
alembic upgrade head
# if tables are already there use following command
alembic stamp head
```

## Project Structure

```text
sh-smart-ai-assistant/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── data_loader.py
│   ├── graph_builder.py
│   ├── schema.py
│   ├── tools.py
|   ├── models.py                   # contain all the tables - for auto generate tables on supabase
│   ├── ui.py                       # just for testing
│   ├── vectorstore_supabas.py      # handle supabase db
│   ├── vectorstore_weaviate.py     # hanlde weaviate db, if you want to switch
│   ├── vectorstore.py              # handle faiss db
├── notebooks/
│   ├── advance-RAG.ipynb
│   ├──customize_gpt.ipynb
└── main.py
├── pyproject.toml          # uv uses pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

## Running the Application with uv

```bash
# Activate the virtual environment (uv creates .venv by default)
source .venv/bin/activate  # On macOS/Linux
# On Windows: .venv\Scripts\activate

# Or run directly with uv
uvicorn app.main:app --reload

```

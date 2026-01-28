# System Architecture Diagram

Here's the comprehensive system architecture:

```text
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM ARCHITECTURE DIAGRAM                                 │
│                      AI Platform with Admin Management                              │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER (Next.js Frontend)                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   Login Page    │  │   Dashboard     │  │   AI Chat       │  │   System Prompts│ │
│  │                 │  │                 │  │                 │  │                 │ │
│  │ - Auth Check    │  │ - Stats Overview│  │ - Query Input   │  │ -CRUD Operations│ │
│  │ - Redirect      │  │ - Navigation    │  │ - Response      │  │ - Prompt        │ │
│  │                 │  │                 │  │ Display         │  │ Management      │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│                                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                      │
│  │ Knowledge Base  │  │   User Mgmt     │  │                 │                      │
│  │                 │  │  (Admin Only)   │  │                 │                      │
│  │ - File Upload   │  │ - Create Users  │  │                 │                      │
│  │ - Document List │  │ - Delete Users  │  │ - Sign Out      │                      │
│  │ - Download/Delete│ │ - DB Access Ctrl│  │                 │                      │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘                      │
│                                                                                     │
└───────────────────────────────┬─────────────────────────────────────────────────────┘
                                │
                                │ HTTPS/API Calls
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                             BACKEND LAYER                                           │
├───────────────────────────────┬─────────────────────────────────────────────────────┤
│                                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                     Next.js API Routes                                      │   │
│   │  (Handles: User Conversations & Admin User Management)                      │   │
│   │                                                                             │   │
│   │  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                  │   │
│   │  │ /api/auth   │      │ /api/convers│      │ /api/admin  │                  │   │
│   │  │             │      │ ations      │      │             │                  │   │
│   │  │ - Session   │      │ - CRUD Ops  │      │ - User CRUD │                  │   │
│   │  │ Management  │      │ - List/Store│      │ - DB Access │                  │   │
│   │  │             │      │ Conversations│     │  Control    │                  │   │
│   │  └─────────────┘      └─────────────┘      └─────────────┘                  │   │
│   └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────────────┐   │
│   │                   FastAPI + Python Backend                                  │   │
│   │          (Separate Service - External API Calls)                            │   │
│   │                                                                             │   │
│   │  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                  │   │
│   │  │ /api/ai     │      │ /api/prompts│      │ /api/knowledge                 │   │
│   │  │             │      │             │      │             │                  │   │
│   │  │ - AI Query  │      │ - System    │      │ - File Upload│                 │   │
│   │  │ Processing  │      │ Prompt CRUD │      │ - Document   │                 │   │
│   │  │ - LLM       │      │ Operations  │      │ Management   │                 │   │
│   │  │ Integration │      │             │      │ - Vector DB  │                 │   │
│   │  │             │      │             │      │  Operations  │                 │   │
│   │  └─────────────┘      └─────────────┘      └─────────────┘                  │   │
│   └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
└───────────────────────────────┬─────────────────────────────────────────────────────┘
                                │
                                │ Database Operations
                                ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER (Supabase PostgreSQL)                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌───────────────────────────────────────────────────────────────────────────────┐  │
│  │                               Database Tables                                 │  │
│  │                                                                               │  │
│  │  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐                 │  │
│  │  │   users      │      │ conversations│      │  prompts     │                 │  │
│  │  │              │      │              │      │              │                 │  │
│  │  │ - id         │      │ - id         │      │ - id         │                 │  │
│  │  │ - email      │      │ - user_id    │      │ - user_id    │                 │  │
│  │  │ - password   │      │ - messages   │      │ - content    │                 │  │
│  │  │ - role       │      │ - created_at │      │ - type       │                 │  │
│  │  │ - created_at │      │ - updated_at │      │ - created_at │                 │  │
│  │  │ - is_active  │      │              │      │              │                 │  │
│  │  └──────────────┘      └──────────────┘      └──────────────┘                 │  │
│  │                                                                               │  │
│  │  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐                 │  │
│  │  │  documents   │      │   KB_Aceess  │      | messages     |                 │  │
│  │  │              │      │              │      |  -id         |                 │  │
│  │  │ - id         │      │ - id         │      |  -conv_id    |                 │  │
│  │  │ - user_id    │      │ - user_id    │      |  -user_id    |                 │  │
│  │  │ - filename   │      │ - hasAccess  │      |  -role       |                 │  │
│  │  │ - file_path  │      │              │      |  -content    |                 │  │
│  │  │ - uploaded_at│      │ - timestamp  │      |              |                 │  │
│  │  │ - size       │      │              │      |              |                 │  │
│  │  │ - metadata   │      │              │      |              |                 │  │
│  │  └──────────────┘      └──────────────┘      └──────────────┘                 │  │
│  │                                                                               │  │
│  └───────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL INTEGRATIONS                                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌──────────────┐          ┌──────────────┐          ┌──────────────┐               │
│  │   AI/LLM     │          │ File Storage │          │ Authentication│              │
│  │   Service    │◄────────►│   Service    │◄────────►│   Service    │               │
│  │              │          │              │          │              │               │
│  │ - OpenAI     │          │ - Supabase   │          │ - Supabase   │               │
│  │              │          │   Storage    │          │   Auth       │               │
│  │              │          │              │          │ - Credential │               │
│  │              │          │              │          │    Auth      │               │
│  └──────────────┘          └──────────────┘          └──────────────┘               │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           FLOW SUMMARY                                              │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  1. Authentication Flow:                                                            │
│     End User → Login Page → Supabase Auth → Dashboard (Role-based redirect)         │
│                                                                                     │
│  2. Admin User Management:                                                          │
│     Admin → User Management → Next.js API → Supabase DB → Update user permissions   │
│                                                                                     │
│  3. AI Chat Flow:                                                                   │
│     User → Query Input → FastAPI Backend → AI Service → Response → Display          │
│     Conversation History → Next.js API → Supabase DB                                │
│                                                                                     │
│  4. System Prompts:                                                                 │
│     User → Prompt CRUD → FastAPI Backend → Supabase DB → Updated List               │
│                                                                                     │
│  5. Knowledge Base:                                                                 │
│     User → Upload PDF → FastAPI Backend → File Storage + DB → Document List Update  │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Key Architecture Components:

### 1. Frontend (Next.js)

- Pages: Login, Dashboard, AI Chat, System Prompts, Knowledge Base, Admin Panel
- Components: Sidebar with conversations, Document list, Chat interface
- API Routes: Handles conversations and admin user management

### 2. Backend Services

- Next.js API Routes: Manages user conversations and admin operations
- FastAPI + Python Service: Separate service for AI operations, prompt management, and document processing

### 3. Database (Supabase PostgreSQL)

- Single database for all services
- Tables: users, conversations, prompts, documents, messages, kb_access

### 4. Authentication & Authorization

- Supabase/Credentials Auth for user authentication
- Role-based access control (Admin vs Regular User)
- Admin-specific permissions for user management

### 5. Data Flow Separation

- Conversations: Frontend (Next.js) → Next.js API → Supabase DB
- Messages: Frontend (Next.js) → Next.js API → Supabase DB
- AI Processing: Frontend → FastAPI → AI Service → Response

### 6. Admin Privileges

- Create/delete users
- Control database access permissions
- Access to all regular user features plus admin-specific functions

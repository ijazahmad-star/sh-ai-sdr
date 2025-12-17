from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID, uuid4
from sqlalchemy import Column, DateTime, text, JSON
from sqlmodel import Field, SQLModel, Relationship, create_engine
from pgvector.sqlalchemy import Vector # For Supabase Vector support

class User(SQLModel, table=True):
    __tablename__ = "users"
    
    id: str = Field(primary_key=True)
    email: str = Field(index=True, unique=True)
    name: Optional[str] = None
    image: Optional[str] = None
    emailVerified: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=False)))
    createdAt: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime, server_default=text("CURRENT_TIMESTAMP")))
    updatedAt: datetime = Field(sa_column=Column(DateTime, onupdate=text("CURRENT_TIMESTAMP")))
    password: Optional[str] = None
    role: str = Field(default="user")

    # Relationships
    files: List["UserFile"] = Relationship(back_populates="user")
    prompts: List["Prompt"] = Relationship(back_populates="user")
    conversations: List["Conversation"] = Relationship(back_populates="user")
    kb_access: Optional["KBAccess"] = Relationship(back_populates="user")

class UserFile(SQLModel, table=True):
    __tablename__ = "user_files"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: str = Field(foreign_key="users.id", ondelete="CASCADE")
    filename: str
    storage_path: str
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

    user: User = Relationship(back_populates="files")
    documents: List["Document"] = Relationship(back_populates="file")

class Prompt(SQLModel, table=True):
    __tablename__ = "prompts"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: Optional[str] = Field(default=None, foreign_key="users.id", ondelete="CASCADE")
    prompt: str
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)
    is_active: Optional[bool] = True
    name: Optional[str] = None

    user: Optional[User] = Relationship(back_populates="prompts")

class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    
    id: str = Field(primary_key=True)
    title: Optional[str] = "New Chat"
    userId: str = Field(foreign_key="users.id", ondelete="CASCADE")
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(sa_column=Column(DateTime, onupdate=text("CURRENT_TIMESTAMP")))

    user: User = Relationship(back_populates="conversations") 
    messages: List["Message"] = Relationship(back_populates="conversation")

class Message(SQLModel, table=True):
    __tablename__ = "messages"
    
    id: str = Field(primary_key=True)
    conversationId: str = Field(foreign_key="conversations.id", ondelete="CASCADE")
    userId: str = Field(foreign_key="users.id", ondelete="CASCADE")
    role: str
    content: str
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    sources: Optional[Any] = Field(default=None, sa_column=Column(JSON))

    conversation: Conversation = Relationship(back_populates="messages")

class KBAccess(SQLModel, table=True):
    __tablename__ = "kb_access"
    
    id: str = Field(primary_key=True)
    userId: str = Field(foreign_key="users.id", unique=True, ondelete="CASCADE")
    hasAccessToDefaultKB: bool = Field(default=False)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(sa_column=Column(DateTime, onupdate=text("CURRENT_TIMESTAMP")))

    user: User = Relationship(back_populates="kb_access")

class Document(SQLModel, table=True):
    __tablename__ = "documents"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: Optional[str] = Field(default=None, foreign_key="users.id", ondelete="CASCADE")
    content: str
    document_metadata: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    embedding: Optional[Any] = Field(default=None, sa_column=Column(Vector(1536)))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    file_id: Optional[UUID] = Field(default=None, foreign_key="user_files.id", ondelete="CASCADE")

    user: Optional[User] = Relationship()
    file: Optional[UserFile] = Relationship(back_populates="documents")


from mcp.server.fastmcp import FastMCP

from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from pathlib import Path
from tempfile import mkdtemp

from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.readers.docling import DoclingReader
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.core import Settings




from docling_core.types.doc.document import (
    DoclingDocument,
    NodeItem,
    # DocItem,
    # GroupItem
)

# Create a single shared FastMCP instance
mcp = FastMCP("docling")

# Define your shared cache here if it's used by multiple tools
local_document_cache: dict[str, DoclingDocument] = {}
local_stack_cache: dict[str, list[NodeItem]] = {}


Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")
Settings.llm = Ollama(model="granite3.2:latest", request_timeout=120.0)
MILVUS_URI = str(Path(mkdtemp()) / "docling.db")

reader = DoclingReader()
node_parser = MarkdownNodeParser()

db = chromadb.PersistentClient(path="./chroma_db")

chroma_collection = db.get_or_create_collection("quickstart")

vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

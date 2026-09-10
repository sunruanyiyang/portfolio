"""Global configuration: API keys, model names and retrieval parameters.

All values used across the pipeline are centralised here so that a single
file controls the behaviour of extraction, classification, routing,
retrieval and question answering.
"""

import os

# ---------------------------------------------------------------------------
# Google Gemini API
# ---------------------------------------------------------------------------
# NEVER hard-code a real API key in this file. Read it from the environment
# instead: set GOOGLE_API_KEY before running, or use Colab Secrets / a .env.
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
if GOOGLE_API_KEY:
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY

# LLM used for classification, routing, query rewriting and final answering.
# "models/gemini-3.1-flash-lite" is fast and cheap; "models/gemini-pro" is a
# heavier alternative if higher reasoning quality is required.
LLM_MODEL = "models/gemini-3.1-flash-lite"

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
# bge-small-en-v1.5 is a compact, strong English embedding model.
# Alternative used during the experiments: "sentence-transformers/all-MiniLM-L6-v2".
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# ---------------------------------------------------------------------------
# Chunking parameters
# ---------------------------------------------------------------------------
CHUNK_SIZE = 512            # Target characters per chunk
CHUNK_OVERLAP = 60          # Characters shared between neighbouring chunks
LOGICAL_CHUNK_OVERLAP = 100  # Overlap used when splitting logical documents

# ---------------------------------------------------------------------------
# Retrieval parameters
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 4           # Number of chunks handed to the LLM as context
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_TOP_N = 3            # How many chunks survive reranking
SIMILARITY_THRESHOLD = -15.0  # Score floor: weaker chunks are discarded

# ---------------------------------------------------------------------------
# Document types handled by the classifier / router
# ---------------------------------------------------------------------------
DOC_TYPE_OPTIONS = [
    "Cover Letter",
    "Certificate of Quality",
    "Packaging Specification",
    "BSE/TSE Declaration",
    "Material Description",
    "Supplier Qualification",
    "Chain of Custody",
    "Other",
]


def get_llm():
    """Build the Gemini LLM used across the pipeline (lazy factory)."""
    from llama_index.llms.gemini import Gemini

    return Gemini(model=LLM_MODEL)


def get_embed_model():
    """Build the HuggingFace embedding model used across the pipeline."""
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)

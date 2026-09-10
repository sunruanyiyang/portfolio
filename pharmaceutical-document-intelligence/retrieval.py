"""Retrieval: chunking, embeddings, vector / BM25 hybrid search and reranking.

Contains the highest-value technical pieces of the project:
  * fixed-size / overlapping / semantic chunking
  * embedding generation
  * pure vector retrieval
  * hybrid retrieval (vector + BM25 keyword search)
  * cross-encoder reranking
  * score-threshold filtering
  * metadata-filtered retrieval
"""

from dataclasses import dataclass
from typing import List

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.node_parser import SemanticSplitterNodeParser, SentenceSplitter
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.retrievers.bm25 import BM25Retriever

from src.config import (
    DEFAULT_TOP_K,
    RERANK_MODEL,
    RERANK_TOP_N,
    SIMILARITY_THRESHOLD,
)


@dataclass
class ChunkMetadata:
    """Typed metadata attached to every retrieved chunk."""

    text: str
    doc_type: str = "unknown"
    page_start: int = 0
    page_end: int = 0
    source_file: str = ""
    chunk_index: int = 0
    score: float = 0.0


def create_fixed_chunks(documents: List[Document], chunk_size: int, chunk_overlap: int) -> List:
    """Fixed-size chunking, optionally with overlap."""
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.get_nodes_from_documents(documents)


def create_semantic_chunks(documents: List[Document], embed_model) -> List:
    """Semantic chunking: split where the embedding similarity drops."""
    splitter = SemanticSplitterNodeParser(embed_model=embed_model)
    return splitter.get_nodes_from_documents(documents)


def generate_embeddings(nodes: List, embed_model) -> None:
    """Compute an embedding for every node in place."""
    for node in nodes:
        node.embedding = embed_model.get_text_embedding(node.text)
    print("Embeddings Generated Successfully!")


def build_index(documents: List[Document], embed_model) -> VectorStoreIndex:
    """Build a vector index over the given documents."""
    return VectorStoreIndex.from_documents(documents, embed_model=embed_model)


def retrieve(query: str, index: VectorStoreIndex, top_k: int = DEFAULT_TOP_K) -> List:
    """Pure vector retrieval."""
    retriever = index.as_retriever(similarity_top_k=top_k)
    return retriever.retrieve(query)


def hybrid_retrieve(query: str, index: VectorStoreIndex, top_k: int = DEFAULT_TOP_K) -> List:
    """Hybrid retrieval: vector search + BM25 keyword search, merged and sorted."""
    # Vector search
    vector_retriever = index.as_retriever(similarity_top_k=top_k)
    vector_nodes = vector_retriever.retrieve(query)

    # Keyword search over the same node store
    try:
        nodes = list(index.docstore.docs.values())
    except AttributeError:
        # Fallback for llama-index versions with a different docstore API
        nodes = list(index.docstore.get_all().values())
    bm25_retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=top_k)
    keyword_nodes = bm25_retriever.retrieve(query)

    # Merge results from both retrievers
    all_nodes = list(vector_nodes) + list(keyword_nodes)

    # Remove duplicate nodes (same node_id)
    unique_nodes = {}
    for node in all_nodes:
        if node.node_id not in unique_nodes:
            unique_nodes[node.node_id] = node

    # Sort by relevance score, highest first
    sorted_nodes = sorted(
        unique_nodes.values(),
        key=lambda x: x.score if hasattr(x, "score") else 0.0,
        reverse=True,
    )

    return sorted_nodes[:top_k]


def rerank(query: str, nodes: List, top_n: int = RERANK_TOP_N) -> List:
    """Re-rank the retrieved chunks with a cross-encoder."""
    reranker = SentenceTransformerRerank(model=RERANK_MODEL, top_n=top_n)
    return reranker.postprocess_nodes(nodes, query_str=query)


def filter_by_score(nodes: List, threshold: float = SIMILARITY_THRESHOLD) -> List:
    """Keep only nodes whose relevance score is above the threshold."""
    return [n for n in nodes if n.score and n.score > threshold]


def retrieve_with_filters(
    query: str,
    index: VectorStoreIndex,
    doc_type: str,
    top_k: int = DEFAULT_TOP_K,
) -> List:
    """Retrieve only within chunks matching a document type (metadata filter)."""
    from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters

    retriever = index.as_retriever(
        similarity_top_k=top_k,
        filters=MetadataFilters(
            filters=[
                MetadataFilter(
                    key="doc_type",
                    value=doc_type,
                    operator=FilterOperator.EQ,
                )
            ]
        ),
    )
    return retriever.retrieve(query)  # Search within the matched chunks

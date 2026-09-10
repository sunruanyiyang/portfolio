"""Question-answering pipeline: Question -> Retrieval -> Context -> LLM -> Answer."""

from typing import List, Optional, Tuple

from llama_index.core import Document, VectorStoreIndex

from src.config import DEFAULT_TOP_K, get_embed_model, get_llm
from src.document_classification import classify_pages_json
from src.document_extraction import load_pages
from src.retrieval import (
    ChunkMetadata,
    build_index,
    filter_by_score,
    hybrid_retrieve,
    rerank,
    retrieve_with_filters,
)
from src.routing import build_logical_documents, chunk_logical_documents, route_query

# Short descriptions the router can use to pick the most relevant document type
DOC_TYPE_DESCRIPTIONS = [
    {"doc_type": "Certificate of Quality", "text_excerpt": "Certificate of Quality for Lot 2023-A"},
    {"doc_type": "BSE/TSE Declaration", "text_excerpt": "BSE/TSE Declaration for raw material supplier"},
    {"doc_type": "Packaging Specification", "text_excerpt": "Packaging Specification for product line Alpha"},
]


def _generate_text(llm, prompt: str) -> str:
    """Run a prompt through the LLM and return plain text."""
    if callable(llm):
        return str(llm(prompt)).strip()
    if hasattr(llm, "complete"):
        return llm.complete(prompt).text.strip()
    if hasattr(llm, "generate_content"):
        return llm.generate_content(prompt).text.strip()
    raise TypeError("llm must be callable or expose complete()/generate_content()")


def rewrite_query(user_query: str, llm) -> str:
    """Rewrite a user query so it matches the retrieval index better."""
    from llama_index.core.llms import ChatMessage

    messages = [
        ChatMessage(role="system", content="Rewrite this query for improved retrieval relevance."),
        ChatMessage(role="user", content=user_query),
    ]
    response = llm.chat(messages)
    return response.message.content


def _extract_doc_type(route_answer: str, options: Optional[List[str]] = None) -> Optional[str]:
    """Heuristic: pick the first known document type mentioned by the router."""
    options = options or [
        "Cover Letter",
        "Certificate of Quality",
        "Packaging Specification",
        "BSE/TSE Declaration",
        "Material Description",
        "Supplier Qualification",
        "Chain of Custody",
        "Other",
    ]
    lowered = route_answer.lower()
    for opt in options:
        if opt.lower() in lowered:
            return opt
    return None


class DocumentQA:
    """End-to-end QA system over a set of pharmaceutical PDF documents."""

    def __init__(self, llm, index: VectorStoreIndex, doc_descriptions: Optional[List[dict]] = None):
        self.llm = llm
        self.index = index
        self.doc_descriptions = doc_descriptions or DOC_TYPE_DESCRIPTIONS

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        k: int = DEFAULT_TOP_K,
        filter_doc_type: Optional[str] = None,
        auto_route: bool = True,
    ) -> List[Tuple[ChunkMetadata, float]]:
        """Retrieve relevant chunks with optional filtering and routing.

        Returns chunks with relevance scores.
        """
        # Decide which document type to search inside
        if filter_doc_type:
            target_type = filter_doc_type
        elif auto_route:
            # Let the LLM predict the most relevant document type first
            route_answer = route_query(query, self.doc_descriptions, self.llm)
            target_type = _extract_doc_type(route_answer)
        else:
            target_type = None

        # Search: metadata-filtered retrieval or full hybrid retrieval
        if target_type:
            nodes = retrieve_with_filters(query, self.index, target_type, top_k=k)
        else:
            nodes = hybrid_retrieve(query, self.index, top_k=k)

        # Rerank and keep only the strongest hits
        if nodes:
            nodes = rerank(query, nodes, top_n=k)
            nodes = filter_by_score(nodes)

        # Convert nodes into typed chunks carrying their scores
        retrieved_chunks: List[Tuple[ChunkMetadata, float]] = []
        for node in nodes:
            meta = node.metadata or {}
            chunk = ChunkMetadata(
                text=node.text,
                doc_type=meta.get("doc_type", "unknown"),
                page_start=meta.get("page_start", 0),
                page_end=meta.get("page_end", 0),
                source_file=meta.get("source_file", ""),
                score=node.score or 0.0,
            )
            retrieved_chunks.append((chunk, node.score or 0.0))
        return retrieved_chunks

    # ------------------------------------------------------------------
    # Answer generation
    # ------------------------------------------------------------------
    def answer_question(
        self,
        query: str,
        k: int = DEFAULT_TOP_K,
        filter_doc_type: Optional[str] = None,
        auto_route: bool = True,
    ) -> dict:
        """Answer a question from the retrieved context and return sources."""
        retrieved_chunks = self.retrieve(
            query, k=k, filter_doc_type=filter_doc_type, auto_route=auto_route
        )

        if not retrieved_chunks:  # Return an empty result when nothing matches
            return {
                "answer": "I couldn't find relevant information to answer your question.",
                "sources": [],
                "confidence": 0.0,
                "chunks_used": 0,
            }

        # Build the context and the source list from the retrieved chunks
        context_parts = []
        sources = []
        for chunk_meta, score in retrieved_chunks:
            context_parts.append(
                f"[From {chunk_meta.doc_type}, Pages {chunk_meta.page_start}-{chunk_meta.page_end}]"
            )
            context_parts.append(chunk_meta.text)
            context_parts.append("")
            sources.append(
                {
                    "doc_type": chunk_meta.doc_type,
                    "page_start": chunk_meta.page_start,
                    "page_end": chunk_meta.page_end,
                    "source_file": chunk_meta.source_file,
                    "score": round(score, 4),
                }
            )

        prompt = f"""You are a pharmaceutical document assistant. Answer the question using ONLY the context below.
If the context does not contain the answer, say you could not find it.

Context:
{chr(10).join(context_parts)}

Question: {query}
Answer:"""

        # Ask the model
        answer = _generate_text(self.llm, prompt)

        # Compute confidence as the average retrieval score
        avg_score = sum(score for _, score in retrieved_chunks) / len(retrieved_chunks)

        return {
            "answer": answer,
            "sources": sources,
            "confidence": avg_score,
            "chunks_used": len(retrieved_chunks),
        }


def build_document_qa(pdf_path: str, llm=None, embed_model=None) -> DocumentQA:
    """Build the full pipeline: extract -> classify -> group -> chunk -> embed -> index."""
    from llama_index.core import Settings
    from llama_index.core.node_parser import SentenceSplitter

    from src.config import CHUNK_OVERLAP, CHUNK_SIZE

    llm = llm or get_llm()
    embed_model = embed_model or get_embed_model()

    # Global defaults used across the pipeline
    Settings.embed_model = embed_model
    Settings.node_parser = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    Settings.llm = llm

    # 1) Extract pages from the PDF
    pages = load_pages(pdf_path)

    # 2) Classify every page (boundary + document type)
    classified = classify_pages_json(pages, llm)
    if classified:
        classified[0]["is_new_doc"] = "Yes"  # The first page always starts a document
    for page, cls in zip(pages, classified):
        page["is_new_doc"] = cls["is_new_doc"]
        page["doc_type"] = cls["doc_type"]

    # 3) Group consecutive pages into logical documents
    logical_documents = build_logical_documents(pages, source_file=pdf_path)

    # 4) Chunk the logical documents and attach their metadata
    chunks = chunk_logical_documents(logical_documents)
    if not chunks:
        raise ValueError("No content could be extracted from the PDF.")

    # 5) Build LlamaIndex documents, then embed and index them
    docs = [
        Document(
            text=chunk.text,
            metadata={
                "doc_type": chunk.doc_type,
                "chunk_index": chunk.chunk_index,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "source_file": chunk.source_file,
            },
        )
        for chunk in chunks
    ]
    index = build_index(docs, embed_model)

    return DocumentQA(llm=llm, index=index)

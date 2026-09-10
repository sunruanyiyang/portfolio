"""Query routing and metadata-based narrowing.

Routing is different from classification:
  * Classification answers: "what type of document is this?"
  * Routing answers:      "given the user question, which document type
                           (or file) is most likely to contain the answer?"

This module also owns the metadata store and the logical-document builder,
because both exist to narrow the retrieval space before searching.
"""

import uuid
from typing import Dict, List

from langchain.text_splitter import RecursiveCharacterTextSplitter

from src.config import CHUNK_SIZE, LOGICAL_CHUNK_OVERLAP
from src.retrieval import ChunkMetadata


def _generate_text(llm, prompt: str) -> str:
    """Run a prompt through the LLM and return plain text."""
    if callable(llm):
        return str(llm(prompt)).strip()
    if hasattr(llm, "complete"):
        return llm.complete(prompt).text.strip()
    if hasattr(llm, "generate_content"):
        return llm.generate_content(prompt).text.strip()
    raise TypeError("llm must be callable or expose complete()/generate_content()")


def build_metadata_store(documents: List[dict], filename: str, year: str = "", user_id: str = "xyz") -> List[dict]:
    """Attach file-level metadata to every page of a document.

    Each entry stores: file_id, user_id, doc_type, year, filename,
    page_number and the raw page text.
    """
    file_id = str(uuid.uuid4())  # Assign a unique ID per uploaded file
    metadata_store = []
    for i, doc in enumerate(documents):
        metadata = {
            "file_id": file_id,
            "user_id": user_id,
            "doc_type": "unknown",
            "year": year,
            "filename": filename,
            "page_number": i + 1,
            "text": doc["text"],
        }
        metadata_store.append(metadata)
    print("Stored Metadata:")
    print(metadata_store[0])
    return metadata_store


def route_query(query: str, document_descriptions: List[dict], llm) -> str:
    """Let the LLM predict which document type is most likely to answer."""
    prompt = f"""
User Query: "{query}"
Here are the documents available:
{document_descriptions}
Based on the query, which document(s) are most likely to contain the answer?
Return a list of filenames or indices.
"""
    response = _generate_text(llm, prompt)
    return response


def retrieve_files_by_doc_type(doc_type: str, metadata_store: List[dict]) -> List[dict]:
    """Use metadata to fetch the most relevant files of a given type."""
    return [doc for doc in metadata_store if doc["doc_type"] == doc_type]


def build_logical_documents(pages: List[dict], source_file: str) -> List[dict]:
    """Group consecutive pages of the same document type into logical docs.

    Each logical document records its own text plus the page range
    (page_start / page_end), the document type and the source file.
    """
    logical_documents = []
    current_doc = None
    for page in pages:  # Group pages with the same doc type into one logical document
        if page.get("is_new_doc") == "Yes":
            if current_doc:
                logical_documents.append(current_doc)
            current_doc = {
                "text": page["text"],
                "doc_type": page["doc_type"],
                "page_start": page["page_num"],
                "page_end": page["page_num"],
                "source_file": source_file,
            }
        else:
            current_doc["text"] += "\n\n" + page["text"]
            current_doc["page_end"] = page["page_num"]
    if current_doc:
        logical_documents.append(current_doc)
    return logical_documents


def chunk_logical_documents(logical_documents: List[dict]) -> List[ChunkMetadata]:
    """Chunk every logical document and attach its metadata to each chunk."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=LOGICAL_CHUNK_OVERLAP,
    )
    all_chunks = []
    for doc in logical_documents:
        chunks = splitter.split_text(doc["text"])
        for i, chunk in enumerate(chunks):
            all_chunks.append(
                ChunkMetadata(
                    text=chunk,
                    doc_type=doc["doc_type"],
                    chunk_index=i,
                    page_start=doc["page_start"],
                    page_end=doc["page_end"],
                    source_file=doc["source_file"],
                    score=0.0,
                )
            )
    return all_chunks


def build_metadata_filters(doc_type: str):
    """Build LlamaIndex metadata filters for a given document type."""
    from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters

    return MetadataFilters(
        filters=[
            MetadataFilter(
                key="doc_type",
                value=doc_type,
                operator=FilterOperator.EQ,
            )
        ]
    )

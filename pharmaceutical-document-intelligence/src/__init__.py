"""Pharmaceutical Document Intelligence.

An end-to-end RAG pipeline that turns a batch of pharmaceutical PDF
documents into a searchable, question-answering chatbot:

    PDF -> Text Extraction -> Document Classification -> Metadata
        -> Chunking -> Embeddings -> Routing -> Hybrid Retrieval
        -> Reranking -> LLM -> Answer + Sources -> Gradio UI
"""

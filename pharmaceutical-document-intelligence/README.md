# Pharmaceutical Document Intelligence System

## Overview

As part of an AI-focused externship, I worked on a document intelligence workflow designed for pharmaceutical documentation.

The project explored how AI can process large and partially unstructured documents, from PDF text extraction and OCR to information retrieval, RAG, LLM-based question answering, and interactive chatbot interfaces.

The final goal was to integrate these components into an end-to-end document processing pipeline.

---

## What I Worked On

### 1. PDF Text Extraction

Used Python libraries such as PyMuPDF and pdfplumber to extract text from multi-page pharmaceutical documents.

I also explored rule-based methods, including regular expressions, anchor phrases, and layout information, to identify structured fields such as:

- Document dates
- Vendor names
- Document types
- Other relevant metadata

---

### 2. OCR

Compared several OCR approaches for scanned pharmaceutical documents:

- Tesseract
- PaddleOCR
- EasyOCR

The goal was to understand how different OCR systems handled scanned documents and preserved useful text and layout information.

---

### 3. RAG Pipeline

Built a Retrieval-Augmented Generation (RAG) workflow using LlamaIndex.

The pipeline included:

**Document → Text Extraction → Chunking → Embedding → Retrieval → LLM Response**

I experimented with:

- Different chunking strategies
- Chunk overlap
- Metadata-based filtering
- Different embedding models
- Open-source and proprietary LLMs

---

### 4. LLM Chatbot

Connected the retrieval pipeline to an LLM to allow users to ask questions about the documents.

I also explored building a simple interactive interface using Gradio.

The workflow became:

**User Question → Retrieval → Relevant Document Context → LLM → Answer**

---

## Technologies

- Python
- PyMuPDF
- pdfplumber
- Tesseract
- PaddleOCR
- EasyOCR
- LlamaIndex
- RAG
- Embeddings
- LLMs
- Gradio
- Google Gemini

---

## My Experience

This externship gave me hands-on experience working with both structured and unstructured data.

I learned how document processing systems combine traditional programming techniques, such as regular expressions and data preprocessing, with modern AI techniques such as embeddings, retrieval, and large language models.

I was particularly interested in how the different stages of the pipeline depend on each other: poor document extraction can affect embeddings, retrieval quality can affect the final answer, and model selection can affect both performance and usability.

---

## Project Pipeline

The overall workflow can be summarized as:

**Pharmaceutical PDF**

↓  

**PDF / OCR Processing**

↓

**Text Cleaning & Structuring**

↓

**Chunking + Embeddings**

↓

**Vector Retrieval**

↓

**RAG + LLM**

↓

**Interactive Chatbot**

---

## What I Learned

- How to preprocess and clean real-world document data
- How OCR systems differ in practical document-processing tasks
- How RAG systems retrieve relevant context for LLMs
- How chunking and metadata can affect retrieval quality
- How to connect an LLM pipeline to an interactive user interface
- How multiple AI components can be integrated into a single end-to-end workflow

---

## Code

The implementation and experiments are included in this repository.

More documentation and selected code examples will be added as the project is organized.

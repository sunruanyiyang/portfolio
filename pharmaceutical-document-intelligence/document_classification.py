"""Page-level document classification.

Decides two things for every page:
  1. Whether it starts a new document (page boundary detection)
  2. Which document type it belongs to

Two implementations are provided:
  * classify_pages()      - plain text answers ("Yes"/"No" + type name)
  * classify_pages_json() - structured JSON answers (higher accuracy)
"""

import json
from typing import Dict, List

from src.config import DOC_TYPE_OPTIONS

# The fixed set of document types the classifier may return
DOC_TYPES = DOC_TYPE_OPTIONS


def _generate_text(llm, prompt: str) -> str:
    """Run a prompt through the LLM and always return plain text.

    Supports a callable (prompt -> str), llama-index style LLMs exposing
    .complete() / .chat(), and google-genai style models exposing
    .generate_content().
    """
    if callable(llm):
        return str(llm(prompt)).strip()

    if hasattr(llm, "complete"):
        return llm.complete(prompt).text.strip()

    if hasattr(llm, "generate_content"):
        return llm.generate_content(prompt).text.strip()

    raise TypeError("llm must be a callable or expose complete()/generate_content()")


def is_same_document(prev_text: str, curr_text: str, doc_type: str | None, llm) -> bool:
    """Check whether two consecutive pages belong to the same document."""
    prompt = f"""
You are checking whether two pages belong to the same document. Previous page type: {doc_type or 'unknown'}
Previous Page:
{prev_text}
Current Page:
{curr_text}
Respond with only: Yes or No. Do not explain or add commentary.
"""
    response = _generate_text(llm, prompt)  # Ask the LLM
    return response.lower().startswith("yes")


def classify_document_type(text: str, llm) -> str:
    """Classify the content of a page into one of the predefined types."""
    prompt = f"""
This is the start of a new document. Based on the content, classify it.
Page Content:
{text}
Choose from: {", ".join(DOC_TYPES)}. Just respond with the type.
"""
    response = _generate_text(llm, prompt).lower().replace(".", "")
    return response.title()  # Normalise the answer to title case


def classify_pages(pages: List[dict], llm) -> List[dict]:
    """Iterate over all pages, detect boundaries and assign document types."""
    results = []
    current_doc_type = None
    doc_counter = 0

    for i, page in enumerate(pages):  # Iterate over every page
        if i == 0:  # Handle the first page: it always starts a new document
            current_doc_type = classify_document_type(page["text"], llm)
        else:
            # Check whether the remaining pages continue the same document
            prev_text = pages[i - 1]["text"]
            same = is_same_document(prev_text, page["text"], current_doc_type, llm)
            if not same:
                doc_counter += 1
                current_doc_type = classify_document_type(page["text"], llm)

        results.append(
            {
                "page_num": page["page_num"],
                "doc_id": doc_counter,
                "doc_type": current_doc_type,
            }
        )
    return results


def classify_page_json(page_text: str, llm) -> Dict[str, str]:
    """Classify a page and return a structured JSON answer.

    Tips that improve classification accuracy:
      1. Give the model a predefined set of document types
      2. Ask for the result as JSON (or CSV)
      3. Instruct the model to return "Other" when unsure
      4. Fix the output type and structure to avoid explanations
      5. Provide few-shot examples so the model mirrors the sample format
    """
    prompt = f"""
You are a document boundary detection agent.
Your job is to:
1. Decide if this page starts a new document or continues the previous one.
2. If it starts a new document, classify its type.
Document type options: {json.dumps(DOC_TYPES)}
Return only a JSON response in the format:
{{
    "is_new_doc": "<Yes/No>",
    "doc_type": "<one of the above>"
}}
Page Content:
{page_text}
If unsure about document type, return "Other".
"""
    response = _generate_text(llm, prompt)
    try:
        # Parse the structured answer as JSON
        return json.loads(response)
    except json.JSONDecodeError:
        return {"is_new_doc": "No", "doc_type": "Other"}


def classify_pages_json(pages: List[dict], llm) -> List[dict]:
    """Page loop using the structured JSON classification (higher accuracy)."""
    results = []
    for i, page in enumerate(pages):
        parsed = classify_page_json(page["text"], llm)
        results.append(
            {
                "page_num": page["page_num"],
                "is_new_doc": parsed.get("is_new_doc", "No"),
                "doc_type": parsed.get("doc_type", "Other"),
            }
        )
    return results

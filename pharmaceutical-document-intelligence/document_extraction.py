"""PDF -> machine-readable text extraction.

Two backends are provided:
  * PyMuPDF (fitz) - the primary extractor used by the final pipeline
  * PyPDF2         - an alternative used for comparison during development
"""

from typing import List

import fitz  # PyMuPDF


def upload_pdf() -> str:
    """Ask the user for a PDF and return its local filename.

    Uses the Colab file uploader when running in Google Colab, otherwise
    falls back to a plain file-path prompt.
    """
    try:
        from google.colab import files  # Only available inside Colab

        print("Please select a PDF file to upload:")
        uploaded = files.upload()
        return next(iter(uploaded.keys()))
    except ImportError:
        # Local fallback: ask for a path instead of a browser upload
        return input("Please enter the path to your PDF file: ").strip()


def extract_text_with_pymupdf(pdf_path: str) -> str:
    """Return the full text of a PDF as a single string."""
    doc = fitz.open(pdf_path)
    # Extract text from every page
    text = "\n".join([page.get_text() for page in doc])
    print(f"Extracted {len(text.split())} words from the PDF.")
    return text


def extract_pages_with_pymupdf(pdf_path: str) -> List[str]:
    """Return one text string per page of the PDF."""
    doc = fitz.open(pdf_path)
    return [page.get_text() for page in doc]


def extract_pages_with_pypdf2(pdf_path: str) -> List[str]:
    """Return one text string per page using PyPDF2 (alternative backend)."""
    from PyPDF2 import PdfReader

    reader = PdfReader(pdf_path)
    # Go through the pages one by one and pull out their text
    return [page.extract_text() for page in reader.pages]


def load_pages(pdf_path: str) -> List[dict]:
    """Return pages as dicts so downstream classifiers can iterate easily."""
    page_texts = extract_pages_with_pymupdf(pdf_path)
    # Turn each page into a dict {page_num, text}
    return [{"page_num": i, "text": text} for i, text in enumerate(page_texts)]

"""Gradio chat UI for the pharmaceutical document QA system."""

import os
import sys

# Make `python src/app.py` work the same way as `python -m src.app`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr

from src.qa_pipeline import DocumentQA, build_document_qa

# Global state shared between the UI callbacks
qa_system: DocumentQA | None = None


def process_pdf(file) -> str:
    """Process the uploaded PDF and build the RAG pipeline."""
    global qa_system
    try:
        qa_system = build_document_qa(file.name)
        return "PDF processed successfully! You can now ask questions."
    except Exception as e:  # Surface the error in the UI instead of crashing
        return f"Failed to process PDF: {e}"


def handle_chat(message, history):
    """Receive a user message, answer it and return the updated history."""
    if qa_system is None:
        return history + [(message, "Please upload and process a PDF first.")]

    result = qa_system.answer_question(message, k=4, auto_route=True)
    answer = result["answer"]
    if result["sources"]:
        source_list = ", ".join(
            f"{s['doc_type']} p.{s['page_start']}-{s['page_end']}" for s in result["sources"]
        )
        answer += f"\n\nSources: {source_list} | Confidence: {result['confidence']:.2f}"
    return history + [(message, answer)]


def build_ui():
    """Design the chat interface with gr.Blocks."""
    with gr.Blocks(title="Document Q&A Chatbot") as demo:
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(label="Chat History", height=500)  # Display the chat history
            user_input = gr.Textbox(  # Input textbox for the user question
                placeholder="Ask a question about your document...",
                label="Your Question",
            )
            send_btn = gr.Button("Send")

        with gr.Column(scale=1):
            pdf_input = gr.File(label="Upload PDF", file_types=[".pdf"])  # PDF uploader

        process_btn = gr.Button("Process Document")  # Send the file to the pipeline
        clear_btn = gr.Button("Clear Chat")  # Clear the chat history

        # Wire up the components
        process_btn.click(process_pdf, inputs=pdf_input, outputs=None)
        send_btn.click(handle_chat, inputs=[user_input, chatbot], outputs=chatbot)
        user_input.submit(handle_chat, inputs=[user_input, chatbot], outputs=chatbot)
        clear_btn.click(lambda: [], outputs=[chatbot])

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(share=True)  # Launch a shareable web app

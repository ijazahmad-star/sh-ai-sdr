# import gradio as gr

# def launch_ui(app, config):
#     def chat_with_email_assistant(message, history):
#         history = history or []
#         history.append(("user", message))
#         try:
#             response = app.invoke({"messages": [{"role": "user", "content": message}]}, config)
#             reply = response["messages"][-1].content
#         except Exception as e:
#             reply = f"Error: {str(e)}"
#         history.append(("assistant", reply))
#         return history, history

#     custom_css = """
#     #chatbot {height: 600px; border-radius: 15px; background: #f9fafb;}
#     .gradio-container {font-family: 'Inter', sans-serif;}
#     .message.user {background-color: #dbeafe !important; color: #1e3a8a !important;}
#     .message.assistant {background-color: #e5e7eb !important; color: #111827 !important;}
#     """

#     with gr.Blocks(css=custom_css, theme=gr.themes.Soft(), title="Strategisthub Email Assistant") as ui:
#         gr.Markdown(
#             """
#             <div style="text-align:center; padding:10px 0;">
#                 <h2 style="font-weight:700; color:#1e40af;">Strategisthub Email Assistant</h2>
#                 <p style="color:#374151;">Your intelligent RAG-powered assistant for professional email responses</p>
#             </div>
#             """
#         )
#         chatbot = gr.Chatbot(elem_id="chatbot", label="Conversation", height=600)
#         msg = gr.Textbox(placeholder="Paste or type your email here...", label="Your Message", lines=5)
#         with gr.Row():
#             clear = gr.Button("Clear Chat")
#             submit = gr.Button("Generate Response", variant="primary")

#         submit.click(chat_with_email_assistant, inputs=[msg, chatbot], outputs=[chatbot, chatbot])
#         msg.submit(chat_with_email_assistant, inputs=[msg, chatbot], outputs=[chatbot, chatbot])
#         clear.click(lambda: None, None, chatbot, queue=False)

#     ui.launch()


import gradio as gr
from pathlib import Path
from app.data_loader import load_pdfs_from_directory
from app.vectorstore import build_vectorstore
from app.tools.tools import create_retriever_tool
from app.graph_builder import build_workflow
from app.config import PDF_DIR, EMAIL_SYSTEM_PROMPT


def launch_ui(app, config):
    def chat_with_email_assistant(message, history):
        history = history or []
        history.append({"role": "user", "content": message})
        try:
            response = app.invoke({"messages": [{"role": "user", "content": message}]}, config)
            reply = response["messages"][-1].content
        except Exception as e:
            reply = f"⚠️ Error: {str(e)}"
        history.append({"role": "assistant", "content": reply})
        return history, history

    def upload_new_docs(files):
        if not files:
            return "⚠️ No file uploaded."
        Path(PDF_DIR).mkdir(parents=True, exist_ok=True)
        for file in files:
            file_path = Path(PDF_DIR) / Path(file.name).name
            with open(file_path, "wb") as f:
                f.write(file.read())

        pdf_docs = load_pdfs_from_directory(PDF_DIR)
        retriever = build_vectorstore(pdf_docs)
        tools = create_retriever_tool(retriever)
        new_workflow = build_workflow(tools, EMAIL_SYSTEM_PROMPT)
        config = {"configurable": {"thread_id": "1"}}
        global current_app
        current_app = new_workflow
        return "File uploaded and vectorstore updated successfully!"

    custom_css = """
    #chatbot {height: 600px; border-radius: 15px; background: #f9fafb;}
    .gradio-container {font-family: 'Inter', sans-serif;}
    .message.user {background-color: #dbeafe !important; color: #1e3a8a !important;}
    .message.assistant {background-color: #e5e7eb !important; color: #111827 !important;}
    """

    global current_app
    current_app = app

    with gr.Blocks(css=custom_css, theme=gr.themes.Soft(), title="Strategisthub Email Assistant") as ui:
        gr.Markdown(
            """
            <div style="text-align:center; padding:10px 0;">
                <h2 style="font-weight:700; color:#1e40af;">📧 Strategisthub Email Assistant</h2>
                <p style="color:#374151;">Upload company documents and chat for instant email drafting</p>
            </div>
            """
        )

        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(elem_id="chatbot", label="Conversation", height=600, type="messages")
                msg = gr.Textbox(placeholder="Paste or type your email here...", label="Your Message", lines=5)
                with gr.Row():
                    clear = gr.Button("🧹 Clear Chat")
                    submit = gr.Button("🚀 Generate Response", variant="primary")

            with gr.Column(scale=1):
                gr.Markdown("### 📂 Upload PDF Documents")
                file_uploader = gr.File(label="Upload new company documents", file_types=[".pdf"], file_count="multiple")
                upload_status = gr.Markdown()
                upload_button = gr.Button("📤 Upload & Update Database", variant="secondary")

        submit.click(chat_with_email_assistant, inputs=[msg, chatbot], outputs=[chatbot, chatbot])
        msg.submit(chat_with_email_assistant, inputs=[msg, chatbot], outputs=[chatbot, chatbot])
        clear.click(lambda: None, None, chatbot, queue=False)
        upload_button.click(upload_new_docs, inputs=[file_uploader], outputs=[upload_status])

    return ui

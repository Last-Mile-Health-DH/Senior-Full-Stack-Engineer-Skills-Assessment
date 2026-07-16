import chainlit as cl

from api_client import ApiError, post_chat


@cl.on_chat_start
async def on_chat_start() -> None:
    await cl.Message(
        content=(
            "Hi! Ask me a question about your ingested documents and I'll answer using RAG "
            "over the documents you've uploaded. (Uploading new PDFs happens on the separate "
            "frontend's Upload page — this chat is answer-only.)"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    try:
        response = await post_chat(message.content)
    except ApiError as exc:
        await cl.Message(content=f"Sorry, I couldn't get an answer: {exc.message}").send()
        return

    answer = response.get("answer", "")
    sources = response.get("sources", [])

    reply = answer
    if sources:
        source_lines = "\n".join(
            f"- {source['doc_name']} ({round(source['similarity'] * 100)}%)" for source in sources
        )
        reply = f"{answer}\n\n**Sources:**\n{source_lines}"

    await cl.Message(content=reply).send()

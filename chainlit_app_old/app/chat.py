import chainlit as cl

@cl.on_chat_start
async def start_chat():
    await cl.Message(content="Hello! I'm your assistant. How can I help you today?").send() 


@cl.on_message
async def handle_message(message: cl.Message):
    user_input = message.content
    # Here you can add your logic to process the user input and generate a response
    response = f"You said: {user_input}"
    await cl.Message(content=response).send()
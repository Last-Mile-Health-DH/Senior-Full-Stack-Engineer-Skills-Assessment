import { useState } from 'react'
import { useOutletContext } from 'react-router'
import { Box } from '@chakra-ui/react'
import { postChat } from '../api/chat'
import { ApiError } from '../api/client'
import { ChatInput } from '../components/chat/ChatInput'
import { MessageList } from '../components/chat/MessageList'
import type { ChatOutletContext } from '../components/layout/AppLayout'
import type { ChatMessage } from '../types'

function newMessage(role: ChatMessage['role'], content: string, sources?: ChatMessage['sources']): ChatMessage {
  return { id: crypto.randomUUID(), role, content, sources, createdAt: Date.now() }
}

export default function ChatPage() {
  const { messages, addMessage } = useOutletContext<ChatOutletContext>()
  const [isPending, setIsPending] = useState(false)

  const handleSubmit = async (question: string) => {
    addMessage(newMessage('user', question))
    setIsPending(true)
    try {
      const response = await postChat(question)
      addMessage(newMessage('assistant', response.answer, response.sources))
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
      addMessage(newMessage('error', message))
    } finally {
      setIsPending(false)
    }
  }

  return (
    <Box>
      <MessageList messages={messages} isPending={isPending} />
      <ChatInput onSubmit={handleSubmit} isDisabled={isPending} />
    </Box>
  )
}

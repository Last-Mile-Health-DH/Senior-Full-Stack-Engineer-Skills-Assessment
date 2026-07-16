import { useState } from 'react'
import { Box } from '@chakra-ui/react'
import { Outlet } from 'react-router'
import { NavBar } from './NavBar'
import type { ChatMessage } from '../../types'

export interface ChatOutletContext {
  messages: ChatMessage[]
  addMessage: (message: ChatMessage) => void
}

// Chat message state lives here (not inside ChatPage) so it survives
// navigating to /upload and back — ChatPage unmounts on route change,
// but AppLayout stays mounted for the lifetime of the app.
export function AppLayout() {
  const [messages, setMessages] = useState<ChatMessage[]>([])

  const addMessage = (message: ChatMessage) => {
    setMessages((prev) => [...prev, message])
  }

  return (
    <Box minH="100vh">
      <NavBar />
      <Box as="main" maxW="3xl" mx="auto" px={4} py={6}>
        <Outlet context={{ messages, addMessage } satisfies ChatOutletContext} />
      </Box>
    </Box>
  )
}

import { Box, Text } from '@chakra-ui/react'
import type { ChatMessage } from '../../types'
import { SourceList } from './SourceList'

const roleStyles: Record<ChatMessage['role'], { bg: string; alignSelf: string; colorPalette?: string }> = {
  user: { bg: 'blue.subtle', alignSelf: 'flex-end' },
  assistant: { bg: 'gray.subtle', alignSelf: 'flex-start' },
  error: { bg: 'red.subtle', alignSelf: 'flex-start', colorPalette: 'red' },
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const style = roleStyles[message.role]

  return (
    <Box
      bg={style.bg}
      colorPalette={style.colorPalette}
      alignSelf={style.alignSelf}
      borderRadius="lg"
      px={4}
      py={2}
      maxW="80%"
    >
      <Text>{message.content}</Text>
      {message.role === 'assistant' && message.sources && <SourceList sources={message.sources} />}
    </Box>
  )
}

import { Flex, HStack, Spinner, Text } from '@chakra-ui/react'
import type { ChatMessage } from '../../types'
import { MessageBubble } from './MessageBubble'

export function MessageList({ messages, isPending }: { messages: ChatMessage[]; isPending: boolean }) {
  if (messages.length === 0 && !isPending) {
    return (
      <Flex justify="center" py={16}>
        <Text color="fg.muted">Ask a question about your uploaded documents to get started.</Text>
      </Flex>
    )
  }

  return (
    <Flex direction="column" gap={3} className="max-h-[60vh] overflow-y-auto" py={4}>
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {isPending && (
        <HStack alignSelf="flex-start" bg="gray.subtle" borderRadius="lg" px={4} py={2}>
          <Spinner size="sm" />
          <Text>Thinking…</Text>
        </HStack>
      )}
    </Flex>
  )
}

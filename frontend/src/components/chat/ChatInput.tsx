import { useState } from 'react'
import { Button, HStack, Input } from '@chakra-ui/react'

export function ChatInput({
  onSubmit,
  isDisabled,
}: {
  onSubmit: (question: string) => void
  isDisabled: boolean
}) {
  const [value, setValue] = useState('')

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || isDisabled) return
    onSubmit(trimmed)
    setValue('')
  }

  return (
    <form onSubmit={handleSubmit}>
      <HStack gap={2}>
        <Input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Ask a question about your documents…"
          disabled={isDisabled}
        />
        <Button type="submit" disabled={isDisabled || !value.trim()} loading={isDisabled}>
          Send
        </Button>
      </HStack>
    </form>
  )
}

import { HStack, Badge, Text } from '@chakra-ui/react'
import type { SourceChunk } from '../../types'

export function SourceList({ sources }: { sources: SourceChunk[] }) {
  if (sources.length === 0) return null

  return (
    <HStack gap={2} mt={2} wrap="wrap">
      <Text fontSize="sm" color="fg.muted">
        Sources:
      </Text>
      {sources.map((source, index) => (
        <Badge key={`${source.doc_name}-${index}`} variant="subtle">
          {source.doc_name} ({Math.round(source.similarity * 100)}%)
        </Badge>
      ))}
    </HStack>
  )
}

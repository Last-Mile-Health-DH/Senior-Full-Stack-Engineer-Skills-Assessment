import { Alert } from '@chakra-ui/react'
import type { UploadResponse } from '../../types'

export function UploadResult({ result, error }: { result: UploadResponse | null; error: string | null }) {
  if (error) {
    return (
      <Alert.Root status="error" mt={4}>
        <Alert.Indicator />
        <Alert.Title>{error}</Alert.Title>
      </Alert.Root>
    )
  }

  if (result) {
    return (
      <Alert.Root status="success" mt={4}>
        <Alert.Indicator />
        <Alert.Title>
          Ingested '{result.doc_name}' — {result.chunks_ingested} chunks indexed.
        </Alert.Title>
      </Alert.Root>
    )
  }

  return null
}

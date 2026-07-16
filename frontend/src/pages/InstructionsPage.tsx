import { useEffect, useState } from 'react'
import { Alert, Box, Spinner } from '@chakra-ui/react'
import { getInstructionsHtml } from '../api/instructions'

export default function InstructionsPage() {
  const [html, setHtml] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getInstructionsHtml()
      .then(setHtml)
      .catch((err: Error) => setError(err.message))
  }, [])

  if (error) {
    return (
      <Alert.Root status="error">
        <Alert.Indicator />
        <Alert.Title>{error}</Alert.Title>
      </Alert.Root>
    )
  }

  if (html === null) {
    return <Spinner />
  }

  // The backend serves this as a full, self-contained HTML document (see
  // backend/app/routers/instructions.py) — trusted, static content, not user input.
  return <Box dangerouslySetInnerHTML={{ __html: html }} />
}

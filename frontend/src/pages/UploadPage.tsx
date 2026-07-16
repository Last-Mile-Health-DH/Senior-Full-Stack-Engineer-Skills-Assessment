import { useEffect, useState } from 'react'
import { Alert, Box, Button, Heading, Text, VStack } from '@chakra-ui/react'
import { listDocuments, uploadDocument } from '../api/documents'
import { ApiError } from '../api/client'
import { DocumentGrid } from '../components/upload/DocumentGrid'
import { UploadDropzone } from '../components/upload/UploadDropzone'
import { UploadResult } from '../components/upload/UploadResult'
import type { DocumentFile, UploadResponse } from '../types'

const MAX_SIZE_WARNING_MB = 20

function isPdfFile(file: File): boolean {
  return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
}

export default function UploadPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [result, setResult] = useState<UploadResponse | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [documents, setDocuments] = useState<DocumentFile[]>([])
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true)
  const [documentsError, setDocumentsError] = useState<string | null>(null)

  const fetchDocuments = async () => {
    setIsLoadingDocuments(true)
    setDocumentsError(null)
    try {
      const response = await listDocuments()
      setDocuments(response.documents)
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Could not load uploaded documents.'
      setDocumentsError(message)
    } finally {
      setIsLoadingDocuments(false)
    }
  }

  useEffect(() => {
    fetchDocuments()
  }, [])

  const handleFileSelected = (file: File) => {
    setResult(null)
    setUploadError(null)

    if (!isPdfFile(file)) {
      setValidationError('Please select a PDF file.')
      setSelectedFile(null)
      return
    }

    setValidationError(null)
    setSelectedFile(file)
  }

  const handleUpload = async () => {
    if (!selectedFile) return
    setIsUploading(true)
    setUploadError(null)
    setResult(null)
    try {
      const response = await uploadDocument(selectedFile)
      setResult(response)
      setSelectedFile(null)
      await fetchDocuments()
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Upload failed. Please try again.'
      setUploadError(message)
    } finally {
      setIsUploading(false)
    }
  }

  const showSizeWarning = selectedFile && selectedFile.size > MAX_SIZE_WARNING_MB * 1024 * 1024

  return (
    <VStack align="stretch" gap={4}>
      <Heading size="lg">Upload a document</Heading>
      <Text color="fg.muted">
        Upload a PDF to ingest it into the RAG pipeline. Once processed, you can ask questions about it on the
        Chat page.
      </Text>

      <UploadDropzone onFileSelected={handleFileSelected} isDisabled={isUploading} />

      {selectedFile && (
        <Text fontSize="sm">
          Selected: <strong>{selectedFile.name}</strong>
        </Text>
      )}

      {validationError && (
        <Alert.Root status="error">
          <Alert.Indicator />
          <Alert.Title>{validationError}</Alert.Title>
        </Alert.Root>
      )}

      {showSizeWarning && (
        <Alert.Root status="warning">
          <Alert.Indicator />
          <Alert.Title>
            This file is larger than {MAX_SIZE_WARNING_MB}MB — the server may reject very large uploads.
          </Alert.Title>
        </Alert.Root>
      )}

      <Box>
        <Button onClick={handleUpload} disabled={!selectedFile || isUploading} loading={isUploading}>
          Upload
        </Button>
      </Box>

      <UploadResult result={result} error={uploadError} />

      <Heading size="md" mt={4}>
        Uploaded documents
      </Heading>
      {documentsError && (
        <Alert.Root status="error">
          <Alert.Indicator />
          <Alert.Title>{documentsError}</Alert.Title>
        </Alert.Root>
      )}
      {isLoadingDocuments ? <Text color="fg.muted">Loading…</Text> : <DocumentGrid documents={documents} />}
    </VStack>
  )
}

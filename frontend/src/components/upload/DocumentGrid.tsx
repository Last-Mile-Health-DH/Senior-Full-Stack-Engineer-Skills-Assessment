import { SimpleGrid, Text, VStack } from '@chakra-ui/react'
import { FaFile, FaFilePdf } from 'react-icons/fa6'
import type { DocumentFile } from '../../types'

function fileTypeIcon(fileType: string) {
  if (fileType === 'application/pdf') return FaFilePdf
  return FaFile
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`
}

export function DocumentGrid({ documents }: { documents: DocumentFile[] }) {
  if (documents.length === 0) {
    return <Text color="fg.muted">No documents uploaded yet.</Text>
  }

  return (
    <SimpleGrid columns={{ base: 2, sm: 3, md: 4 }} gap={4}>
      {documents.map((doc) => {
        const FileIcon = fileTypeIcon(doc.file_type)
        return (
          <VStack
            key={doc.id}
            borderWidth="1px"
            borderRadius="lg"
            p={3}
            gap={2}
            align="center"
            title={doc.doc_name}
          >
            <FileIcon size={32} />
            <Text fontSize="sm" fontWeight="medium" lineClamp={2} textAlign="center">
              {doc.doc_name}
            </Text>
            <Text fontSize="xs" color="fg.muted">
              {doc.page_count ?? '—'} pages · {formatBytes(doc.file_size)}
            </Text>
          </VStack>
        )
      })}
    </SimpleGrid>
  )
}

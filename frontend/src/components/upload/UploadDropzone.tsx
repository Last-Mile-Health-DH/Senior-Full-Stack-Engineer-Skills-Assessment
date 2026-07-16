import { useRef, useState } from 'react'
import { Box, Text } from '@chakra-ui/react'

export function UploadDropzone({
  onFileSelected,
  isDisabled,
}: {
  onFileSelected: (file: File) => void
  isDisabled: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragActive, setIsDragActive] = useState(false)

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0]
    if (file) onFileSelected(file)
  }

  return (
    <Box
      role="button"
      tabIndex={0}
      onClick={() => !isDisabled && inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click()
      }}
      onDragOver={(event) => {
        event.preventDefault()
        setIsDragActive(true)
      }}
      onDragLeave={() => setIsDragActive(false)}
      onDrop={(event) => {
        event.preventDefault()
        setIsDragActive(false)
        handleFiles(event.dataTransfer.files)
      }}
      borderWidth="2px"
      borderStyle="dashed"
      borderColor={isDragActive ? 'blue.solid' : 'border'}
      borderRadius="lg"
      px={6}
      py={10}
      textAlign="center"
      cursor={isDisabled ? 'not-allowed' : 'pointer'}
      opacity={isDisabled ? 0.6 : 1}
    >
      <Text>Drag and drop a PDF here, or click to choose a file.</Text>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,application/pdf"
        disabled={isDisabled}
        onChange={(event) => handleFiles(event.target.files)}
        style={{
          position: 'absolute',
          width: 1,
          height: 1,
          padding: 0,
          margin: -1,
          overflow: 'hidden',
          clip: 'rect(0, 0, 0, 0)',
          whiteSpace: 'nowrap',
          border: 0,
        }}
      />
    </Box>
  )
}

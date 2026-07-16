export interface ChatRequest {
  question: string
  num_results?: number
}

export interface SourceChunk {
  doc_name: string
  similarity: number
}

export interface ChatResponse {
  answer: string
  sources: SourceChunk[]
}

export interface UploadResponse {
  doc_name: string
  chunks_ingested: number
}

export interface DocumentFile {
  id: number
  doc_name: string
  file_size: number
  page_count: number | null
  file_type: string
  created_at: string
}

export interface DocumentListResponse {
  documents: DocumentFile[]
}

// Client-side only — not part of the backend contract.
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'error'
  content: string
  sources?: SourceChunk[]
  createdAt: number
}

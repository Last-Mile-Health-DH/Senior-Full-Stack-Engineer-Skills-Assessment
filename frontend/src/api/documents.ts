import { apiRequest } from './client'
import type { UploadResponse } from '../types'

export function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  // No explicit Content-Type header — the browser sets the multipart
  // boundary automatically when the body is a FormData instance.
  return apiRequest<UploadResponse>('/documents', {
    method: 'POST',
    body: formData,
  })
}

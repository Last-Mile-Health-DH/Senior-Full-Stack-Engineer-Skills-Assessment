import { apiRequest } from './client'
import type { ChatRequest, ChatResponse } from '../types'

export function postChat(question: string, numResults?: number): Promise<ChatResponse> {
  const body: ChatRequest = { question, ...(numResults ? { num_results: numResults } : {}) }

  return apiRequest<ChatResponse>('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

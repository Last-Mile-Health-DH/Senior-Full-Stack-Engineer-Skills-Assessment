import { API_BASE_URL } from './client'

export async function getInstructionsHtml(): Promise<string> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/instructions`, { headers: { Accept: 'text/html' } })
  } catch {
    throw new Error('Could not reach the server — is the backend running?')
  }

  if (!response.ok) {
    throw new Error(`Failed to load instructions (${response.status}).`)
  }

  return response.text()
}

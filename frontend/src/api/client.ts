export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:6100'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// FastAPI's default validation errors return `detail` as an array of
// { loc, msg, type }; custom HTTPExceptions return `detail` as a plain
// string. Handle both shapes rather than assuming one.
function extractErrorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : null))
        .filter((msg): msg is string => Boolean(msg))
      if (messages.length > 0) return messages.join('; ')
    }
  }
  return fallback
}

export async function apiRequest<TResponse>(
  path: string,
  init: RequestInit = {},
): Promise<TResponse> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError('Could not reach the server — is the backend running?', 0)
  }

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      // response had no JSON body; fall through to generic message
    }

    if (response.status >= 500) {
      console.error('Backend error', response.status, body)
      throw new ApiError('Something went wrong processing that — please try again.', response.status)
    }

    throw new ApiError(extractErrorMessage(body, `Request failed (${response.status}).`), response.status)
  }

  return (await response.json()) as TResponse
}

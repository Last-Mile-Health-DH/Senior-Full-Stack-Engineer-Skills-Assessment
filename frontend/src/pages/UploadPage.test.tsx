import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../AppRoutes'
import { renderWithProviders } from '../test/renderWithProviders'

vi.mock('../api/documents', () => ({
  uploadDocument: vi.fn(),
  listDocuments: vi.fn(),
}))

import { listDocuments, uploadDocument } from '../api/documents'

function getFileInput(): HTMLInputElement {
  return document.querySelector('input[type="file"]') as HTMLInputElement
}

describe('UploadPage', () => {
  it('uploads a PDF and renders the success result', async () => {
    vi.mocked(uploadDocument).mockResolvedValue({ doc_name: 'a.pdf', chunks_ingested: 17 })
    vi.mocked(listDocuments).mockResolvedValueOnce({ documents: [] }).mockResolvedValueOnce({
      documents: [
        {
          id: 1,
          doc_name: 'a.pdf',
          file_size: 12_345,
          page_count: 4,
          file_type: 'application/pdf',
          created_at: '2026-07-01T00:00:00Z',
        },
      ],
    })

    const user = userEvent.setup()
    renderWithProviders(<AppRoutes />, { route: '/upload' })

    const file = new File(['%PDF-1.4 fake content'], 'a.pdf', { type: 'application/pdf' })
    await user.upload(getFileInput(), file)

    await user.click(screen.getByRole('button', { name: /upload/i }))

    await waitFor(() => expect(screen.getByText(/ingested 'a\.pdf'/i)).toBeInTheDocument())
    expect(screen.getByText(/17 chunks indexed/i)).toBeInTheDocument()
    expect(uploadDocument).toHaveBeenCalledWith(file)

    await waitFor(() => expect(screen.getByTitle('a.pdf')).toBeInTheDocument())
    expect(listDocuments).toHaveBeenCalledTimes(2)
  })

  it('rejects a non-PDF file client-side without calling the API', async () => {
    vi.mocked(listDocuments).mockResolvedValue({ documents: [] })
    renderWithProviders(<AppRoutes />, { route: '/upload' })

    // The hidden file input has accept=".pdf,application/pdf", which
    // userEvent.upload() honors (mimicking the OS file picker) and would
    // silently refuse a .txt file. A drag-and-drop, however, bypasses that
    // OS-level filtering — exactly the path our client-side validation
    // guards against — so we simulate rejection via `drop`.
    const file = new File(['plain text'], 'notes.txt', { type: 'text/plain' })
    fireEvent.drop(screen.getByRole('button', { name: /drag and drop/i }), {
      dataTransfer: { files: [file] },
    })

    expect(await screen.findByText(/please select a pdf file/i)).toBeInTheDocument()
    expect(uploadDocument).not.toHaveBeenCalled()
  })
})

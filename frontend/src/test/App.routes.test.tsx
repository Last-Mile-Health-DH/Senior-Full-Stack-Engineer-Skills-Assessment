import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../AppRoutes'
import { renderWithProviders } from './renderWithProviders'

vi.mock('../api/instructions', () => ({
  getInstructionsHtml: vi.fn().mockResolvedValue('<h1>Assessment instructions</h1>'),
}))

vi.mock('../api/documents', () => ({
  listDocuments: vi.fn().mockResolvedValue({ documents: [] }),
}))

describe('AppRoutes', () => {
  it('redirects / to the instructions page', async () => {
    renderWithProviders(<AppRoutes />, { route: '/' })

    await waitFor(() => expect(screen.getByRole('heading', { name: /assessment instructions/i })).toBeInTheDocument())
  })

  it('renders the upload page at /upload', () => {
    renderWithProviders(<AppRoutes />, { route: '/upload' })

    expect(screen.getByRole('heading', { name: /upload a document/i })).toBeInTheDocument()
  })

  it('navigates from instructions to upload via the nav bar', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AppRoutes />, { route: '/' })

    await waitFor(() => expect(screen.getByRole('heading', { name: /assessment instructions/i })).toBeInTheDocument())
    await user.click(screen.getByRole('link', { name: /upload/i }))

    expect(screen.getByRole('heading', { name: /upload a document/i })).toBeInTheDocument()
  })
})

import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../AppRoutes'
import { renderWithProviders } from './renderWithProviders'

describe('AppRoutes', () => {
  it('renders the chat page at /', () => {
    renderWithProviders(<AppRoutes />, { route: '/' })

    expect(screen.getByText(/ask a question about your uploaded documents/i)).toBeInTheDocument()
  })

  it('renders the upload page at /upload', () => {
    renderWithProviders(<AppRoutes />, { route: '/upload' })

    expect(screen.getByRole('heading', { name: /upload a document/i })).toBeInTheDocument()
  })

  it('navigates from chat to upload via the nav bar', async () => {
    const user = userEvent.setup()
    renderWithProviders(<AppRoutes />, { route: '/' })

    await user.click(screen.getByRole('link', { name: /upload/i }))

    expect(screen.getByRole('heading', { name: /upload a document/i })).toBeInTheDocument()
  })
})

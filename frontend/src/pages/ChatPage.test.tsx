import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppRoutes } from '../AppRoutes'
import { renderWithProviders } from '../test/renderWithProviders'

vi.mock('../api/chat', () => ({
  postChat: vi.fn(),
}))

import { postChat } from '../api/chat'

describe('ChatPage', () => {
  it('sends a question and renders the answer with sources', async () => {
    vi.mocked(postChat).mockResolvedValue({
      answer: 'Mock answer',
      sources: [{ doc_name: 'a.pdf', similarity: 0.9 }],
    })

    const user = userEvent.setup()
    renderWithProviders(<AppRoutes />, { route: '/' })

    await user.type(screen.getByPlaceholderText(/ask a question/i), 'What is UNICEF?')
    await user.click(screen.getByRole('button', { name: /send/i }))

    expect(screen.getByText('What is UNICEF?')).toBeInTheDocument()

    await waitFor(() => expect(screen.getByText('Mock answer')).toBeInTheDocument())
    expect(screen.getByText(/a\.pdf/)).toBeInTheDocument()
    expect(screen.getByText(/90%/)).toBeInTheDocument()
    expect(postChat).toHaveBeenCalledWith('What is UNICEF?')
  })
})

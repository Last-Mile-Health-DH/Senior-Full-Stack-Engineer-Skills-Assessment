import { Route, Routes } from 'react-router'
import { AppLayout } from './components/layout/AppLayout'
import ChatPage from './pages/ChatPage'
import UploadPage from './pages/UploadPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<ChatPage />} />
        <Route path="upload" element={<UploadPage />} />
      </Route>
    </Routes>
  )
}

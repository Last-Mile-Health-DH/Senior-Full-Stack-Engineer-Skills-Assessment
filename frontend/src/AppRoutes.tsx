import { Navigate, Route, Routes } from 'react-router'
import { AppLayout } from './components/layout/AppLayout'
// Chat is disabled for this deployment — see NavBar for the corresponding nav link.
import ChatPage from './pages/ChatPage'
import InstructionsPage from './pages/InstructionsPage'
import UploadPage from './pages/UploadPage'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="upload" replace />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="chat" element={<ChatPage />} />
        {/*<Route index element={<Navigate to="instructions" replace />} />*/}
        <Route path="instructions" element={<InstructionsPage />} />
      </Route>
    </Routes>
  )
}

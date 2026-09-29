import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import EventPage from '@/pages/EventPage'
import JobPage from '@/pages/JobPage'
import LivePage from '@/pages/LivePage'
import SearchPage from '@/pages/SearchPage'
import UploadPage from '@/pages/UploadPage'
import './index.css'

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <UploadPage /> },
      { path: '/live', element: <LivePage /> },
      { path: '/jobs/:id', element: <JobPage /> },
      { path: '/events/:id', element: <EventPage /> },
      { path: '/search', element: <SearchPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)

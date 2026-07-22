import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './theme.css'
import App from './App'

// One QueryClient for the app: it is the data-cache layer (the st.cache_data analogue) —
// every useQuery result is cached under its key and deduped across components.
// retry: false mirrors the Streamlit failed-key behavior — a failed generate is not
// auto-retried on every interaction; the Run button retries explicitly.
const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)

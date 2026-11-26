import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './workspace/ErrorBoundary'
import './styles/fonts.css'
import './styles.css'
import './theme/theme.css'
import './ui/system.css'
import './ui/tour.css'

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)

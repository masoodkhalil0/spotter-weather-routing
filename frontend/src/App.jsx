import { useEffect, useState } from 'react'
import './App.css'
import { health } from './api/client'

function App() {
  const [statusMessage, setStatusMessage] = useState('Connecting to server...')

  useEffect(() => {
    const controller = new AbortController()

    async function checkServer() {
      try {
        const data = await health({ signal: controller.signal })

        if (data.status === 'ok') {
          setStatusMessage('Server connected')
          return
        }

        setStatusMessage('Server responded, but the status was unexpected.')
      } catch (error) {
        if (error.name === 'AbortError') {
          return
        }

        setStatusMessage(error.message)
      }
    }

    checkServer()

    return () => {
      controller.abort()
    }
  }, [])

  return (
    <main className="app-shell">
      <section className="card">
        <h1>Truck Weather Route Planner</h1>
        <p className="subtitle">
          Frontend scaffold ready. Next we can add trip search, route results, and the weather heatmap.
        </p>
        <p className="status-line">{statusMessage}</p>
      </section>
    </main>
  )
}

export default App
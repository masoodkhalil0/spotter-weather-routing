import { useEffect, useRef, useState } from 'react'
import './App.css'
import { analyze, health } from './api/client'
import RiskLegend from './components/RiskLegend'
import RouteCards from './components/RouteCards'
import RouteMap from './components/RouteMap'
import TripForm from './components/TripForm'

function App() {
  const [statusMessage, setStatusMessage] = useState('Connecting to server...')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [result, setResult] = useState(null)
  const [selectedRouteId, setSelectedRouteId] = useState(null)
  const analyzeControllerRef = useRef(null)

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

  useEffect(() => {
    return () => {
      if (analyzeControllerRef.current) {
        analyzeControllerRef.current.abort()
      }
    }
  }, [])

  async function handleTripSubmit(payload) {
    if (analyzeControllerRef.current) {
      analyzeControllerRef.current.abort()
    }

    const controller = new AbortController()
    analyzeControllerRef.current = controller

    setLoading(true)
    setErrorMessage('')
    setResult(null)
    setSelectedRouteId(null)

    try {
      const data = await analyze(payload, { signal: controller.signal })
      setResult(data)
      setSelectedRouteId(data.recommended_route_id || data.routes?.[0]?.route_id || null)
    } catch (error) {
      if (error.name === 'AbortError') {
        return
      }

      setErrorMessage(error.message || 'Unable to plan the route right now.')
    } finally {
      if (analyzeControllerRef.current === controller) {
        setLoading(false)
        analyzeControllerRef.current = null
      }
    }
  }

  return (
    <main className="app-shell">
      <section className="card">
        <h1>Truck Weather Route Planner</h1>
        <p className="subtitle">
          Plan a truck trip and check for safer route options based on weather. The first request can take up
          to a minute if the server was asleep.
        </p>
        <p className="status-line">{statusMessage}</p>

        <TripForm onSubmit={handleTripSubmit} loading={loading} />

        {errorMessage ? <div className="message-box error-box">Error: {errorMessage}</div> : null}

        {result ? (
          result.routes?.length ? (
            <section className="results-section">
              <RiskLegend />

              <div className="results-layout">
                <RouteCards
                  routes={result.routes}
                  selectedRouteId={selectedRouteId}
                  onSelect={setSelectedRouteId}
                  explanation={result.explanation}
                />
                <RouteMap routes={result.routes} selectedRouteId={selectedRouteId} onSelect={setSelectedRouteId} />
              </div>
            </section>
          ) : (
            <div className="message-box success-box">No routes were found for this trip.</div>
          )
        ) : null}
      </section>
    </main>
  )
}

export default App
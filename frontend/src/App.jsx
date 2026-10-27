import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { analyze, health, heatmap } from './api/client'
import HeatmapPanel from './components/HeatmapPanel'
import RiskLegend from './components/RiskLegend'
import RouteCards from './components/RouteCards'
import RouteMap from './components/RouteMap'
import TripForm from './components/TripForm'

function App() {
  const [statusMessage, setStatusMessage] = useState('Connecting to server...')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [result, setResult] = useState(null)
  const [heatmapData, setHeatmapData] = useState(null)
  const [heatmapLoading, setHeatmapLoading] = useState(false)
  const [heatmapError, setHeatmapError] = useState('')
  const [hourState, setHourState] = useState({ startTime: null, hour: 0 })
  const [selectedRouteId, setSelectedRouteId] = useState(null)
  const analyzeControllerRef = useRef(null)
  const heatmapRequestRef = useRef({ controller: null, requestId: 0 })
  const handleHourChange = useCallback(
    (hour) => setHourState({ startTime: heatmapData?.start_time ?? null, hour }),
    [heatmapData?.start_time],
  )

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

      if (heatmapRequestRef.current.controller) {
        heatmapRequestRef.current.controller.abort()
      }
    }
  }, [])

  function startHeatmapRequest(payload) {
    if (heatmapRequestRef.current.controller) {
      heatmapRequestRef.current.controller.abort()
    }

    const controller = new AbortController()
    const requestId = heatmapRequestRef.current.requestId + 1
    heatmapRequestRef.current = { controller, requestId }

    setHeatmapLoading(true)
    setHeatmapError('')

    heatmap({ ...payload, hours: 49 }, { signal: controller.signal })
      .then((data) => {
        if (heatmapRequestRef.current.requestId !== requestId) {
          return
        }

        setHeatmapData(data)
      })
      .catch((error) => {
        if (error.name === 'AbortError' || heatmapRequestRef.current.requestId !== requestId) {
          return
        }

        setHeatmapError(error.message || 'Unable to load the forecast heatmap right now.')
      })
      .finally(() => {
        if (heatmapRequestRef.current.requestId === requestId) {
          setHeatmapLoading(false)
          heatmapRequestRef.current = { controller: null, requestId }
        }
      })
  }

  async function handleTripSubmit(payload) {
    if (analyzeControllerRef.current) {
      analyzeControllerRef.current.abort()
    }

    if (heatmapRequestRef.current.controller) {
      heatmapRequestRef.current.controller.abort()
    }

    heatmapRequestRef.current = { controller: null, requestId: heatmapRequestRef.current.requestId + 1 }

    const controller = new AbortController()
    analyzeControllerRef.current = controller

    setLoading(true)
    setErrorMessage('')
    setResult(null)
    setHeatmapData(null)
    setHeatmapLoading(false)
    setHeatmapError('')
    setHourState({ startTime: null, hour: 0 })
    setSelectedRouteId(null)

    try {
      const data = await analyze(payload, { signal: controller.signal })
      setResult(data)
      setSelectedRouteId(data.recommended_route_id || data.routes?.[0]?.route_id || null)
      startHeatmapRequest(payload)
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

  const selectedHour = hourState.startTime === heatmapData?.start_time ? hourState.hour : 0

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
                  originTimezone={result.origin_timezone}
                />
                <RouteMap
                  routes={result.routes}
                  selectedRouteId={selectedRouteId}
                  onSelect={setSelectedRouteId}
                  originTimezone={result.origin_timezone}
                  heatmap={heatmapData}
                  selectedHour={selectedHour}
                />
              </div>

              <HeatmapPanel
                key={heatmapData?.start_time ?? 'none'}
                heatmap={heatmapData}
                loading={heatmapLoading}
                error={heatmapError}
                originTimezone={result.origin_timezone}
                tripDurationSeconds={result.routes.find((route) => route.is_recommended)?.duration_seconds ?? null}
                selectedHour={selectedHour}
                onHourChange={handleHourChange}
              />
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
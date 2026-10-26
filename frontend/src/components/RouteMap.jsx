import { memo, useEffect, useMemo } from 'react'
import { CircleMarker, MapContainer, Pane, Polyline, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { formatDateTime } from '../utils/format'
import { getRiskInfo, getRiskRadius } from '../utils/risk'

const MAP_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const MAP_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const DEFAULT_CENTER = [39.8283, -98.5795]
const DEFAULT_ZOOM = 4

const FitBounds = memo(function FitBounds({ bounds }) {
  const map = useMap()

  useEffect(() => {
    if (!bounds) {
      return
    }

    map.fitBounds(bounds, { padding: [32, 32] })
  }, [bounds, map])

  return null
})

const SelectedRouteMarkers = memo(function SelectedRouteMarkers({ route, originTimezone }) {
  const startPoint = route.geometry?.[0]
  const endPoint = route.geometry?.[route.geometry.length - 1]
  const lastCheckpointIndex = (route.checkpoints?.length || 1) - 1

  return (
    <>
      {startPoint ? (
        <CircleMarker
          pane="checkpoints"
          center={startPoint}
          radius={11}
          pathOptions={{ color: '#ffffff', weight: 2, fillColor: '#0f172a', fillOpacity: 1 }}
        >
          <Tooltip direction="center" offset={[0, 0]} permanent className="endpoint-label">
            A
          </Tooltip>
        </CircleMarker>
      ) : null}

      {endPoint ? (
        <CircleMarker
          pane="checkpoints"
          center={endPoint}
          radius={11}
          pathOptions={{ color: '#ffffff', weight: 2, fillColor: '#0f172a', fillOpacity: 1 }}
        >
          <Tooltip direction="center" offset={[0, 0]} permanent className="endpoint-label">
            B
          </Tooltip>
        </CircleMarker>
      ) : null}

      {route.checkpoints?.map((checkpoint) => {
        const riskInfo = getRiskInfo(checkpoint.level)
        let popupTitle = `Checkpoint ${checkpoint.index}`

        if (checkpoint.index === 0) {
          popupTitle = 'Start (A)'
        } else if (checkpoint.index === lastCheckpointIndex) {
          popupTitle = 'Destination (B)'
        }

        return (
          <CircleMarker
            key={`${route.route_id}-${checkpoint.index}`}
            pane="checkpoints"
            center={[checkpoint.lat, checkpoint.lon]}
            radius={getRiskRadius(checkpoint.level)}
            pathOptions={{
              color: '#f8fafc',
              weight: 2,
              fillColor: riskInfo.color,
              fillOpacity: 0.95,
            }}
          >
            <Popup>
              <div className="checkpoint-popup">
                <h3>{popupTitle}</h3>
                <p>
                  <strong>Mile marker:</strong> {checkpoint.mile_marker}
                </p>
                <p>
                  <strong>ETA:</strong> {formatDateTime(checkpoint.eta, originTimezone || undefined)}
                </p>
                <p>
                  <strong>Risk level:</strong> {riskInfo.label}
                </p>
                <p>
                  <strong>Wind:</strong> {checkpoint.weather?.wind_mph ?? 'Unknown'} mph
                </p>
                <p>
                  <strong>Rain:</strong> {checkpoint.weather?.rain_in_hr ?? 'Unknown'} in/hr
                </p>
                <p>
                  <strong>Snow:</strong> {checkpoint.weather?.snow_in_hr ?? 'Unknown'} in/hr
                </p>

                <div>
                  <strong>Reasons:</strong>
                  {checkpoint.reasons?.length ? (
                    <ul>
                      {checkpoint.reasons.map((reason, reasonIndex) => (
                        <li key={`${reasonIndex}-${reason}`}>{reason}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>No weather concerns</p>
                  )}
                </div>
              </div>
            </Popup>
          </CircleMarker>
        )
      })}
    </>
  )
})

const RouteMap = memo(function RouteMap({ routes, selectedRouteId, onSelect, originTimezone }) {
  const selectedRoute = useMemo(() => {
    return routes.find((route) => route.route_id === selectedRouteId) || routes[0] || null
  }, [routes, selectedRouteId])

  const routeLines = useMemo(() => {
    return routes
      .filter((route) => Array.isArray(route.geometry) && route.geometry.length > 1)
      .map((route) => ({
        route,
        positions: route.geometry.map(([lat, lon]) => [lat, lon]),
      }))
  }, [routes])

  const bounds = useMemo(() => {
    const allPoints = routeLines.flatMap((routeLine) => routeLine.positions)

    if (allPoints.length === 0) {
      return null
    }

    return allPoints
  }, [routeLines])

  return (
    <section className="map-panel">
      <h2 className="section-title">Route map</h2>

      <div className="map-wrapper">
        <MapContainer center={DEFAULT_CENTER} zoom={DEFAULT_ZOOM} className="route-map" scrollWheelZoom>
          <TileLayer attribution={MAP_ATTRIBUTION} url={MAP_TILE_URL} />
          <Pane name="routes" style={{ zIndex: 400 }} />
          <Pane name="checkpoints" style={{ zIndex: 450 }} />

          {bounds ? <FitBounds bounds={bounds} /> : null}

          {routeLines.map(({ route, positions }) => {
            const isSelected = route.route_id === selectedRoute?.route_id

            return (
              <Polyline
                key={route.route_id}
                positions={positions}
                pane="routes"
                pathOptions={
                  isSelected
                    ? {
                        color: '#1d4ed8',
                        weight: 6,
                        opacity: 0.95,
                      }
                    : {
                        color: '#6b7280',
                        weight: 3,
                        opacity: 0.7,
                        dashArray: '8 8',
                      }
                }
                eventHandlers={
                  isSelected
                    ? undefined
                    : {
                        click: () => {
                          onSelect(route.route_id)
                        },
                      }
                }
              >
                <Tooltip sticky>
                  Route {route.rank}
                  {route.is_recommended ? ' (Recommended)' : ''}
                </Tooltip>
              </Polyline>
            )
          })}

          {selectedRoute ? <SelectedRouteMarkers route={selectedRoute} originTimezone={originTimezone} /> : null}
        </MapContainer>
      </div>
    </section>
  )
})

export default RouteMap
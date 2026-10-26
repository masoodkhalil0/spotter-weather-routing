import { memo } from 'react'
import { formatDateTime, formatDuration, formatMiles } from '../utils/format'
import { RISK_LEVELS, getRiskInfo } from '../utils/risk'

const RouteCards = memo(function RouteCards({ routes, selectedRouteId, onSelect, explanation }) {
  return (
    <section className="results-sidebar">
      <div className="route-explanation">
        <h2 className="section-title">Recommendation</h2>
        <p>{explanation || 'The backend did not provide an explanation for this recommendation.'}</p>
      </div>

      <div className="route-cards" role="list" aria-label="Available routes">
        {routes.map((route) => {
          const worstRisk = getRiskInfo(route.summary?.worst_level)
          const isSelected = route.route_id === selectedRouteId

          return (
            <button
              key={route.route_id}
              type="button"
              className={`route-card ${isSelected ? 'route-card-selected' : ''}`}
              aria-pressed={isSelected}
              onClick={() => {
                onSelect(route.route_id)
              }}
            >
              <div className="route-card-header">
                <div>
                  <h3>Route {route.rank}</h3>
                  <div className="route-badges">
                    {route.is_recommended ? <span className="route-badge">Recommended</span> : null}
                    {route.is_generated ? <span className="route-tag">Generated alternative</span> : null}
                  </div>
                </div>
              </div>

              <dl className="route-details">
                <div>
                  <dt>Distance</dt>
                  <dd>{formatMiles(route.distance_miles)}</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>{formatDuration(route.duration_seconds)}</dd>
                </div>
                <div>
                  <dt>Arrival</dt>
                  <dd>{formatDateTime(route.arrival)}</dd>
                </div>
                <div>
                  <dt>Worst risk</dt>
                  <dd className="risk-inline">
                    <span className="risk-swatch" style={{ backgroundColor: worstRisk.color }} aria-hidden="true" />
                    <span>{worstRisk.label}</span>
                  </dd>
                </div>
                <div>
                  <dt>Average risk</dt>
                  <dd>{Number.isFinite(route.summary?.average_risk) ? route.summary.average_risk.toFixed(2) : 'Unknown'}</dd>
                </div>
              </dl>

              <div className="miles-by-level">
                <p className="miles-by-level-title">Miles by level</p>
                <ul>
                  {RISK_LEVELS.filter((risk) => (route.summary?.miles_by_level?.[risk.key] ?? 0) > 0).map((risk) => (
                    <li key={risk.key} className="miles-by-level-item">
                      <span className="risk-inline">
                        <span className="risk-swatch" style={{ backgroundColor: risk.color }} aria-hidden="true" />
                        <span>{risk.label}</span>
                      </span>
                      <span>{formatMiles(route.summary.miles_by_level[risk.key])}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {route.summary?.has_no_travel ? <p className="route-warning">Contains No Travel conditions</p> : null}
            </button>
          )
        })}
      </div>
    </section>
  )
})

export default RouteCards
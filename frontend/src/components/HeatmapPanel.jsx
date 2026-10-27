import { memo, useMemo } from 'react'
import { formatDateTime } from '../utils/format'
import { RISK_LEVELS } from '../utils/risk'

const MS_PER_HOUR = 60 * 60 * 1000

function addHoursToIsoString(isoString, hours) {
  return new Date(Date.parse(isoString) + hours * MS_PER_HOUR).toISOString()
}

const HeatmapPanel = memo(function HeatmapPanel({ heatmap, loading, error, originTimezone, tripDurationSeconds, selectedHour, onHourChange }) {
  const maxHour = Math.max((heatmap?.hours ?? 1) - 1, 0)
  const clampedSelectedHour = Math.min(selectedHour, maxHour)
  const startTime = heatmap?.start_time
  const hasTripDuration = Number.isFinite(tripDurationSeconds)
  const arrivalHour = hasTripDuration ? Math.min(maxHour, Math.round(tripDurationSeconds / 3600)) : null
  const phaseLabel = hasTripDuration ? (clampedSelectedHour <= arrivalHour ? 'During trip' : 'After arrival') : null
  const tripPct = hasTripDuration ? `${(arrivalHour / Math.max(maxHour, 1)) * 100}%` : '0%'

  const hourLabel = useMemo(() => {
    if (!startTime) {
      return 'Forecast hour unavailable'
    }

    const labelTimeZone = originTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone
    return `${formatDateTime(addHoursToIsoString(startTime, clampedSelectedHour), labelTimeZone)} +${clampedSelectedHour} h`
  }, [clampedSelectedHour, originTimezone, startTime])

  const summary = useMemo(() => {
    const countsByIndex = new Map(RISK_LEVELS.map((risk, index) => [index + 1, 0]))
    let noDataCount = 0

    for (const point of heatmap?.points || []) {
      const level = point.levels?.[clampedSelectedHour]
      if (level == null) {
        noDataCount += 1
        continue
      }

      countsByIndex.set(level, (countsByIndex.get(level) || 0) + 1)
    }

    return { countsByIndex, noDataCount }
  }, [clampedSelectedHour, heatmap])

  return (
    <section className="heatmap-panel card-section">
      <div className="heatmap-panel-header">
        <div>
          <h2 className="section-title">Forecast heatmap</h2>
          <p className="heatmap-panel-subtitle">Hourly corridor summary for the selected trip.</p>
        </div>
        {heatmap?.demo_mode ? <span className="heatmap-demo-banner">Demo weather, not real data</span> : null}
      </div>

      {loading ? <p className="heatmap-panel-message">Loading forecast heatmap...</p> : null}
      {error ? <p className="heatmap-panel-message heatmap-panel-error">{error}</p> : null}

      {heatmap ? (
        <div className="heatmap-controls" style={{ '--trip-pct': tripPct }}>
          <label className="heatmap-slider-label" htmlFor="forecast-hour-slider">
            Forecast hour
          </label>
          <input
            id="forecast-hour-slider"
            className="heatmap-slider"
            type="range"
            min="0"
            max={maxHour}
            step="1"
            value={clampedSelectedHour}
            aria-label="Forecast hour"
            onChange={(event) => {
              onHourChange(Number(event.target.value))
            }}
          />
          <div className="heatmap-slider-scale" aria-hidden="true">
            <span>Departure (+0 h)</span>
            {hasTripDuration ? <span>Arrival about +{arrivalHour} h</span> : <span />}
            <span>+{maxHour} h</span>
          </div>
          <p className="heatmap-hour-label" aria-live="polite">
            <span>{hourLabel}</span>
            {phaseLabel ? <span className="heatmap-phase-badge">{phaseLabel}</span> : null}
          </p>

          <ul className="heatmap-summary-list" aria-label="Forecast heatmap summary by risk level">
            {RISK_LEVELS.map((risk, index) => (
              <li key={risk.key} className="heatmap-summary-item">
                <span className="risk-inline">
                  <span className="risk-swatch" style={{ backgroundColor: risk.color }} aria-hidden="true" />
                  <span>{risk.label}</span>
                </span>
                <span>{summary.countsByIndex.get(index + 1) || 0} points</span>
              </li>
            ))}
            {summary.noDataCount > 0 ? (
              <li className="heatmap-summary-item heatmap-summary-item-muted">
                <span>No data</span>
                <span>{summary.noDataCount} points</span>
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </section>
  )
})

export default HeatmapPanel
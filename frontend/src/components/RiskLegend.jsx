import { memo } from 'react'
import { RISK_LEVELS } from '../utils/risk'

const RiskLegend = memo(function RiskLegend() {
  return (
    <section className="risk-legend" aria-label="Risk levels">
      <h2 className="section-title">Risk levels</h2>
      <ul className="risk-legend-list">
        {RISK_LEVELS.map((risk) => (
          <li key={risk.key} className="risk-legend-item">
            <span className="risk-swatch" style={{ backgroundColor: risk.color }} aria-hidden="true" />
            <span>{risk.label}</span>
          </li>
        ))}
      </ul>
    </section>
  )
})

export default RiskLegend
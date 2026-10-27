export default function RiskLabel({ risk }) {
  return (
    <>
      <span className="risk-swatch" style={{ backgroundColor: risk.color }} aria-hidden="true" />
      <span>{risk.label}</span>
    </>
  )
}
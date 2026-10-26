export const RISK_LEVELS = [
  { key: 'LOW', label: 'Low', color: '#1a7f37' },
  { key: 'MODERATE', label: 'Moderate', color: '#c88a00' },
  { key: 'HIGH', label: 'High', color: '#d95f02' },
  { key: 'SEVERE', label: 'Severe', color: '#c62828' },
  { key: 'NO_TRAVEL', label: 'No Travel', color: '#5b2a86' },
]

const RISK_INFO_BY_KEY = Object.fromEntries(RISK_LEVELS.map((risk) => [risk.key, risk]))

const RISK_RADIUS_BY_KEY = {
  LOW: 6,
  MODERATE: 7.5,
  HIGH: 9,
  SEVERE: 10.5,
  NO_TRAVEL: 12,
}

export function getRiskInfo(key) {
  return RISK_INFO_BY_KEY[key] || { key, label: key || 'Unknown', color: '#6b7280' }
}

export function getRiskRadius(key) {
  return RISK_RADIUS_BY_KEY[key] || 6
}
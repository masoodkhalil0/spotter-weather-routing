const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return 'Unknown'
  }

  const totalMinutes = Math.round(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60

  if (hours === 0) {
    return `${minutes} min`
  }

  if (minutes === 0) {
    return `${hours} h`
  }

  return `${hours} h ${minutes} min`
}

export function formatMiles(value) {
  if (!Number.isFinite(value)) {
    return 'Unknown'
  }

  return `${value.toFixed(1)} mi`
}

export function formatDateTime(isoString) {
  if (!isoString || typeof isoString !== 'string') {
    return 'Unknown'
  }

  const date = new Date(isoString)

  if (Number.isNaN(date.getTime())) {
    return 'Unknown'
  }

  return dateTimeFormatter.format(date)
}
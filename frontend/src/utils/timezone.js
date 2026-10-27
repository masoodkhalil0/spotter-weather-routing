const datePartFormatter = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

const timePartFormatter = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export const MAX_DEPARTURE_DAYS = 10
export const MAX_DEPARTURE_WINDOW_MS = MAX_DEPARTURE_DAYS * 24 * 60 * 60 * 1000

function normalizePart(parts, type) {
  return parts.find((part) => part.type === type)?.value || ''
}

export function formatNaiveDeparture(dateValue, timeValue) {
  if (!dateValue || !timeValue) {
    return ''
  }

  return `${dateValue}T${timeValue}:00`
}

export function getWallTimeParts(date, timeZone) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime()) || !timeZone) {
    return null
  }

  const dateParts = datePartFormatter.formatToParts(date)
  const timeParts = timePartFormatter.formatToParts(date)

  return {
    date: `${normalizePart(dateParts, 'year')}-${normalizePart(dateParts, 'month')}-${normalizePart(dateParts, 'day')}`,
    time: `${normalizePart(timeParts, 'hour')}:${normalizePart(timeParts, 'minute')}`,
  }
}

export function isDepartureOutsideAllowedWindow(dateValue, timeValue, timeZone, now = new Date()) {
  if (!dateValue || !timeValue) {
    return true
  }

  if (!timeZone) {
    const departureDate = new Date(`${dateValue}T${timeValue}`)
    const minDate = new Date(now.getTime() - 60 * 60 * 1000)
    const maxDate = new Date(now.getTime() + MAX_DEPARTURE_WINDOW_MS)

    if (Number.isNaN(departureDate.getTime())) {
      return true
    }

    return departureDate < minDate || departureDate > maxDate
  }

  const minAllowed = new Date(now.getTime() - 60 * 60 * 1000)
  const maxAllowed = new Date(now.getTime() + MAX_DEPARTURE_WINDOW_MS)
  const minParts = getWallTimeParts(minAllowed, timeZone)
  const maxParts = getWallTimeParts(maxAllowed, timeZone)

  if (!minParts || !maxParts) {
    return true
  }

  const departureValue = `${dateValue}T${timeValue}`
  return departureValue < `${minParts.date}T${minParts.time}` || departureValue > `${maxParts.date}T${maxParts.time}`
}

export function getTimeZoneAbbreviation(timeZone, date = new Date()) {
  if (!timeZone) {
    return ''
  }

  const formatter = new Intl.DateTimeFormat(undefined, {
    timeZone,
    timeZoneName: 'short',
  })
  const timeZonePart = formatter.formatToParts(date).find((part) => part.type === 'timeZoneName')

  return timeZonePart?.value || ''
}
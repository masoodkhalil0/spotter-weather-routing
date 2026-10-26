import { useState } from 'react'
import PlaceSearch from './PlaceSearch'
import DatePicker from './DatePicker'
import TimePicker from './TimePicker'

const TEN_DAYS_IN_MS = 10 * 24 * 60 * 60 * 1000

function padNumber(value) {
  return String(value).padStart(2, '0')
}

function formatDateInputValue(date) {
  return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`
}

function getDateRange() {
  const today = new Date()
  const maxDate = new Date(today.getTime() + TEN_DAYS_IN_MS)

  return {
    minDate: formatDateInputValue(today),
    maxDate: formatDateInputValue(maxDate),
  }
}

function getInitialDepartureParts() {
  const nextHour = new Date()
  nextHour.setMinutes(0, 0, 0)
  nextHour.setHours(nextHour.getHours() + 1)

  return {
    date: formatDateInputValue(nextHour),
    time: `${padNumber(nextHour.getHours())}:${padNumber(nextHour.getMinutes())}`,
  }
}

function buildDepartureValue(dateValue, timeValue) {
  if (!dateValue || !timeValue) {
    return ''
  }

  return `${dateValue}T${timeValue}`
}

function isDateOutOfRange(dateValue, minDate, maxDate) {
  if (!dateValue) {
    return true
  }

  return dateValue < minDate || dateValue > maxDate
}

function isPastTimeForDate(dateValue, timeValue) {
  if (!dateValue || !timeValue) {
    return true
  }

  const departureDate = new Date(`${dateValue}T${timeValue}`)
  const now = new Date()
  const minDate = new Date(now.getTime() - 60 * 60 * 1000)
  const maxDate = new Date(now.getTime() + TEN_DAYS_IN_MS)

  if (Number.isNaN(departureDate.getTime())) {
    return true
  }

  return departureDate < minDate || departureDate > maxDate
}

// Calculate the straight-line distance between two latitude/longitude points in miles.
function getDistanceInMiles(origin, destination) {
  const earthRadiusMiles = 3958.8
  const toRadians = (degrees) => (degrees * Math.PI) / 180
  const latitudeDelta = toRadians(destination.lat - origin.lat)
  const longitudeDelta = toRadians(destination.lon - origin.lon)
  const originLatitude = toRadians(origin.lat)
  const destinationLatitude = toRadians(destination.lat)

  const haversineValue =
    Math.sin(latitudeDelta / 2) * Math.sin(latitudeDelta / 2) +
    Math.cos(originLatitude) * Math.cos(destinationLatitude) * Math.sin(longitudeDelta / 2) * Math.sin(longitudeDelta / 2)

  const centralAngle = 2 * Math.atan2(Math.sqrt(haversineValue), Math.sqrt(1 - haversineValue))

  return earthRadiusMiles * centralAngle
}

function TripForm({ onSubmit, loading }) {
  const initialDeparture = getInitialDepartureParts()

  const [origin, setOrigin] = useState(null)
  const [destination, setDestination] = useState(null)
  const [departureDate, setDepartureDate] = useState(initialDeparture.date)
  const [departureTime, setDepartureTime] = useState(initialDeparture.time)
  const [loadWeight, setLoadWeight] = useState('30000')
  const [errors, setErrors] = useState({})
  const [dateRange] = useState(() => getDateRange())

  function clearError(fieldName) {
    setErrors((currentErrors) => {
      if (!currentErrors[fieldName]) {
        return currentErrors
      }

      const nextErrors = { ...currentErrors }
      delete nextErrors[fieldName]
      return nextErrors
    })
  }

  function handleOriginSelect(place) {
    setOrigin(place)
    clearError('origin')
    clearError('destination')
  }

  function handleDestinationSelect(place) {
    setDestination(place)
    clearError('destination')
    clearError('origin')
  }

  function validateForm() {
    const nextErrors = {}
    const departure = buildDepartureValue(departureDate, departureTime)

    if (!origin) {
      nextErrors.origin = 'Please choose an origin from the search results.'
    }

    if (!destination) {
      nextErrors.destination = 'Please choose a destination from the search results.'
    }

    if (origin && destination) {
      const distanceInMiles = getDistanceInMiles(origin, destination)

      if (distanceInMiles < 0.5) {
        nextErrors.destination = 'Origin and destination must be at least 0.5 miles apart.'
      }
    }

    if (!departureDate) {
      nextErrors.departureDate = 'Please choose a departure date and time.'
    } else if (isDateOutOfRange(departureDate, dateRange.minDate, dateRange.maxDate)) {
      nextErrors.departureDate = 'Departure must be between 1 hour ago and 10 days from now.'
    }

    if (!departureTime) {
      nextErrors.departureTime = 'Please choose a departure date and time.'
    } else if (departure && isPastTimeForDate(departureDate, departureTime)) {
      nextErrors.departureTime = 'Departure must be between 1 hour ago and 10 days from now.'
    }

    if (!/^\d+$/.test(loadWeight)) {
      nextErrors.loadWeight = 'Load weight must be a whole number.'
    } else {
      const numericWeight = Number(loadWeight)

      if (numericWeight < 0 || numericWeight > 80000) {
        nextErrors.loadWeight = 'Load weight must be between 0 and 80000 lb.'
      }
    }

    setErrors(nextErrors)
    return Object.keys(nextErrors).length === 0
  }

  function handleSubmit(event) {
    event.preventDefault()

    if (!validateForm()) {
      return
    }

    const departure = buildDepartureValue(departureDate, departureTime)

    onSubmit({
      origin: { lat: origin.lat, lon: origin.lon },
      destination: { lat: destination.lat, lon: destination.lon },
      departure: new Date(departure).toISOString(),
      load_weight_lb: Number(loadWeight),
    })
  }

  return (
    <form className="trip-form" onSubmit={handleSubmit} noValidate>
      <PlaceSearch label="Origin" value={origin} onSelect={handleOriginSelect} />
      {errors.origin ? <p className="error-text" role="alert">Error: {errors.origin}</p> : null}

      <PlaceSearch label="Destination" value={destination} onSelect={handleDestinationSelect} />
      {errors.destination ? <p className="error-text" role="alert">Error: {errors.destination}</p> : null}

      <div className="departure-grid">
        <DatePicker
          id="departure-date-input"
          label="Departure date"
          helperText="Choose a date from today through the next 10 days."
          value={departureDate}
          min={dateRange.minDate}
          max={dateRange.maxDate}
          onChange={(nextDate) => {
            setDepartureDate(nextDate)
            clearError('departureDate')
          }}
          onBlur={(isValid) => {
            if (isValid) {
              clearError('departureDate')
            }
          }}
          error={errors.departureDate}
        />

        <TimePicker
          id="departure-time-input"
          label="Departure time"
          helperText="Type a time or choose one from the clock."
          value={departureTime}
          onChange={(nextTime) => {
            setDepartureTime(nextTime)
            clearError('departureTime')
          }}
          onBlur={(isValid) => {
            if (isValid) {
              clearError('departureTime')
            }
          }}
          error={errors.departureTime}
        />
      </div>

      <div className="field-group">
        <label className="field-label" htmlFor="load-weight-input">
          Load weight (lb)
        </label>
        <p className="field-helper-text">Enter the total cargo weight as a whole number.</p>
        <input
          id="load-weight-input"
          className="text-input"
          type="number"
          inputMode="numeric"
          min="0"
          max="80000"
          step="1"
          value={loadWeight}
          onChange={(event) => {
            setLoadWeight(event.target.value)
            clearError('loadWeight')
          }}
        />
        {errors.loadWeight ? <p className="error-text" role="alert">Error: {errors.loadWeight}</p> : null}
      </div>

      <button className="submit-button" type="submit" disabled={loading}>
        {loading ? 'Planning route...' : 'Plan route'}
      </button>
    </form>
  )
}

export default TripForm
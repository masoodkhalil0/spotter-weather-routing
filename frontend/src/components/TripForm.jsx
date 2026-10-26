import { useState } from 'react'
import PlaceSearch from './PlaceSearch'

function getNextFullHourLocalValue() {
  const nextHour = new Date()
  nextHour.setMinutes(0, 0, 0)
  nextHour.setHours(nextHour.getHours() + 1)

  const year = nextHour.getFullYear()
  const month = String(nextHour.getMonth() + 1).padStart(2, '0')
  const day = String(nextHour.getDate()).padStart(2, '0')
  const hours = String(nextHour.getHours()).padStart(2, '0')
  const minutes = String(nextHour.getMinutes()).padStart(2, '0')

  return `${year}-${month}-${day}T${hours}:${minutes}`
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
  const [origin, setOrigin] = useState(null)
  const [destination, setDestination] = useState(null)
  const [departure, setDeparture] = useState(getNextFullHourLocalValue)
  const [loadWeight, setLoadWeight] = useState('30000')
  const [errors, setErrors] = useState({})

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

    if (!departure) {
      nextErrors.departure = 'Please choose a departure date and time.'
    } else {
      const departureDate = new Date(departure)
      const now = new Date()
      const minDate = new Date(now.getTime() - 60 * 60 * 1000)
      const maxDate = new Date(now.getTime() + 10 * 24 * 60 * 60 * 1000)

      if (Number.isNaN(departureDate.getTime())) {
        nextErrors.departure = 'Please enter a valid departure date and time.'
      } else if (departureDate < minDate || departureDate > maxDate) {
        nextErrors.departure = 'Departure must be between 1 hour ago and 10 days from now.'
      }
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

      <div className="field-group">
        <label className="field-label" htmlFor="departure-input">
          Departure
        </label>
        <input
          id="departure-input"
          className="text-input"
          type="datetime-local"
          value={departure}
          onChange={(event) => {
            setDeparture(event.target.value)
            clearError('departure')
          }}
        />
        {errors.departure ? <p className="error-text" role="alert">Error: {errors.departure}</p> : null}
      </div>

      <div className="field-group">
        <label className="field-label" htmlFor="load-weight-input">
          Load weight (lb)
        </label>
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
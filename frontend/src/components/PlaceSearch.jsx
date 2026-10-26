import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { geocode } from '../api/client'

function PlaceSearch({ label, value, onSelect }) {
  const [inputValue, setInputValue] = useState(value ? value.label : '')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)

  const searchControllerRef = useRef(null)
  const debounceTimerRef = useRef(null)
  const wrapperRef = useRef(null)
  const listboxId = useId()
  const inputId = useId()

  useEffect(() => {
    function handleClickOutside(event) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
        setIsOpen(false)
        setActiveIndex(-1)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        window.clearTimeout(debounceTimerRef.current)
      }

      if (searchControllerRef.current) {
        searchControllerRef.current.abort()
      }
    }
  }, [])

  const activeOptionId = useMemo(() => {
    if (activeIndex < 0 || activeIndex >= results.length) {
      return undefined
    }

    return `${listboxId}-option-${activeIndex}`
  }, [activeIndex, listboxId, results.length])

  function choosePlace(place) {
    setInputValue(place.label)
    setResults([])
    setLoading(false)
    setErrorMessage('')
    setIsOpen(false)
    setActiveIndex(-1)

    if (debounceTimerRef.current) {
      window.clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }

    if (searchControllerRef.current) {
      searchControllerRef.current.abort()
      searchControllerRef.current = null
    }

    onSelect(place)
  }

  function handleInputChange(event) {
    const nextValue = event.target.value
    const trimmedValue = nextValue.trim()

    setInputValue(nextValue)

    if (value) {
      onSelect(null)
    }

    if (debounceTimerRef.current) {
      window.clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }

    if (searchControllerRef.current) {
      searchControllerRef.current.abort()
      searchControllerRef.current = null
    }

    if (trimmedValue.length < 3) {
      setResults([])
      setLoading(false)
      setErrorMessage('')
      setIsOpen(false)
      setActiveIndex(-1)
      return
    }

    setResults([])
    setLoading(true)
    setErrorMessage('')
    setIsOpen(true)
    setActiveIndex(-1)

    debounceTimerRef.current = window.setTimeout(async () => {
      const controller = new AbortController()
      searchControllerRef.current = controller

      try {
        const data = await geocode(trimmedValue, { signal: controller.signal })
        const nextResults = Array.isArray(data.results) ? data.results.slice(0, 5) : []

        setResults(nextResults)
        setErrorMessage('')
        setIsOpen(true)
        setActiveIndex(nextResults.length > 0 ? 0 : -1)
      } catch (error) {
        if (error.name === 'AbortError') {
          return
        }

        setResults([])
        setIsOpen(true)
        setActiveIndex(-1)
        setErrorMessage(error.message || 'Unable to search for places right now.')
      } finally {
        // A stale request must not overwrite the loading state for a newer search.
        if (searchControllerRef.current === controller) {
          setLoading(false)
          searchControllerRef.current = null
        }
      }
    }, 400)
  }

  function handleKeyDown(event) {
    if (!isOpen && event.key === 'ArrowDown' && results.length > 0) {
      setIsOpen(true)
      setActiveIndex(0)
      return
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((currentIndex) => {
        if (results.length === 0) {
          return -1
        }

        return currentIndex < results.length - 1 ? currentIndex + 1 : 0
      })
      setIsOpen(true)
      return
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((currentIndex) => {
        if (results.length === 0) {
          return -1
        }

        return currentIndex > 0 ? currentIndex - 1 : results.length - 1
      })
      setIsOpen(true)
      return
    }

    if (event.key === 'Enter' && isOpen && activeIndex >= 0 && activeIndex < results.length) {
      event.preventDefault()
      choosePlace(results[activeIndex])
      return
    }

    if (event.key === 'Escape') {
      setIsOpen(false)
      setActiveIndex(-1)
    }
  }

  const showNoResults = isOpen && !loading && !errorMessage && inputValue.trim().length >= 3 && results.length === 0
  const showDropdown = isOpen && (loading || errorMessage || showNoResults || results.length > 0)

  return (
    <div className="field-group" ref={wrapperRef}>
      <label className="field-label" htmlFor={inputId}>
        {label}
      </label>

      <div className="combobox-wrapper">
        <input
          id={inputId}
          className="text-input"
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          onFocus={() => {
            if (loading || errorMessage || results.length > 0) {
              setIsOpen(true)
            }
          }}
          onKeyDown={handleKeyDown}
          placeholder="Search for a city or address"
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showDropdown}
          aria-controls={listboxId}
          aria-activedescendant={activeOptionId}
        />

        {showDropdown ? (
          <ul className="search-dropdown" id={listboxId} role="listbox">
            {loading ? <li className="search-status">Searching...</li> : null}

            {!loading && errorMessage ? <li className="search-status error-text">Error: {errorMessage}</li> : null}

            {!loading && !errorMessage && results.length > 0
              ? results.map((place, index) => (
                  <li
                    key={`${place.lat}-${place.lon}-${index}`}
                    id={`${listboxId}-option-${index}`}
                    className={`search-option ${index === activeIndex ? 'search-option-active' : ''}`}
                    role="option"
                    aria-selected={index === activeIndex}
                    onMouseDown={(event) => {
                      event.preventDefault()
                      choosePlace(place)
                    }}
                    onMouseEnter={() => {
                      setActiveIndex(index)
                    }}
                  >
                    {place.label}
                  </li>
                ))
              : null}

            {showNoResults ? <li className="search-status">No places found</li> : null}
          </ul>
        ) : null}
      </div>

      {value ? <p className="selected-note">Selected: {value.label}</p> : null}
    </div>
  )
}

export default PlaceSearch
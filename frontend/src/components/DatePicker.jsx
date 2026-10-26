import { memo, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

const WEEKDAY_LABELS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const CALENDAR_GRID_DAYS = 42
const POPOVER_WIDTH = 264
const POPOVER_MARGIN = 8
const POPOVER_ESTIMATED_HEIGHT = 340

function padNumber(value) {
  return String(value).padStart(2, '0')
}

function stripDigits(value, maxLength) {
  return value.replace(/\D/g, '').slice(0, maxLength)
}

function parseIsoDateParts(value) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/)

  if (!match) {
    return null
  }

  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
  }
}

function createLocalDate(year, month, day) {
  const date = new Date(year, month - 1, day)

  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null
  }

  date.setHours(0, 0, 0, 0)
  return date
}

function formatIsoDate(date) {
  return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`
}

function formatSegments(value) {
  const parts = parseIsoDateParts(value)

  if (!parts) {
    return { day: '', month: '', year: '' }
  }

  return {
    day: padNumber(parts.day),
    month: padNumber(parts.month),
    year: String(parts.year),
  }
}

function compareDates(leftDate, rightDate) {
  return leftDate.getTime() - rightDate.getTime()
}

function addDays(date, days) {
  const nextDate = new Date(date)
  nextDate.setDate(nextDate.getDate() + days)
  nextDate.setHours(0, 0, 0, 0)
  return nextDate
}

function getMonthLabel(date) {
  return date.toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  })
}

function getCalendarDays(visibleMonth) {
  const firstDayOfMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1)
  firstDayOfMonth.setHours(0, 0, 0, 0)
  const gridStart = addDays(firstDayOfMonth, -firstDayOfMonth.getDay())

  return Array.from({ length: CALENDAR_GRID_DAYS }, (_, index) => addDays(gridStart, index))
}

function buildPopoverStyle(bounds, popoverHeight) {
  const availableBelow = window.innerHeight - bounds.bottom - POPOVER_MARGIN
  const availableAbove = bounds.top - POPOVER_MARGIN
  const shouldOpenBelow = availableBelow >= popoverHeight || availableBelow >= availableAbove
  const maxHeight = Math.max(120, shouldOpenBelow ? availableBelow : availableAbove)
  const unclampedTop = shouldOpenBelow ? bounds.bottom + 8 : bounds.top - Math.min(popoverHeight, maxHeight) - 8
  const maxTop = window.innerHeight - Math.min(popoverHeight, maxHeight) - POPOVER_MARGIN

  return {
    left: Math.min(Math.max(POPOVER_MARGIN, bounds.left), window.innerWidth - POPOVER_WIDTH - POPOVER_MARGIN),
    top: Math.min(Math.max(POPOVER_MARGIN, unclampedTop), Math.max(POPOVER_MARGIN, maxTop)),
    width: POPOVER_WIDTH,
    maxHeight,
  }
}

function getErrorMessage(helperId, errorId) {
  const ids = []

  if (helperId) {
    ids.push(helperId)
  }

  if (errorId) {
    ids.push(errorId)
  }

  return ids.length > 0 ? ids.join(' ') : undefined
}

function clampSegment(value, minValue, maxValue) {
  if (value < minValue) {
    return maxValue
  }

  if (value > maxValue) {
    return minValue
  }

  return value
}

function validateSegmentDate(dayText, monthText, yearText, minDate, maxDate) {
  if (!dayText || !monthText || !yearText) {
    return { valid: false, message: 'Please enter a departure date.' }
  }

  if (dayText.length !== 2 || monthText.length !== 2 || yearText.length !== 4) {
    return { valid: false, message: 'Complete the full departure date.' }
  }

  const day = Number(dayText)
  const month = Number(monthText)
  const year = Number(yearText)
  const date = createLocalDate(year, month, day)

  if (!date) {
    return { valid: false, message: 'Enter a real calendar date.' }
  }

  if ((minDate && compareDates(date, minDate) < 0) || (maxDate && compareDates(date, maxDate) > 0)) {
    return { valid: false, message: 'Departure must be between today and 10 days from now.' }
  }

  return { valid: true, isoDate: formatIsoDate(date), date }
}

const DatePicker = memo(function DatePicker({
  id,
  label,
  helperText,
  value,
  min,
  max,
  onChange,
  onBlur,
  error,
}) {
  const initialSegments = formatSegments(value)
  const [dayText, setDayText] = useState(initialSegments.day)
  const [monthText, setMonthText] = useState(initialSegments.month)
  const [yearText, setYearText] = useState(initialSegments.year)
  const [inlineError, setInlineError] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [draftValue, setDraftValue] = useState(value)
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const parts = parseIsoDateParts(value)
    return parts ? new Date(parts.year, parts.month - 1, 1) : new Date()
  })
  const [popoverStyle, setPopoverStyle] = useState(null)
  const [today] = useState(() => {
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    return now
  })

  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const dialogRef = useRef(null)
  const dayInputRef = useRef(null)
  const monthInputRef = useRef(null)
  const yearInputRef = useRef(null)

  const labelId = useId()
  const helperId = helperText ? `${id}-helper` : undefined
  const errorId = inlineError || error ? `${id}-error` : undefined
  const dialogLabelId = `${id}-dialog-label`

  const minDate = useMemo(() => {
    const parts = parseIsoDateParts(min)
    return parts ? createLocalDate(parts.year, parts.month, parts.day) : null
  }, [min])
  const maxDate = useMemo(() => {
    const parts = parseIsoDateParts(max)
    return parts ? createLocalDate(parts.year, parts.month, parts.day) : null
  }, [max])
  const draftSelectedDate = useMemo(() => {
    const parts = parseIsoDateParts(draftValue)
    return parts ? createLocalDate(parts.year, parts.month, parts.day) : null
  }, [draftValue])
  const calendarDays = useMemo(() => getCalendarDays(visibleMonth), [visibleMonth])
  const describedBy = getErrorMessage(helperId, errorId)

  useEffect(() => {
    const nextSegments = formatSegments(value)
    setDayText((currentValue) => (document.activeElement === dayInputRef.current ? currentValue : nextSegments.day))
    setMonthText((currentValue) => (document.activeElement === monthInputRef.current ? currentValue : nextSegments.month))
    setYearText((currentValue) => (document.activeElement === yearInputRef.current ? currentValue : nextSegments.year))
  }, [value])

  useEffect(() => {
    if (!isOpen) {
      return undefined
    }

    function handleOutsideClick(event) {
      if (rootRef.current && !rootRef.current.contains(event.target) && dialogRef.current && !dialogRef.current.contains(event.target)) {
        setIsOpen(false)
        setDraftValue(value)
      }
    }

    function handleEscape(event) {
      if (event.key === 'Escape') {
        event.preventDefault()
        setIsOpen(false)
        setDraftValue(value)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isOpen, value])

  useLayoutEffect(() => {
    if (!isOpen || !rootRef.current) {
      return undefined
    }

    const triggerButton = buttonRef.current

    function updatePosition() {
      const triggerBounds = rootRef.current.getBoundingClientRect()
      setPopoverStyle(buildPopoverStyle(triggerBounds, POPOVER_ESTIMATED_HEIGHT))
    }

    updatePosition()
    dialogRef.current?.focus()
    window.addEventListener('resize', updatePosition)

    return () => {
      window.removeEventListener('resize', updatePosition)
      triggerButton?.focus()
    }
  }, [isOpen])

  function syncSegmentsFromValue(nextValue) {
    const nextSegments = formatSegments(nextValue)
    setDayText(nextSegments.day)
    setMonthText(nextSegments.month)
    setYearText(nextSegments.year)
  }

  function commitIfComplete(nextDay, nextMonth, nextYear) {
    const parsed = validateSegmentDate(nextDay, nextMonth, nextYear, minDate, maxDate)

    if (!parsed.valid) {
      return parsed
    }

    setInlineError('')
    onChange(parsed.isoDate)
    return parsed
  }

  function attemptBlurCommit() {
    const parsed = validateSegmentDate(dayText, monthText, yearText, minDate, maxDate)

    if (!parsed.valid) {
      setInlineError(parsed.message)
      const activeElement = document.activeElement
      const isInsideField = activeElement === dayInputRef.current || activeElement === monthInputRef.current || activeElement === yearInputRef.current

      if (!isInsideField) {
        syncSegmentsFromValue(value)
      }

      onBlur?.(false)
      return
    }

    setInlineError('')
    onChange(parsed.isoDate)
    onBlur?.(true)
  }

  function handleSegmentChange(segment, nextValue) {
    const digits = stripDigits(nextValue, segment === 'year' ? 4 : 2)

    if (segment === 'day') {
      setDayText(digits)

      if (digits.length === 2) {
        monthInputRef.current?.focus()
      }

      if (digits.length === 2 && monthText.length === 2 && yearText.length === 4) {
        commitIfComplete(digits, monthText, yearText)
      }

      return
    }

    if (segment === 'month') {
      setMonthText(digits)

      if (digits.length === 2) {
        yearInputRef.current?.focus()
      }

      if (dayText.length === 2 && digits.length === 2 && yearText.length === 4) {
        commitIfComplete(dayText, digits, yearText)
      }

      return
    }

    setYearText(digits)

    if (dayText.length === 2 && monthText.length === 2 && digits.length === 4) {
      commitIfComplete(dayText, monthText, digits)
    }
  }

  function handleSegmentKeyDown(event, segment) {
    const segmentMap = {
      day: { value: dayText, minValue: 1, maxValue: 31, setter: setDayText, length: 2, nextRef: monthInputRef, previousRef: null },
      month: { value: monthText, minValue: 1, maxValue: 12, setter: setMonthText, length: 2, nextRef: yearInputRef, previousRef: dayInputRef },
      year: {
        value: yearText,
        minValue: minDate ? minDate.getFullYear() : 0,
        maxValue: maxDate ? maxDate.getFullYear() : 9999,
        setter: setYearText,
        length: 4,
        nextRef: null,
        previousRef: monthInputRef,
      },
    }

    const config = segmentMap[segment]

    if (event.key === 'Backspace' && !config.value) {
      event.preventDefault()
      config.previousRef?.current?.focus()
      return
    }

    if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && config) {
      event.preventDefault()
      const direction = event.key === 'ArrowUp' ? 1 : -1
      const baseValue = config.value ? Number(config.value) : config.minValue
      const nextNumericValue = clampSegment(baseValue + direction, config.minValue, config.maxValue)
      const nextValue = String(nextNumericValue).padStart(config.length, '0')
      config.setter(nextValue)

      const nextDay = segment === 'day' ? nextValue : dayText
      const nextMonth = segment === 'month' ? nextValue : monthText
      const nextYear = segment === 'year' ? nextValue : yearText

      if (nextDay.length === 2 && nextMonth.length === 2 && nextYear.length === 4) {
        commitIfComplete(nextDay, nextMonth, nextYear)
      }
    }
  }

  function handleFieldBlur() {
    window.setTimeout(() => {
      const activeElement = document.activeElement
      const isStillInside = activeElement === dayInputRef.current || activeElement === monthInputRef.current || activeElement === yearInputRef.current

      if (!isStillInside) {
        attemptBlurCommit()
      }
    }, 0)
  }

  function openPopover() {
    const baseValue = value || min
    const baseParts = parseIsoDateParts(baseValue)
    const nextMonth = baseParts ? new Date(baseParts.year, baseParts.month - 1, 1) : today

    setDraftValue(value)
    setVisibleMonth(nextMonth)
    setInlineError('')

    if (rootRef.current) {
      setPopoverStyle(buildPopoverStyle(rootRef.current.getBoundingClientRect(), POPOVER_ESTIMATED_HEIGHT))
    }

    setIsOpen(true)
  }

  function closePopover() {
    setIsOpen(false)
    setDraftValue(value)
  }

  function changeMonth(offset) {
    setVisibleMonth((currentMonth) => new Date(currentMonth.getFullYear(), currentMonth.getMonth() + offset, 1))
  }

  function isDisabledDate(date) {
    if (minDate && compareDates(date, minDate) < 0) {
      return true
    }

    if (maxDate && compareDates(date, maxDate) > 0) {
      return true
    }

    return false
  }

  function handleGridKeyDown(event) {
    const increments = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    }

    const increment = increments[event.key]

    if (increment === undefined || !draftSelectedDate) {
      return
    }

    event.preventDefault()
    const nextDate = addDays(draftSelectedDate, increment)

    if (isDisabledDate(nextDate)) {
      return
    }

    setDraftValue(formatIsoDate(nextDate))
    setVisibleMonth(new Date(nextDate.getFullYear(), nextDate.getMonth(), 1))
  }

  function confirmPopover() {
    if (!draftValue) {
      return
    }

    syncSegmentsFromValue(draftValue)
    onChange(draftValue)
    setInlineError('')
    setIsOpen(false)
    onBlur?.(true)
  }

  return (
    <div className="field-group date-picker" ref={rootRef}>
      <label className="field-label" id={labelId}>
        {label}
      </label>
      {helperText ? (
        <p className="field-helper-text" id={helperId}>
          {helperText}
        </p>
      ) : null}

      <div className="segmented-input-shell" onBlur={handleFieldBlur}>
        <span className="input-leading-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M7 3v3m10-3v3M4 9h16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <rect x="4" y="5" width="16" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </span>

        <div className="segmented-input has-leading-icon has-trailing-button" role="group" aria-labelledby={labelId} aria-describedby={describedBy}>
          <input
            ref={dayInputRef}
            className="segment-input segment-input-short"
            type="text"
            inputMode="numeric"
            maxLength={2}
            placeholder="DD"
            value={dayText}
            onChange={(event) => handleSegmentChange('day', event.target.value)}
            onKeyDown={(event) => handleSegmentKeyDown(event, 'day')}
            aria-label="Departure day"
            aria-invalid={inlineError || error ? 'true' : undefined}
          />
          <span className="segment-separator" aria-hidden="true">
            /
          </span>
          <input
            ref={monthInputRef}
            className="segment-input segment-input-short"
            type="text"
            inputMode="numeric"
            maxLength={2}
            placeholder="MM"
            value={monthText}
            onChange={(event) => handleSegmentChange('month', event.target.value)}
            onKeyDown={(event) => handleSegmentKeyDown(event, 'month')}
            aria-label="Departure month"
            aria-invalid={inlineError || error ? 'true' : undefined}
          />
          <span className="segment-separator" aria-hidden="true">
            /
          </span>
          <input
            ref={yearInputRef}
            className="segment-input segment-input-year"
            type="text"
            inputMode="numeric"
            maxLength={4}
            placeholder="YYYY"
            value={yearText}
            onChange={(event) => handleSegmentChange('year', event.target.value)}
            onKeyDown={(event) => handleSegmentKeyDown(event, 'year')}
            aria-label="Departure year"
            aria-invalid={inlineError || error ? 'true' : undefined}
          />
        </div>

        <button
          ref={buttonRef}
          className="input-action-button"
          type="button"
          aria-label="Open calendar"
          aria-haspopup="dialog"
          aria-expanded={isOpen}
          onClick={openPopover}
        >
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M7 3v3m10-3v3M4 9h16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <rect x="4" y="5" width="16" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </button>
      </div>

      {inlineError || error ? (
        <p className="error-text" id={errorId} role="alert">
          Error: {inlineError || error}
        </p>
      ) : null}

      {isOpen && popoverStyle ? (
        <div ref={dialogRef} className="picker-popover" role="dialog" aria-label="Choose departure date" aria-labelledby={dialogLabelId} tabIndex={-1} style={popoverStyle}>
          <div className="picker-popover-header">
            <div>
              <p className="picker-popover-label" id={dialogLabelId}>
                Choose departure date
              </p>
              <h3 className="picker-popover-title">{getMonthLabel(visibleMonth)}</h3>
            </div>
            <div className="picker-nav-buttons" role="group" aria-label="Change month">
              <button className="secondary-button picker-nav-button" type="button" onClick={() => changeMonth(-1)}>
                ‹
              </button>
              <button className="secondary-button picker-nav-button" type="button" onClick={() => changeMonth(1)}>
                ›
              </button>
            </div>
          </div>

          <div className="calendar-grid-shell">
            <div className="calendar-weekdays" aria-hidden="true">
              {WEEKDAY_LABELS.map((labelText) => (
                <span key={labelText}>{labelText}</span>
              ))}
            </div>
            <div className="calendar-grid" tabIndex={0} role="grid" aria-label="Calendar days" onKeyDown={handleGridKeyDown}>
              {calendarDays.map((day) => {
                const isoValue = formatIsoDate(day)
                const disabled = isDisabledDate(day)
                const isOutsideMonth = day.getMonth() !== visibleMonth.getMonth()
                const isSelected = draftValue === isoValue
                const isToday = compareDates(day, today) === 0

                return (
                  <button
                    key={isoValue}
                    className={`calendar-day ${isSelected ? 'is-selected' : ''} ${isToday ? 'is-today' : ''} ${isOutsideMonth ? 'is-outside-month' : ''}`}
                    type="button"
                    role="gridcell"
                    aria-selected={isSelected}
                    disabled={disabled}
                    onClick={() => {
                      setDraftValue(isoValue)
                      setVisibleMonth(new Date(day.getFullYear(), day.getMonth(), 1))
                    }}
                  >
                    {day.getDate()}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="picker-popover-footer">
            <button className="secondary-button picker-footer-button" type="button" onClick={closePopover}>
              Cancel
            </button>
            <button className="submit-button picker-confirm-button picker-footer-button" type="button" onClick={confirmPopover}>
              OK
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
})

export default DatePicker
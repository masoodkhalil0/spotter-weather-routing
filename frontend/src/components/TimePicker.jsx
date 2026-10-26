import { memo, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

const CLOCK_SIZE = 168
const CLOCK_CENTER = CLOCK_SIZE / 2
const CLOCK_RADIUS = 60
const POINTER_CENTER_OFFSET = 10
const MINUTE_VALUES = Array.from({ length: 12 }, (_, index) => index * 5)
const POPOVER_WIDTH = 264
const POPOVER_MARGIN = 8
const POPOVER_ESTIMATED_HEIGHT = 320

function padTime(value) {
  return String(value).padStart(2, '0')
}

function stripDigits(value, maxLength) {
  return value.replace(/\D/g, '').slice(0, maxLength)
}

function get12HourParts(value24) {
  const [hoursText = '00', minutesText = '00'] = value24.split(':')
  const hours24 = Number(hoursText)
  const minutes = Number(minutesText)
  const period = hours24 >= 12 ? 'PM' : 'AM'
  const hours12 = hours24 % 12 || 12

  return {
    hours12,
    minutes,
    period,
  }
}

function to24HourValue(hours12, minutes, period) {
  const normalizedHours = hours12 % 12
  const hours24 = period === 'PM' ? normalizedHours + 12 : normalizedHours
  return `${padTime(hours24)}:${padTime(minutes)}`
}

function getPopoverStyle(bounds, popoverHeight) {
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

function clampHour(value) {
  if (value < 1) {
    return 12
  }

  if (value > 12) {
    return 1
  }

  return value
}

function clampMinute(value) {
  if (value < 0) {
    return 59
  }

  if (value > 59) {
    return 0
  }

  return value
}

function getDialPosition(clientX, clientY, bounds) {
  const x = clientX - bounds.left - CLOCK_CENTER
  const y = clientY - bounds.top - CLOCK_CENTER
  const angle = Math.atan2(y, x) + Math.PI / 2
  return angle < 0 ? angle + Math.PI * 2 : angle
}

function getHourFromAngle(angle) {
  const step = Math.round(angle / (Math.PI / 6)) % 12
  return step === 0 ? 12 : step
}

function getMinuteFromAngle(angle) {
  const step = Math.round(angle / (Math.PI / 6)) % 12
  return MINUTE_VALUES[step]
}

function getPointForValue(index) {
  const angle = (Math.PI / 6) * index - Math.PI / 2
  return {
    x: CLOCK_CENTER + Math.cos(angle) * CLOCK_RADIUS,
    y: CLOCK_CENTER + Math.sin(angle) * CLOCK_RADIUS,
  }
}

function getDescribedBy(helperId, errorId) {
  const parts = []

  if (helperId) {
    parts.push(helperId)
  }

  if (errorId) {
    parts.push(errorId)
  }

  return parts.length > 0 ? parts.join(' ') : undefined
}

function validateSegmentTime(hourText, minuteText, period) {
  if (!hourText || !minuteText) {
    return { valid: false, message: 'Please enter a departure time.' }
  }

  if (hourText.length !== 2 || minuteText.length !== 2) {
    return { valid: false, message: 'Complete the full departure time.' }
  }

  const hours12 = Number(hourText)
  const minutes = Number(minuteText)

  if (hours12 < 1 || hours12 > 12 || minutes < 0 || minutes > 59) {
    return { valid: false, message: 'Enter a valid time from 1:00 to 12:59.' }
  }

  return { valid: true, value24: to24HourValue(hours12, minutes, period) }
}

const TimePicker = memo(function TimePicker({
  id,
  label,
  helperText,
  value,
  onChange,
  onBlur,
  error,
}) {
  const initialParts = get12HourParts(value)
  const [isOpen, setIsOpen] = useState(false)
  const [mode, setMode] = useState('hour')
  const [draftValue, setDraftValue] = useState(value)
  const [hourText, setHourText] = useState(padTime(initialParts.hours12))
  const [minuteText, setMinuteText] = useState(padTime(initialParts.minutes))
  const [period, setPeriod] = useState(initialParts.period)
  const [inlineError, setInlineError] = useState('')
  const [popoverStyle, setPopoverStyle] = useState(null)

  const rootRef = useRef(null)
  const buttonRef = useRef(null)
  const dialogRef = useRef(null)
  const dialRef = useRef(null)
  const hourInputRef = useRef(null)
  const minuteInputRef = useRef(null)
  const periodButtonRef = useRef(null)
  const pointerCaptureRef = useRef(false)

  const labelId = useId()
  const helperId = helperText ? `${id}-helper` : undefined
  const visibleError = inlineError || error
  const errorId = visibleError ? `${id}-error` : undefined
  const dialogLabelId = `${id}-dialog-label`
  const describedBy = getDescribedBy(helperId, errorId)

  const activeValue = isOpen ? draftValue : value
  const activeParts = useMemo(() => get12HourParts(activeValue), [activeValue])

  useEffect(() => {
    const nextParts = get12HourParts(value)

    setHourText((currentValue) => (document.activeElement === hourInputRef.current ? currentValue : padTime(nextParts.hours12)))
    setMinuteText((currentValue) => (document.activeElement === minuteInputRef.current ? currentValue : padTime(nextParts.minutes)))
    setPeriod((currentValue) => (document.activeElement === periodButtonRef.current ? currentValue : nextParts.period))
  }, [value])

  useEffect(() => {
    if (!isOpen) {
      return undefined
    }

    function handlePointerDown(event) {
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

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isOpen, value])

  useLayoutEffect(() => {
    if (!isOpen || !rootRef.current) {
      return undefined
    }

    const triggerButton = buttonRef.current

    function updatePosition() {
      setPopoverStyle(getPopoverStyle(rootRef.current.getBoundingClientRect(), POPOVER_ESTIMATED_HEIGHT))
    }

    updatePosition()
    dialogRef.current?.focus()
    window.addEventListener('resize', updatePosition)

    return () => {
      window.removeEventListener('resize', updatePosition)
      triggerButton?.focus()
    }
  }, [isOpen])

  const dialNumbers = useMemo(() => {
    if (mode === 'hour') {
      return Array.from({ length: 12 }, (_, index) => {
        const hourValue = index === 0 ? 12 : index
        const point = getPointForValue(hourValue % 12)
        return {
          key: `hour-${hourValue}`,
          label: String(hourValue),
          value: hourValue,
          x: point.x,
          y: point.y,
        }
      })
    }

    return MINUTE_VALUES.map((minuteValue, index) => {
      const point = getPointForValue(index)
      return {
        key: `minute-${minuteValue}`,
        label: padTime(minuteValue),
        value: minuteValue,
        x: point.x,
        y: point.y,
      }
    })
  }, [mode])

  const selectedDialValue = mode === 'hour' ? activeParts.hours12 : activeParts.minutes - (activeParts.minutes % 5)
  const selectedDialIndex = mode === 'hour' ? activeParts.hours12 % 12 : MINUTE_VALUES.indexOf(selectedDialValue)
  const handPoint = getPointForValue(mode === 'hour' ? activeParts.hours12 % 12 : selectedDialIndex)

  function syncSegmentsFromValue(nextValue) {
    const nextParts = get12HourParts(nextValue)
    setHourText(padTime(nextParts.hours12))
    setMinuteText(padTime(nextParts.minutes))
    setPeriod(nextParts.period)
  }

  function commitIfComplete(nextHour, nextMinute, nextPeriod) {
    const parsed = validateSegmentTime(nextHour, nextMinute, nextPeriod)

    if (!parsed.valid) {
      return parsed
    }

    setInlineError('')
    onChange(parsed.value24)
    return parsed
  }

  function attemptBlurCommit() {
    const parsed = validateSegmentTime(hourText, minuteText, period)

    if (!parsed.valid) {
      setInlineError(parsed.message)
      const activeElement = document.activeElement
      const isInsideField = activeElement === hourInputRef.current || activeElement === minuteInputRef.current || activeElement === periodButtonRef.current

      if (!isInsideField) {
        syncSegmentsFromValue(value)
      }

      onBlur?.(false)
      return
    }

    setInlineError('')
    onChange(parsed.value24)
    onBlur?.(true)
  }

  function handleHourChange(nextValue) {
    const digits = stripDigits(nextValue, 2)
    setHourText(digits)

    if (digits.length === 2) {
      minuteInputRef.current?.focus()
    }

    if (digits.length === 2 && minuteText.length === 2) {
      commitIfComplete(digits, minuteText, period)
    }
  }

  function handleMinuteChange(nextValue) {
    const digits = stripDigits(nextValue, 2)
    setMinuteText(digits)

    if (digits.length === 2) {
      periodButtonRef.current?.focus()
    }

    if (hourText.length === 2 && digits.length === 2) {
      commitIfComplete(hourText, digits, period)
    }
  }

  function handleSegmentKeyDown(event, segment) {
    if (event.key === 'Backspace') {
      if (segment === 'minute' && !minuteText) {
        event.preventDefault()
        hourInputRef.current?.focus()
      }

      if (segment === 'period' && !minuteText) {
        event.preventDefault()
        minuteInputRef.current?.focus()
      }

      return
    }

    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()

      if (segment === 'hour') {
        const nextValue = padTime(clampHour((hourText ? Number(hourText) : 12) + (event.key === 'ArrowUp' ? 1 : -1)))
        setHourText(nextValue)

        if (minuteText.length === 2) {
          commitIfComplete(nextValue, minuteText, period)
        }

        return
      }

      if (segment === 'minute') {
        const nextValue = padTime(clampMinute((minuteText ? Number(minuteText) : 0) + (event.key === 'ArrowUp' ? 1 : -1)))
        setMinuteText(nextValue)

        if (hourText.length === 2) {
          commitIfComplete(hourText, nextValue, period)
        }

        return
      }

      const nextPeriod = period === 'AM' ? 'PM' : 'AM'
      setPeriod(nextPeriod)

      if (hourText.length === 2 && minuteText.length === 2) {
        commitIfComplete(hourText, minuteText, nextPeriod)
      }
    }

    if ((event.key === 'a' || event.key === 'A' || event.key === 'p' || event.key === 'P') && segment === 'period') {
      event.preventDefault()
      const nextPeriod = event.key.toLowerCase() === 'a' ? 'AM' : 'PM'
      setPeriod(nextPeriod)

      if (hourText.length === 2 && minuteText.length === 2) {
        commitIfComplete(hourText, minuteText, nextPeriod)
      }
    }
  }

  function handleFieldBlur() {
    window.setTimeout(() => {
      const activeElement = document.activeElement
      const isStillInside = activeElement === hourInputRef.current || activeElement === minuteInputRef.current || activeElement === periodButtonRef.current

      if (!isStillInside) {
        attemptBlurCommit()
      }
    }, 0)
  }

  function openPopover() {
    setDraftValue(value)
    setInlineError('')
    setMode('hour')

    if (rootRef.current) {
      setPopoverStyle(getPopoverStyle(rootRef.current.getBoundingClientRect(), POPOVER_ESTIMATED_HEIGHT))
    }

    setIsOpen(true)
  }

  function handlePeriodChange(nextPeriod) {
    setPeriod(nextPeriod)

    if (hourText.length === 2 && minuteText.length === 2) {
      commitIfComplete(hourText, minuteText, nextPeriod)
    }

    const nextDraft = to24HourValue(activeParts.hours12, activeParts.minutes, nextPeriod)
    setDraftValue(nextDraft)
  }

  function handleHourSelect(nextHour) {
    const nextDraft = to24HourValue(nextHour, activeParts.minutes, activeParts.period)
    setDraftValue(nextDraft)
    setMode('minute')
  }

  function handleMinuteSelect(nextMinute) {
    const nextDraft = to24HourValue(activeParts.hours12, nextMinute, activeParts.period)
    setDraftValue(nextDraft)
  }

  function applyDialSelection(clientX, clientY) {
    if (!dialRef.current) {
      return
    }

    const angle = getDialPosition(clientX, clientY, dialRef.current.getBoundingClientRect())

    if (mode === 'hour') {
      handleHourSelect(getHourFromAngle(angle))
      return
    }

    handleMinuteSelect(getMinuteFromAngle(angle))
  }

  function handleDialPointerDown(event) {
    pointerCaptureRef.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
    applyDialSelection(event.clientX, event.clientY)
  }

  function handleDialPointerMove(event) {
    if (!pointerCaptureRef.current) {
      return
    }

    applyDialSelection(event.clientX, event.clientY)
  }

  function handleDialPointerUp(event) {
    pointerCaptureRef.current = false
    event.currentTarget.releasePointerCapture(event.pointerId)
  }

  function handleDialKeyDown(event) {
    if (mode === 'hour') {
      if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
        event.preventDefault()
        handleHourSelect(clampHour(activeParts.hours12 + 1))
      }

      if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
        event.preventDefault()
        handleHourSelect(clampHour(activeParts.hours12 - 1))
      }

      return
    }

    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
      event.preventDefault()
      handleMinuteSelect(clampMinute(activeParts.minutes + 1))
    }

    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
      event.preventDefault()
      handleMinuteSelect(clampMinute(activeParts.minutes - 1))
    }
  }

  function closePopover() {
    setDraftValue(value)
    setIsOpen(false)
  }

  function confirmPopover() {
    syncSegmentsFromValue(draftValue)
    onChange(draftValue)
    setInlineError('')
    setMode('hour')
    setIsOpen(false)
    onBlur?.(true)
  }

  return (
    <div className="field-group time-picker" ref={rootRef}>
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
            <path d="M12 7a5 5 0 1 0 5 5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <path d="M12 4v3m0 5v4m0 0 3 2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </span>

        <div className="segmented-input has-leading-icon has-trailing-button" role="group" aria-labelledby={labelId} aria-describedby={describedBy}>
          <input
            ref={hourInputRef}
            className="segment-input segment-input-short"
            type="text"
            inputMode="numeric"
            maxLength={2}
            placeholder="hh"
            value={hourText}
            onChange={(event) => handleHourChange(event.target.value)}
            onKeyDown={(event) => handleSegmentKeyDown(event, 'hour')}
            aria-label="Departure hour"
            aria-invalid={visibleError ? 'true' : undefined}
          />
          <span className="segment-separator" aria-hidden="true">
            :
          </span>
          <input
            ref={minuteInputRef}
            className="segment-input segment-input-short"
            type="text"
            inputMode="numeric"
            maxLength={2}
            placeholder="mm"
            value={minuteText}
            onChange={(event) => handleMinuteChange(event.target.value)}
            onKeyDown={(event) => handleSegmentKeyDown(event, 'minute')}
            aria-label="Departure minute"
            aria-invalid={visibleError ? 'true' : undefined}
          />
          <button
            ref={periodButtonRef}
            className="segment-period-button"
            type="button"
            aria-pressed={period === 'PM'}
            onClick={() => handlePeriodChange(period === 'AM' ? 'PM' : 'AM')}
            onKeyDown={(event) => handleSegmentKeyDown(event, 'period')}
          >
            {period}
          </button>
        </div>

        <button
          ref={buttonRef}
          className="input-action-button"
          type="button"
          aria-label="Open time picker"
          aria-haspopup="dialog"
          aria-expanded={isOpen}
          onClick={openPopover}
        >
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M12 7v5l3 2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </button>
      </div>

      {visibleError ? (
        <p className="error-text" id={errorId} role="alert">
          Error: {visibleError}
        </p>
      ) : null}

      {isOpen && popoverStyle ? (
        <div ref={dialogRef} className="picker-popover" role="dialog" aria-label="Choose departure time" aria-labelledby={dialogLabelId} tabIndex={-1} style={popoverStyle}>
          <div className="picker-popover-header">
            <div>
              <p className="picker-popover-label" id={dialogLabelId}>
                Choose departure time
              </p>
              <div className="time-picker-display" aria-live="polite">
                <button className={`time-picker-display-part ${mode === 'hour' ? 'is-active' : ''}`} type="button" onClick={() => setMode('hour')}>
                  {padTime(activeParts.hours12)}
                </button>
                <span className="time-picker-display-separator">:</span>
                <button className={`time-picker-display-part ${mode === 'minute' ? 'is-active' : ''}`} type="button" onClick={() => setMode('minute')}>
                  {padTime(activeParts.minutes)}
                </button>
              </div>
            </div>

            <div className="time-picker-period-toggle" role="group" aria-label="Select AM or PM">
              <button type="button" aria-pressed={activeParts.period === 'AM'} onClick={() => handlePeriodChange('AM')}>
                AM
              </button>
              <button type="button" aria-pressed={activeParts.period === 'PM'} onClick={() => handlePeriodChange('PM')}>
                PM
              </button>
            </div>
          </div>

          <div className="time-picker-clock-shell">
            <svg
              ref={dialRef}
              className="time-picker-clock"
              viewBox={`0 0 ${CLOCK_SIZE} ${CLOCK_SIZE}`}
              width={CLOCK_SIZE}
              height={CLOCK_SIZE}
              tabIndex={0}
              role="slider"
              aria-label={mode === 'hour' ? 'Choose hour' : 'Choose minute'}
              aria-valuemin={mode === 'hour' ? 1 : 0}
              aria-valuemax={mode === 'hour' ? 12 : 59}
              aria-valuenow={mode === 'hour' ? activeParts.hours12 : activeParts.minutes}
              onPointerDown={handleDialPointerDown}
              onPointerMove={handleDialPointerMove}
              onPointerUp={handleDialPointerUp}
              onPointerCancel={handleDialPointerUp}
              onKeyDown={handleDialKeyDown}
            >
              <circle cx={CLOCK_CENTER} cy={CLOCK_CENTER} r="78" className="time-picker-clock-face" />
              <line x1={CLOCK_CENTER} y1={CLOCK_CENTER} x2={handPoint.x} y2={handPoint.y} className="time-picker-clock-hand" />
              <circle cx={CLOCK_CENTER} cy={CLOCK_CENTER} r={POINTER_CENTER_OFFSET / 2} className="time-picker-clock-center" />

              {dialNumbers.map((item) => {
                const isSelected = item.value === selectedDialValue

                return (
                  <g
                    key={item.key}
                    className="time-picker-clock-number"
                    transform={`translate(${item.x} ${item.y})`}
                    onClick={() => {
                      if (mode === 'hour') {
                        handleHourSelect(item.value)
                        return
                      }

                      handleMinuteSelect(item.value)
                    }}
                  >
                    {isSelected ? <circle r="14" className="time-picker-clock-number-selected" /> : null}
                    <text className={isSelected ? 'is-selected' : ''} dominantBaseline="middle" textAnchor="middle">
                      {item.label}
                    </text>
                  </g>
                )
              })}
            </svg>
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

export default TimePicker
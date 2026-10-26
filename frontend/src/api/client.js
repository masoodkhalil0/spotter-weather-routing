const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'
const REQUEST_TIMEOUT_MS = 60000

function getApiBaseUrl() {
  return (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '')
}

async function readErrorMessage(response) {
  function collectMessages(value, path = '') {
    if (typeof value === 'string') {
      return path ? [`${path}: ${value}`] : [value]
    }

    if (Array.isArray(value)) {
      return value.flatMap((item) => collectMessages(item, path))
    }

    if (value && typeof value === 'object') {
      return Object.entries(value).flatMap(([key, nestedValue]) => {
        const nextPath = path ? `${path}.${key}` : key
        return collectMessages(nestedValue, nextPath)
      })
    }

    return []
  }

  try {
    const data = await response.json()

    if (data && typeof data.detail === 'string' && data.detail.trim()) {
      return data.detail
    }

    const messages = collectMessages(data)

    if (messages.length > 0) {
      return messages.join(' ')
    }
  } catch {
    // Ignore JSON parsing errors and fall back to a generic message below.
  }

  return `Request failed with status ${response.status}.`
}

function mergeSignals(signalA, signalB) {
  if (!signalA) {
    return signalB
  }

  if (!signalB) {
    return signalA
  }

  const controller = new AbortController()

  function abortFrom(sourceSignal) {
    if (sourceSignal.aborted) {
      controller.abort(sourceSignal.reason)
      return
    }

    sourceSignal.addEventListener(
      'abort',
      () => {
        controller.abort(sourceSignal.reason)
      },
      { once: true },
    )
  }

  abortFrom(signalA)
  abortFrom(signalB)

  return controller.signal
}

async function request(path, options = {}) {
  const timeoutController = new AbortController()
  const timeoutId = window.setTimeout(() => {
    timeoutController.abort(new Error('The request timed out. Please try again.'))
  }, REQUEST_TIMEOUT_MS)

  const signal = mergeSignals(options.signal, timeoutController.signal)

  try {
    const response = await fetch(`${getApiBaseUrl()}${path}`, {
      method: options.method || 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal,
    })

    if (!response.ok) {
      throw new Error(await readErrorMessage(response))
    }

    return response.json()
  } catch (error) {
    if (error.name === 'AbortError') {
      throw error
    }

    if (error instanceof TypeError) {
      throw new Error('Unable to reach the server. Please make sure the backend is running.')
    }

    throw error
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export function health(options = {}) {
  return request('/api/health/', {
    signal: options.signal,
  })
}

export function geocode(q, options = {}) {
  const params = new URLSearchParams({ q })

  return request(`/api/geocode/?${params.toString()}`, {
    signal: options.signal,
  })
}

export function analyze(payload, options = {}) {
  return request('/api/analyze/', {
    method: 'POST',
    body: payload,
    signal: options.signal,
  })
}

export function heatmap(payload, options = {}) {
  return request('/api/heatmap/', {
    method: 'POST',
    body: payload,
    signal: options.signal,
  })
}
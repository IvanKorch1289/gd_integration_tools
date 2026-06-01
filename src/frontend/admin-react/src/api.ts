/**
 * Centralized API client for admin-react.
 *
 * Auth: VITE_ADMIN_API_KEY env var (set at build time).
 * All requests include X-API-Key header validated by APIKeyMiddleware.
 *
 * Backend mount: /api/v1/admin/*
 * (Vite proxy /api → http://localhost:8000)
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const API_KEY = (import.meta as any).env?.VITE_ADMIN_API_KEY as string | undefined
const API_BASE = '/api/v1'

export interface ApiError {
  detail?: string
  error?: string
  message?: string
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  if (!API_KEY) {
    throw new Error('AUTH_NOT_CONFIGURED')
  }

  const url = `${API_BASE}${path}`
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
      ...(options.headers || {}),
    },
  })

  if (!response.ok) {
    let message: string
    try {
      const body = (await response.json()) as ApiError
      message = body.detail || body.error || body.message || String(response.status)
    } catch {
      message = String(response.status)
    }
    throw new Error(`${response.status} ${message}`)
  }

  // Handle empty responses
  const text = await response.text()
  if (!text) return {} as T
  return JSON.parse(text) as T
}

export const api = {
  /** GET request */
  get<T>(path: string): Promise<T> {
    return request<T>(path)
  },

  /** POST request */
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    })
  },

  /** PUT request */
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    })
  },

  /** DELETE request */
  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' })
  },

  /** True when VITE_ADMIN_API_KEY was set at build time. */
  isConfigured(): boolean {
    return Boolean(API_KEY)
  },
}

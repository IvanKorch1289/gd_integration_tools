import { useEffect, useState } from 'react'

interface Route {
  id: string
  name: string
  path: string
  method: string
  status: 'active' | 'inactive' | 'error'
  lastAccessed: string
}

/**
 * Route Management UI.
 *
 * NOTE: Backend endpoint for route listing does not exist yet.
 * When the endpoint is added (e.g. GET /admin/routes from dsl_routes store),
 * replace the placeholder below with:
 *   api.get<Route[]>('/admin/routes').then(...).catch(...)
 */
export function RouteList() {
  const [routes] = useState<Route[]>([])
  const [loading, setLoading] = useState(true)
  const [error] = useState<string | null>(null)

  useEffect(() => {
    setLoading(false)
  }, [])

  if (loading) return <p>Loading routes…</p>
  if (error) return <p style={{ color: 'orange' }}>{error}</p>

  return (
    <section>
      <h2 style={{ marginBottom: '16px' }}>Route Management</h2>
      <p style={{ color: '#888' }}>
        Route listing endpoint not yet implemented.
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Path</th>
              <th>Method</th>
              <th>Status</th>
              <th>Last Accessed</th>
            </tr>
          </thead>
          <tbody>
            {routes.map(r => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td><code>{r.path}</code></td>
                <td>{r.method}</td>
                <td style={{
                  color: r.status === 'active' ? '#4ade80'
                    : r.status === 'inactive' ? '#facc15' : '#f87171'
                }}>{r.status}</td>
                <td>{r.lastAccessed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

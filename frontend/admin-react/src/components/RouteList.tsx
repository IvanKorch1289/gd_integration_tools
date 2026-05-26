interface Route {
  id: string
  name: string
  path: string
  method: string
  status: 'active' | 'inactive' | 'error'
  lastAccessed: string
}

const mockRoutes: Route[] = [
  { id: '1', name: 'Get Users', path: '/api/users', method: 'GET', status: 'active', lastAccessed: '2026-05-26T10:30:00Z' },
  { id: '2', name: 'Create User', path: '/api/users', method: 'POST', status: 'active', lastAccessed: '2026-05-26T10:25:00Z' },
  { id: '3', name: 'Get Routes', path: '/api/routes', method: 'GET', status: 'active', lastAccessed: '2026-05-26T09:15:00Z' },
  { id: '4', name: 'Health Check', path: '/api/health', method: 'GET', status: 'active', lastAccessed: '2026-05-26T10:45:00Z' },
  { id: '5', name: 'Deprecated Endpoint', path: '/api/v1/legacy', method: 'DELETE', status: 'inactive', lastAccessed: '2026-05-20T08:00:00Z' },
  { id: '6', name: 'Error Route', path: '/api/error', method: 'POST', status: 'error', lastAccessed: '2026-05-26T01:00:00Z' },
]

function getStatusColor(status: Route['status']): string {
  switch (status) {
    case 'active': return '#4ade80'
    case 'inactive': return '#facc15'
    case 'error': return '#f87171'
  }
}

export function RouteList() {
  // Auth stub - in production this would use actual auth
  const isAuthenticated = true

  if (!isAuthenticated) {
    return (
      <div style={{ padding: '20px', textAlign: 'center' }}>
        <p>Authentication required (stubbed - no auth implemented)</p>
      </div>
    )
  }

  return (
    <section>
      <h2 style={{ marginBottom: '16px' }}>Route Management</h2>
      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Path</th>
              <th>Method</th>
              <th>Status</th>
              <th>Last Accessed</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {mockRoutes.map((route) => (
              <tr key={route.id}>
                <td>{route.name}</td>
                <td><code>{route.path}</code></td>
                <td><span style={{
                  padding: '2px 8px',
                  borderRadius: '4px',
                  backgroundColor: '#333',
                  fontFamily: 'monospace'
                }}>{route.method}</span></td>
                <td>
                  <span style={{
                    display: 'inline-block',
                    width: '10px',
                    height: '10px',
                    borderRadius: '50%',
                    backgroundColor: getStatusColor(route.status),
                    marginRight: '8px'
                  }}></span>
                  {route.status}
                </td>
                <td>{new Date(route.lastAccessed).toLocaleString()}</td>
                <td>
                  <button onClick={() => alert(`Edit ${route.name}`)}>Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

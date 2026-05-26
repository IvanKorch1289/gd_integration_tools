import { useEffect, useState } from 'react'

interface Session {
  id: string
  agent_id: string
  created_at: string
  last_active: string
  tenant?: string
}

export function SessionList() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/admin/sessions')
      .then(r => r.json())
      .then(data => { setSessions(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  if (loading) return <p>Loading sessions…</p>
  if (error && sessions.length === 0) return <p style={{ color: 'red' }}>Error: {error}</p>

  return (
    <div>
      <h2>Active Sessions</h2>
      {error && <p style={{ color: 'orange' }}>Last error: {error}</p>}
      {sessions.length === 0 ? (
        <p style={{ color: '#888' }}>No active sessions.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #333' }}>
              <th>ID</th>
              <th>Agent</th>
              <th>Tenant</th>
              <th>Created</th>
              <th>Last Active</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map(s => (
              <tr key={s.id} style={{ borderBottom: '1px solid #222' }}>
                <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '0.85em' }}>{s.id}</td>
                <td style={{ padding: '6px' }}>{s.agent_id}</td>
                <td style={{ padding: '6px' }}>{s.tenant || '—'}</td>
                <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '0.85em' }}>
                  {new Date(s.created_at).toLocaleString()}
                </td>
                <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '0.85em' }}>
                  {new Date(s.last_active).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

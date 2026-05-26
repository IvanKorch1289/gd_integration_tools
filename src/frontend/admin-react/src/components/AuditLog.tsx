import { useEffect, useState } from 'react'

interface AuditEntry {
  event: string
  correlation_id: string
  timestamp: string
  actor: string
  action: string
  resource: string
  outcome: string
  details?: Record<string, unknown>
}

export function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/admin/audit')
      .then(r => r.json())
      .then(data => { setEntries(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  if (loading) return <p>Loading audit log…</p>
  if (error && entries.length === 0) return <p style={{ color: 'red' }}>Error: {error}</p>

  return (
    <div>
      <h2>Audit Log</h2>
      {error && <p style={{ color: 'orange' }}>Last error: {error}</p>}
      {entries.length === 0 ? (
        <p style={{ color: '#888' }}>No audit entries yet.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #333' }}>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Resource</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={i} style={{ borderBottom: '1px solid #222' }}>
                <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '0.85em' }}>
                  {e.timestamp ? new Date(e.timestamp).toLocaleString() : '—'}
                </td>
                <td style={{ padding: '6px' }}>{e.actor}</td>
                <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '0.85em' }}>{e.action}</td>
                <td style={{ padding: '6px', fontFamily: 'monospace', fontSize: '0.85em' }}>{e.resource}</td>
                <td style={{
                  padding: '6px',
                  color: e.outcome === 'allowed' ? '#4caf50' : e.outcome === 'denied' ? '#f44336' : '#ff9800'
                }}>
                  {e.outcome}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

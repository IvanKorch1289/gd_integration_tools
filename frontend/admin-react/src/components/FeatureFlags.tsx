import { useEffect, useState } from 'react'

interface FeatureFlag {
  Name: string
  value: boolean | string | number
}

interface ToggleResult {
  flag?: string
  old?: boolean | string | number
  new?: boolean | string | number
  error?: string
}

export function FeatureFlags() {
  const [flags, setFlags] = useState<FeatureFlag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toggling, setToggling] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/admin/flags')
      .then(r => r.json())
      .then(data => { setFlags(data); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  async function handleToggle(flag: FeatureFlag) {
    if (typeof flag.value !== 'boolean') return
    setToggling(flag.Name)
    try {
      const res = await fetch(`/api/admin/flags/${flag.Name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !flag.value }),
      })
      const data: ToggleResult = await res.json()
      if (data.error) {
        setError(data.error)
      } else {
        setFlags(prev =>
          prev.map(f => f.Name === flag.Name ? { ...f, value: data.new! } : f)
        )
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setToggling(null)
    }
  }

  if (loading) return <p>Loading flags…</p>
  if (error && flags.length === 0) return <p style={{ color: 'red' }}>Error: {error}</p>

  return (
    <div>
      <h2>Feature Flags</h2>
      {error && <p style={{ color: 'orange' }}>Last error: {error}</p>}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', borderBottom: '1px solid #333' }}>
            <th>Flag</th>
            <th>Value</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {flags.map(f => (
            <tr key={f.Name} style={{ borderBottom: '1px solid #222' }}>
              <td style={{ padding: '8px' }}>{f.Name}</td>
              <td style={{ padding: '8px', color: typeof f.value === 'boolean' ? (f.value ? '#4caf50' : '#f44336') : '#888' }}>
                {String(f.value)}
              </td>
              <td style={{ padding: '8px' }}>
                {typeof f.value === 'boolean' ? (
                  <button
                    onClick={() => handleToggle(f)}
                    disabled={toggling === f.Name}
                    style={{
                      padding: '4px 12px',
                      backgroundColor: f.value ? '#f44336' : '#4caf50',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer',
                    }}
                  >
                    {toggling === f.Name ? '…' : (f.value ? 'Disable' : 'Enable')}
                  </button>
                ) : (
                  <span style={{ color: '#666', fontSize: '0.9em' }}>read-only</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

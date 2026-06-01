import { useEffect, useState } from 'react'
import { api } from '../api'

interface PluginInfo {
  name: string
  version: string
  enabled: boolean
  capabilities?: string[]
  description?: string
}

export function PluginInventory() {
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<PluginInfo[]>('/admin/plugins')
      .then(data => { setPlugins(Array.isArray(data) ? data : []); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [])

  if (loading) return <p>Loading plugin inventory…</p>
  if (error && plugins.length === 0) return <p style={{ color: 'red' }}>Error: {error}</p>

  return (
    <div>
      <h2>Plugin Inventory</h2>
      {error && <p style={{ color: 'orange' }}>Last error: {error}</p>}
      {plugins.length === 0 ? (
        <p style={{ color: '#888' }}>No plugins registered.</p>
      ) : (
        <div style={{ display: 'grid', gap: '12px' }}>
          {plugins.map(p => (
            <div key={p.name} style={{
              border: '1px solid #333',
              borderRadius: '8px',
              padding: '12px 16px',
              backgroundColor: p.enabled ? '#1a2a1a' : '#1a1a1a',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong>{p.name}</strong>
                  <span style={{ color: '#888', marginLeft: '8px' }}>v{p.version}</span>
                </div>
                <span style={{
                  padding: '2px 8px',
                  borderRadius: '12px',
                  fontSize: '0.8em',
                  backgroundColor: p.enabled ? '#2e7d32' : '#555',
                  color: '#fff',
                }}>
                  {p.enabled ? 'enabled' : 'disabled'}
                </span>
              </div>
              {p.description && <p style={{ color: '#aaa', margin: '4px 0 0' }}>{p.description}</p>}
              {p.capabilities && p.capabilities.length > 0 && (
                <div style={{ marginTop: '8px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                  {p.capabilities.map(c => (
                    <span key={c} style={{
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontSize: '0.75em',
                      backgroundColor: '#333',
                      color: '#aaa',
                    }}>{c}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

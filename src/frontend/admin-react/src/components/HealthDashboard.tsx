import { useEffect, useState } from 'react'
import { api } from '../api'

interface HealthCard {
  id: string
  name: string
  status: 'healthy' | 'degraded' | 'down'
  latency: number
  uptime: string
}

function getHealthColor(status: HealthCard['status']): string {
  switch (status) {
    case 'healthy': return '#4ade80'
    case 'degraded': return '#facc15'
    case 'down': return '#f87171'
  }
}

export function HealthDashboard() {
  const [cards, setCards] = useState<HealthCard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.get<{ components: Record<string, { status: string; latency_ms?: number }> }>('/health')
      .then(data => {
        const parsed: HealthCard[] = Object.entries(data.components || {}).map(
          ([name, comp], idx) => ({
            id: String(idx),
            name,
            status: (comp.status === 'ok' || comp.status === 'healthy'
              ? 'healthy'
              : comp.status === 'degraded'
              ? 'degraded'
              : 'down') as HealthCard['status'],
            latency: comp.latency_ms ?? 0,
            uptime: '—',
          })
        )
        setCards(parsed)
        setLoading(false)
      })
      .catch(e => {
        setError(String(e))
        setLoading(false)
      })
  }, [])

  if (loading) return <p>Loading health status…</p>
  if (error && cards.length === 0) return <p style={{ color: 'red' }}>Error: {error}</p>

  return (
    <section>
      <h2 style={{ marginBottom: '16px' }}>Health Status</h2>
      {error && <p style={{ color: 'orange' }}>Last error: {error}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '16px' }}>
        {cards.length === 0 && <p style={{ color: '#888' }}>No components reported.</p>}
        {cards.map((card) => (
          <div
            key={card.id}
            style={{
              backgroundColor: '#1a1a1a',
              borderRadius: '8px',
              padding: '16px',
              border: `2px solid ${getHealthColor(card.status)}`,
            }}
          >
            <strong>{card.name}</strong>
            <p style={{ color: getHealthColor(card.status), margin: '4px 0' }}>
              {card.status.toUpperCase()}
            </p>
            {card.latency > 0 && <p style={{ color: '#888', fontSize: '0.85em' }}>{card.latency}ms</p>}
          </div>
        ))}
      </div>
    </section>
  )
}

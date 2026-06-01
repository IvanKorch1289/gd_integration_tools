interface HealthCard {
  id: string
  name: string
  status: 'healthy' | 'degraded' | 'down'
  latency: number
  uptime: string
}

const mockHealthCards: HealthCard[] = [
  { id: '1', name: 'API Gateway', status: 'healthy', latency: 45, uptime: '99.9%' },
  { id: '2', name: 'Database', status: 'healthy', latency: 12, uptime: '99.99%' },
  { id: '3', name: 'Cache', status: 'healthy', latency: 3, uptime: '99.5%' },
  { id: '4', name: 'Queue Worker', status: 'degraded', latency: 230, uptime: '98.2%' },
  { id: '5', name: 'External API', status: 'down', latency: 0, uptime: '0%' },
]

function getHealthColor(status: HealthCard['status']): string {
  switch (status) {
    case 'healthy': return '#4ade80'
    case 'degraded': return '#facc15'
    case 'down': return '#f87171'
  }
}

export function HealthDashboard() {
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
      <h2 style={{ marginBottom: '16px' }}>Health Status</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '16px' }}>
        {mockHealthCards.map((card) => (
          <div
            key={card.id}
            style={{
              backgroundColor: '#1a1a1a',
              borderRadius: '8px',
              padding: '16px',
              border: `2px solid ${getHealthColor(card.status)}`,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
              <span style={{
                width: '12px',
                height: '12px',
                borderRadius: '50%',
                backgroundColor: getHealthColor(card.status),
              }}></span>
              <h3 style={{ fontSize: '1em' }}>{card.name}</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.9em' }}>
              <div>
                <span style={{ color: '#888' }}>Status:</span> {card.status}
              </div>
              <div>
                <span style={{ color: '#888' }}>Latency:</span> {card.latency}ms
              </div>
              <div>
                <span style={{ color: '#888' }}>Uptime:</span> {card.uptime}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

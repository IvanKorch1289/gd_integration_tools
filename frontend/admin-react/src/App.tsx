import { useState } from 'react'
import { RouteList } from './components/RouteList'
import { HealthDashboard } from './components/HealthDashboard'

type NavItem = 'routes' | 'health'

function App() {
  const [activeNav, setActiveNav] = useState<NavItem>('routes')

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar Navigation */}
      <nav
        style={{
          width: '220px',
          backgroundColor: '#1a1a1a',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          borderRight: '1px solid #333',
        }}
      >
        <h2 style={{ marginBottom: '16px', fontSize: '1.2em' }}>Admin</h2>
        <button
          onClick={() => setActiveNav('routes')}
          style={{
            backgroundColor: activeNav === 'routes' ? '#646cff' : 'transparent',
            textAlign: 'left',
          }}
        >
          Route Management
        </button>
        <button
          onClick={() => setActiveNav('health')}
          style={{
            backgroundColor: activeNav === 'health' ? '#646cff' : 'transparent',
            textAlign: 'left',
          }}
        >
          Health Status
        </button>
      </nav>

      {/* Main Content */}
      <main style={{ flex: 1, padding: '24px' }}>
        <header style={{ marginBottom: '24px' }}>
          <h1>Admin Dashboard</h1>
          <p style={{ color: '#888' }}>React MVP - Feature Flag: admin_react_mvp</p>
        </header>

        {activeNav === 'routes' && <RouteList />}
        {activeNav === 'health' && <HealthDashboard />}
      </main>
    </div>
  )
}

export default App

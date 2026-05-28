import { useState } from 'react'
import { RouteList } from './components/RouteList'
import { HealthDashboard } from './components/HealthDashboard'
import { FeatureFlags } from './components/FeatureFlags'
import { AuditLog } from './components/AuditLog'
import { SessionList } from './components/SessionList'
import { PluginInventory } from './components/PluginInventory'
import { api } from './api'

type NavItem = 'routes' | 'health' | 'flags' | 'audit' | 'sessions' | 'plugins'

function LoginScreen() {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      backgroundColor: '#0a0a0a',
      color: '#fff',
    }}>
      <div style={{
        border: '1px solid #333',
        borderRadius: '8px',
        padding: '32px',
        maxWidth: '400px',
        textAlign: 'center',
        backgroundColor: '#1a1a1a',
      }}>
        <h2 style={{ marginBottom: '8px' }}>Admin Dashboard</h2>
        <p style={{ color: '#888', marginBottom: '24px' }}>
          VITE_ADMIN_API_KEY not configured at build time.
        </p>
        <p style={{ color: '#666', fontSize: '0.9em' }}>
          Build with:<br />
          <code style={{ color: '#aaa' }}>
            VITE_ADMIN_API_KEY=your_key npm run build
          </code>
        </p>
      </div>
    </div>
  )
}

function App() {
  const [activeNav, setActiveNav] = useState<NavItem>('routes')

  // Auth gate: require API key at build time
  if (!api.isConfigured()) {
    return <LoginScreen />
  }

  const navItems: { id: NavItem; label: string }[] = [
    { id: 'routes', label: 'Route Management' },
    { id: 'health', label: 'Health Status' },
    { id: 'flags', label: 'Feature Flags' },
    { id: 'audit', label: 'Audit Log' },
    { id: 'sessions', label: 'Active Sessions' },
    { id: 'plugins', label: 'Plugin Inventory' },
  ]

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
        {navItems.map(item => (
          <button
            key={item.id}
            onClick={() => setActiveNav(item.id)}
            style={{
              backgroundColor: activeNav === item.id ? '#646cff' : 'transparent',
              textAlign: 'left',
              padding: '8px',
              color: '#fff',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {/* Main Content */}
      <main style={{ flex: 1, padding: '24px' }}>
        <header style={{ marginBottom: '24px' }}>
          <h1>Admin Dashboard</h1>
          <p style={{ color: '#888' }}>
            GD Integration Tools — Admin Panel
          </p>
        </header>

        {activeNav === 'routes' && <RouteList />}
        {activeNav === 'health' && <HealthDashboard />}
        {activeNav === 'flags' && <FeatureFlags />}
        {activeNav === 'audit' && <AuditLog />}
        {activeNav === 'sessions' && <SessionList />}
        {activeNav === 'plugins' && <PluginInventory />}
      </main>
    </div>
  )
}

export default App

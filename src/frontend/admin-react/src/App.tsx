import { useState } from 'react'
import { RouteList } from './components/RouteList'
import { HealthDashboard } from './components/HealthDashboard'
import { FeatureFlags } from './components/FeatureFlags'
import { AuditLog } from './components/AuditLog'
import { SessionList } from './components/SessionList'
import { PluginInventory } from './components/PluginInventory'

type NavItem = 'routes' | 'health' | 'flags' | 'audit' | 'sessions' | 'plugins'

function App() {
  const [activeNav, setActiveNav] = useState<NavItem>('routes')

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
            GD Integration Tools — Feature Flags: admin_react_mvp, langmem_consolidation_impl
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

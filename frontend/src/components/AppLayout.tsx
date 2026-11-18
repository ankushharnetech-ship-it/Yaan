import { Menu } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { navFor } from '../routes/nav'
import { ROLE_LABELS, type AuthUser } from '../types'

export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden>
        <svg width="20" height="20" viewBox="0 0 32 32"><path d="M9 9l7 8 7-8M16 17v7" stroke="#fff" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
      YAAN
    </div>
  )
}

export function AppLayout({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Primary">
        <Brand />
        <nav className="nav">
          {navFor(user.role).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setOpen(false)}>
              <Icon size={18} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div style={{ color: '#fff', fontWeight: 600 }}>Employee transport</div>
          <div>Plan, assign and track every trip.</div>
        </div>
      </aside>
      <div className={`scrim ${open ? 'open' : ''}`} onClick={() => setOpen(false)} />
      <div className="main">
        <header className="topbar">
          <button className="btn menu-btn" aria-label="Open menu" onClick={() => setOpen(true)}><Menu size={18} /></button>
          <div className="spacer" />
          <div className="userchip" title={`${user.first_name} ${user.last_name} · ${ROLE_LABELS[user.role]}`}>
            <span className="avatar" aria-hidden>{(user.first_name[0] ?? '') + (user.last_name[0] ?? '')}</span>
            <span className="who"><strong>{user.first_name} {user.last_name}</strong><small>{ROLE_LABELS[user.role]}</small></span>
          </div>
          <button className="btn" onClick={onLogout}>Sign out</button>
        </header>
        <main id="main" tabIndex={-1} className="content"><Outlet /></main>
      </div>
    </div>
  )
}

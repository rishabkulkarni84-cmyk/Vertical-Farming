import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Bell, Box, Boxes, Calculator, ChevronDown, CircleHelp, FileText, FolderKanban, GitCompareArrows, Grid3x3, Home, Lightbulb,
  LogOut, Menu, Wallet, Ruler, Settings, Sprout, Activity, X, Image as ImageIcon,
} from 'lucide-react'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate } from 'react-router-dom'
import { get, post } from '../lib/api'
import { useMe } from '../lib/hooks'
import type { Alert, Farm } from '../lib/types'
import { Spinner } from './ui'

const FARM_NAV: { group: string; hint: string; items: { to: string; label: string; icon: ReactNode }[] }[] = [
  { group: 'Plan', hint: 'Room, space and grid', items: [
    { to: 'setup', label: 'Room setup', icon: <Ruler className="size-4" /> },
    { to: 'space', label: 'Photo & obstacles', icon: <ImageIcon className="size-4" /> },
    { to: 'grid', label: 'Planning grid', icon: <Grid3x3 className="size-4" /> },
  ] },
  { group: 'Build', hint: 'Racks and what fits', items: [
    { to: 'plan', label: 'Budget plan', icon: <Wallet className="size-4" /> },
    { to: 'layout', label: 'Layout (manual)', icon: <Boxes className="size-4" /> },
    { to: 'view', label: '2D / 3D view', icon: <Box className="size-4" /> },
    { to: 'crops', label: 'Crops', icon: <Sprout className="size-4" /> },
    { to: 'costs', label: 'Costs & materials', icon: <Calculator className="size-4" /> },
  ] },
  { group: 'Monitor', hint: 'Simulated sensors', items: [
    { to: 'monitor', label: 'Monitoring', icon: <Activity className="size-4" /> },
    { to: 'insights', label: 'Alerts & insights', icon: <Lightbulb className="size-4" /> },
  ] },
  { group: 'Optimize', hint: 'Compare and export', items: [
    { to: 'scenarios', label: 'What-if scenarios', icon: <GitCompareArrows className="size-4" /> },
    { to: 'report', label: 'Report & export', icon: <FileText className="size-4" /> },
  ] },
]

function NavItem({ to, icon, children, end }: { to: string; icon: ReactNode; children: ReactNode; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => clsx('flex items-center gap-2.5 rounded-md px-2.5 h-8 text-[13.5px] transition-colors',
      isActive ? 'bg-white/12 text-white font-medium' : 'text-sage-200/80 hover:text-white hover:bg-white/6')}>
      <span aria-hidden className="opacity-90">{icon}</span>{children}
    </NavLink>
  )
}

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2.5 px-2 text-white">
      <svg viewBox="0 0 32 32" className="size-7" aria-hidden><rect width="32" height="32" rx="7" fill="#DCE5DD" /><g stroke="#1E4A37" strokeWidth="2.2" strokeLinecap="round"><path d="M8 24h16M8 18h16M8 12h16" /></g><path d="M16 12c0-4 3-6 6-6 0 4-3 6-6 6zM16 12c0-3-2-5-5-5 0 3 2 5 5 5z" fill="#34735A" /></svg>
      <span className="font-display text-[19px] font-semibold tracking-tight">Verdant</span>
    </Link>
  )
}

function FarmSwitcher({ farmId }: { farmId: number }) {
  const { data: farms } = useQuery({ queryKey: ['farms', 'ACTIVE'], queryFn: () => get<Farm[]>('/farms?status=ACTIVE') })
  const nav = useNavigate()
  const loc = useLocation()
  const sub = loc.pathname.split('/')[3] ?? 'setup'
  return (
    <div className="px-2">
      <label htmlFor="farm-switch" className="sr-only">Current farm</label>
      <div className="relative">
        <select id="farm-switch" value={farmId} onChange={(e) => nav(`/farms/${e.target.value}/${sub}`)}
          className="w-full appearance-none rounded-md bg-forest-950/60 border border-white/10 text-white text-[13.5px] font-medium h-9 pl-3 pr-8 focus:outline-none focus:border-sage-500">
          {farms?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
        <ChevronDown className="size-4 text-sage-300 absolute right-2.5 top-2.5 pointer-events-none" aria-hidden />
      </div>
    </div>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const m = useMatch('/farms/:farmId/*')
  const farmId = m && m.params.farmId !== 'new' ? Number(m.params.farmId) : null
  return (
    <nav aria-label="Main" className="flex h-full flex-col bg-forest-800 py-4 gap-5 overflow-y-auto" onClick={(e) => (e.target as HTMLElement).closest('a') && onNavigate?.()}>
      <Brand />
      <div className="px-2 space-y-0.5">
        <NavItem to="/" end icon={<Home className="size-4" />}>Overview</NavItem>
        <NavItem to="/farms" end icon={<FolderKanban className="size-4" />}>Farms & designs</NavItem>
      </div>
      {farmId && (
        <div className="space-y-4">
          <FarmSwitcher farmId={farmId} />
          {FARM_NAV.map((g, gi) => (
            <div key={g.group} className="px-2">
              <div className="px-2.5 pb-1 flex items-baseline gap-2">
                <span className="text-[11px] font-semibold text-sage-300 tabular-nums">{gi + 1}</span>
                <span className="text-[12.5px] font-semibold text-sage-200">{g.group}</span>
                <span className="text-[11.5px] text-sage-500 truncate">{g.hint}</span>
              </div>
              <div className="space-y-0.5">{g.items.map((it) => <NavItem key={it.to} to={`/farms/${farmId}/${it.to}`} icon={it.icon}>{it.label}</NavItem>)}</div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-auto px-2 space-y-0.5 pt-4 border-t border-white/10 mx-2">
        <NavItem to="/settings" icon={<Settings className="size-4" />}>Settings</NavItem>
        <NavItem to="/help" icon={<CircleHelp className="size-4" />}>Help & data status</NavItem>
      </div>
    </nav>
  )
}

function Notifications() {
  const m = useMatch('/farms/:farmId/*')
  const farmId = m && m.params.farmId !== 'new' ? Number(m.params.farmId) : null
  const [open, setOpen] = useState(false)
  const { data: dash } = useQuery({ queryKey: ['alert-summary'], queryFn: () => get<{ open: number; critical: number }>('/alerts/summary'), refetchInterval: 15000 })
  const { data: alerts } = useQuery({ queryKey: ['alerts', farmId, 'OPEN'], queryFn: () => get<Alert[]>(`/farms/${farmId}/alerts?status=OPEN&limit=6`), enabled: !!farmId && open })
  const n = dash?.open ?? 0
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`Notifications, ${n} open alerts`} className="relative p-2 rounded-md hover:bg-sage-100">
        <Bell className="size-[18px] text-ink-soft" />
        {n > 0 && <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-crit text-white text-[10.5px] font-semibold grid place-items-center">{n > 99 ? '99+' : n}</span>}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 rounded-lg border border-line bg-surface shadow-xl z-40 p-3" onMouseLeave={() => setOpen(false)}>
          <div className="text-[13px] font-semibold mb-2">{n ? `${n} open alert${n > 1 ? 's' : ''} across your farms` : 'No open alerts'}</div>
          {farmId ? (
            <ul className="space-y-2">
              {alerts?.map((a) => <li key={a.id} className="text-[12.5px] text-ink-soft border-l-2 pl-2" style={{ borderColor: a.severity === 'CRITICAL' ? 'var(--color-crit)' : 'var(--color-warn)' }}>{a.message}</li>)}
            </ul>
          ) : <p className="text-[12.5px] text-muted">Open a farm to see its alerts.</p>}
          {farmId && <Link onClick={() => setOpen(false)} to={`/farms/${farmId}/insights`} className="mt-3 inline-block text-[13px] font-medium text-forest-700 hover:underline">Open alerts & insights</Link>}
        </div>
      )}
    </div>
  )
}

function UserMenu() {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const nav = useNavigate()
  const signOut = async () => {
    await post('/auth/logout')
    qc.clear()
    nav('/login')
  }
  const initials = (me?.name ?? '?').split(' ').map((s) => s[0]).slice(0, 2).join('').toUpperCase()
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label="Account menu" className="flex items-center gap-2 rounded-md pl-1 pr-2 h-9 hover:bg-sage-100">
        <span className="size-7 rounded-full bg-forest-800 text-white text-[11.5px] font-semibold grid place-items-center">{initials}</span>
        <span className="hidden sm:block text-[13.5px] font-medium max-w-32 truncate">{me?.name}</span>
        <ChevronDown className="size-3.5 text-muted" aria-hidden />
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-56 rounded-lg border border-line bg-surface shadow-xl z-40 py-1" onMouseLeave={() => setOpen(false)}>
          <div className="px-3 py-2 text-[12.5px] text-muted truncate border-b border-line">{me?.email}</div>
          <Link onClick={() => setOpen(false)} to="/settings" className="flex items-center gap-2 px-3 py-2 text-[13.5px] hover:bg-sage-50"><Settings className="size-4" />Settings</Link>
          <button onClick={signOut} className="w-full flex items-center gap-2 px-3 py-2 text-[13.5px] hover:bg-sage-50 text-left"><LogOut className="size-4" />Sign out</button>
        </div>
      )}
    </div>
  )
}

export default function AppShell() {
  const [mobile, setMobile] = useState(false)
  const loc = useLocation()
  useEffect(() => setMobile(false), [loc.pathname])
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[248px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 bg-surface px-3 py-2 rounded">Skip to content</a>
      <aside className="hidden lg:block sticky top-0 h-dvh"><Sidebar /></aside>
      {mobile && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="w-72 h-full shadow-2xl"><Sidebar onNavigate={() => setMobile(false)} /></div>
          <button className="flex-1 bg-ink/40" aria-label="Close menu" onClick={() => setMobile(false)}><X className="size-5 text-white m-4" /></button>
        </div>
      )}
      <div className="min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 h-14 flex items-center gap-3 px-4 sm:px-8 bg-paper/90 backdrop-blur border-b border-line">
          <button className="lg:hidden p-2 -ml-2 rounded hover:bg-sage-100" onClick={() => setMobile(true)} aria-label="Open menu"><Menu className="size-5" /></button>
          <div className="lg:hidden font-display font-semibold text-forest-800">Verdant</div>
          <div className="ml-auto flex items-center gap-1"><Notifications /><UserMenu /></div>
        </header>
        <main id="main" className="flex-1 px-4 sm:px-8 py-7 max-w-[1400px] w-full"><Suspense fallback={<Spinner label="Loading" />}><Outlet /></Suspense></main>
      </div>
    </div>
  )
}

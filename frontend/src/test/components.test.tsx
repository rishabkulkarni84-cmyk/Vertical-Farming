import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PlanView from '../components/PlanView'
import { ConfirmDialog, Empty, ErrorState, SourceBadge } from '../components/ui'
import { ApiError } from '../lib/api'
import AuthPage from '../pages/AuthPage'
import InsightsPage from '../pages/InsightsPage'

function wrap(ui: ReactNode, path = '/', route = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={ui} /></Routes></MemoryRouter></QueryClientProvider>)
}

function mockFetch(routes: Record<string, unknown>) {
  const calls: { url: string; method: string; body?: string }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? 'GET', body: init?.body as string })
    const key = Object.keys(routes).find((k) => url.startsWith(k.split(' ').pop()!) && (!k.includes(' ') || k.startsWith(init?.method ?? 'GET')))
    const data = key ? routes[key] : { error: { code: 'NOT_FOUND', message: 'nope' } }
    return new Response(JSON.stringify(typeof data === 'function' ? (data as any)(init) : data), { status: key ? 200 : 404 })
  }))
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('ui primitives', () => {
  it('labels simulated data with a non-color explanation', () => {
    render(<SourceBadge source="SIMULATED" />)
    expect(screen.getByText('Simulated')).toHaveAttribute('title', expect.stringMatching(/not a physical sensor/))
  })
  it('renders empty and error states with actions', async () => {
    const retry = vi.fn()
    render(<><Empty title="Nothing yet">Add one</Empty><ErrorState error={new ApiError(500, 'X', 'Boom')} retry={retry} /></>)
    expect(screen.getByText('Nothing yet')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Boom')
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(retry).toHaveBeenCalled()
  })
  it('confirm dialog requires an explicit confirmation', async () => {
    const onConfirm = vi.fn(), onClose = vi.fn()
    render(<ConfirmDialog open title="Delete farm?" body="Gone forever" confirmLabel="Delete" danger onConfirm={onConfirm} onClose={onClose} />)
    expect(screen.getByRole('dialog', { name: 'Delete farm?' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalled()
  })
})

describe('PlanView', () => {
  const racks = [{ label: 'R1', x: 0, y: 0, w: 1.2, d: 0.45, rotation: 0 as const, access_side: 'S' }, { label: 'R2', x: 1.3, y: 0, w: 1.2, d: 0.45, rotation: 0 as const, access_side: 'S' }]
  it('draws racks and marks invalid ones with text, not colour alone', () => {
    render(<PlanView length={3.048} width={2.4384} unit="ft" racks={racks} invalidRacks={new Set(['R2'])} />)
    expect(screen.getByRole('img', { name: /2 racks/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rack R1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rack R2, invalid' })).toBeInTheDocument()
    expect(screen.getByText('R2 ✕')).toBeInTheDocument()
    expect(screen.getByText('10.0 ft')).toBeInTheDocument()
  })
  it('selects a rack on pointer down', () => {
    const onSelect = vi.fn()
    render(<PlanView length={3} width={2} unit="m" racks={racks} onSelect={onSelect} />)
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Rack R1' }))
    expect(onSelect).toHaveBeenCalledWith({ kind: 'rack', id: 'R1' })
  })
})

describe('AuthPage', () => {
  it('shows field errors without calling the API', async () => {
    const calls = mockFetch({})
    wrap(<AuthPage mode="signup" />)
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Enter your name')).toBeInTheDocument()
    expect(screen.getByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Use at least 8 characters')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })
  it('shows the server error on failed sign-in', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED', message: 'Incorrect email or password' } }), { status: 401 })))
    wrap(<AuthPage mode="login" />)
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.co')
    await userEvent.type(screen.getByLabelText('Password'), 'wrongpass')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Incorrect email or password')).toBeInTheDocument()
  })
})

describe('Alerts & insights page', () => {
  const farm = { id: 7, name: 'Test', room: null, is_sample: false }
  it('lists open alerts with severity text and acknowledges them', async () => {
    let status = 'OPEN'
    const alert = () => ({ id: 1, metric: 'ph', severity: 'CRITICAL', value: 8, message: 'pH 8.00 is above the critical limit 7.2.', suggestion: 'Add pH-down.', status, source_type: 'RULE', data_source: 'SIMULATED', created_at: new Date().toISOString() })
    const calls = mockFetch({
      '/api/farms/7/alerts': () => (status === 'OPEN' ? [alert()] : []),
      'PATCH /api/alerts/1': () => { status = 'ACKNOWLEDGED'; return alert() },
      '/api/farms/7/insights': [{ id: 3, category: 'LAYOUT', priority: 'HIGH', title: 'No door marked on the plan', explanation: 'x', evidence: {}, action: 'Mark the door', source_type: 'RULE', created_at: '' }],
      '/api/farms/7': farm,
    })
    wrap(<InsightsPage />, '/farms/7/insights', '/farms/:farmId/insights')
    expect(await screen.findByText(/pH 8.00 is above/)).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('No door marked on the plan')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH' && c.body?.includes('ACKNOWLEDGED'))).toBe(true))
    expect(await screen.findByText('No open alerts')).toBeInTheDocument()
  })
})

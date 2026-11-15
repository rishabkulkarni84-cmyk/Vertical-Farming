import { lazy, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import AppShell from './components/AppShell'
import { Spinner } from './components/ui'
import { ApiError } from './lib/api'
import { useMe } from './lib/hooks'
import AuthPage from './pages/AuthPage'

// every page is its own chunk, so sign-in and the first screen load fast
const Dashboard = lazy(() => import('./pages/Dashboard'))
const FarmsPage = lazy(() => import('./pages/FarmsPage'))
const SetupWizard = lazy(() => import('./pages/SetupWizard'))
const PlanPage = lazy(() => import('./pages/PlanPage'))
const SpacePage = lazy(() => import('./pages/SpacePage'))
const GridPage = lazy(() => import('./pages/GridPage'))
const LayoutBuilder = lazy(() => import('./pages/LayoutBuilder'))
const CropsPage = lazy(() => import('./pages/CropsPage'))
const CostsPage = lazy(() => import('./pages/CostsPage'))
const ScenariosPage = lazy(() => import('./pages/ScenariosPage'))
const InsightsPage = lazy(() => import('./pages/InsightsPage'))
const ReportPage = lazy(() => import('./pages/ReportPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const HelpPage = lazy(() => import('./pages/HelpPage'))
const ViewPage = lazy(() => import('./pages/ViewPage'))
const MonitorPage = lazy(() => import('./pages/MonitorPage'))

function RequireAuth({ children }: { children: ReactNode }) {
  const { data, isLoading, error } = useMe()
  const loc = useLocation()
  if (isLoading) return <Spinner label="Checking your session" />
  if (error instanceof ApiError && error.status === 401) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (!data) return <div className="p-10 text-center text-sm text-crit">Cannot reach the server. Start the backend and reload.</div>
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/signup" element={<AuthPage mode="signup" />} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<Dashboard />} />
        <Route path="farms" element={<FarmsPage />} />
        <Route path="farms/new" element={<SetupWizard />} />
        <Route path="farms/:farmId">
          <Route index element={<Navigate to="setup" replace />} />
          <Route path="setup" element={<SetupWizard />} />
          <Route path="space" element={<SpacePage />} />
          <Route path="grid" element={<GridPage />} />
          <Route path="plan" element={<PlanPage />} />
          <Route path="layout" element={<LayoutBuilder />} />
          <Route path="view" element={<ViewPage />} />
          <Route path="crops" element={<CropsPage />} />
          <Route path="costs" element={<CostsPage />} />
          <Route path="scenarios" element={<ScenariosPage />} />
          <Route path="monitor" element={<MonitorPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route path="report" element={<ReportPage />} />
        </Route>
        <Route path="settings" element={<SettingsPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route path="*" element={<div className="py-20 text-center"><h1 className="text-2xl font-semibold">Page not found</h1><p className="text-muted mt-2">Use the menu to get back to your farms.</p></div>} />
      </Route>
    </Routes>
  )
}

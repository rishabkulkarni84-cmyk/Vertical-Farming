import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import AiSettingsPanel from '../components/AiSettingsPanel'
import { Button, Field, Input, PageHeader, Panel, Segmented } from '../components/ui'
import { patch, post } from '../lib/api'
import { useAction, useMe } from '../lib/hooks'
import type { Unit, User } from '../lib/types'

export default function SettingsPage() {
  const { data: me } = useMe()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  useEffect(() => { if (me) setName(me.name) }, [me])
  const setUser = (u: User) => qc.setQueryData(['me'], u)
  const saveName = useAction(() => patch<User>('/auth/me', { name: name.trim() }), { success: 'Profile saved', onSuccess: setUser })
  const setUnit = useAction((u: Unit) => patch<User>('/auth/me', { preferences: { display_unit: u } }), { success: 'Display units updated', onSuccess: setUser })
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' })
  const mismatch = pw.confirm !== '' && pw.confirm !== pw.new_password
  const changePw = useAction(() => post('/auth/change-password', { current_password: pw.current_password, new_password: pw.new_password }),
    { success: 'Password changed. Other sessions were signed out.', onSuccess: () => setPw({ current_password: '', new_password: '', confirm: '' }) })
  return (
    <>
      <PageHeader title="Settings" description="Your AI assistant, profile and how measurements are shown." />
      <div className="grid gap-6 max-w-3xl">
        <AiSettingsPanel />
        <Panel title="Display units" description="Applies to plans, layout settings, reports and dimension labels.">
          <Segmented label="Display units" value={(me?.preferences.display_unit as Unit) ?? 'm'} onChange={(u) => setUnit.mutate(u)}
            options={[{ value: 'm', label: 'Metres' }, { value: 'cm', label: 'Centimetres' }, { value: 'ft', label: 'Feet' }, { value: 'in', label: 'Inches' }]} />
        </Panel>
        <Panel title="Profile">
          <form className="flex items-end gap-3" onSubmit={(e) => { e.preventDefault(); saveName.mutate(undefined) }}>
            <div className="flex-1"><Field label="Name" htmlFor="pn"><Input id="pn" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field></div>
            <Button type="submit" disabled={!name.trim() || name === me?.name} loading={saveName.isPending}>Save name</Button>
          </form>
          <p className="text-[13px] text-muted mt-3">Signed in as {me?.email}</p>
        </Panel>
        <Panel title="Change password">
          <form className="grid gap-3 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); changePw.mutate(undefined) }}>
            <Field label="Current password" htmlFor="cp"><Input id="cp" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label="New password" htmlFor="np" hint="At least 8 characters"><Input id="np" type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Field label="Repeat new password" htmlFor="rp" error={mismatch ? "Passwords don't match" : undefined}><Input id="rp" type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
            <div className="sm:col-span-3"><Button type="submit" disabled={!pw.current_password || pw.new_password.length < 8 || mismatch || !pw.confirm} loading={changePw.isPending}>Change password</Button></div>
          </form>
        </Panel>
      </div>
    </>
  )
}

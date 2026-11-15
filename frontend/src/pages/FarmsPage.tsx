import { useQuery } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Copy, MoreHorizontal, Pencil, Plus, Sprout, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, ConfirmDialog, Dialog, Empty, ErrorState, Field, Input, PageHeader, Panel, Segmented, Spinner } from '../components/ui'
import { del, get, patch, post } from '../lib/api'
import { useAction, useDisplayUnit } from '../lib/hooks'
import { fmtLen, timeAgo } from '../lib/units'
import type { DesignSummary, Farm } from '../lib/types'

function Designs({ farm }: { farm: Farm }) {
  const { data } = useQuery({ queryKey: ['designs', farm.id], queryFn: () => get<DesignSummary[]>(`/farms/${farm.id}/designs`) })
  const activate = useAction((id: number) => post(`/designs/${id}/activate`), { success: 'Active design changed', invalidate: [['designs', farm.id], ['farm', farm.id], ['farms']] })
  const dup = useAction((id: number) => post(`/designs/${id}/duplicate`), { success: 'Design duplicated', invalidate: [['designs', farm.id]] })
  const [toDelete, setToDelete] = useState<DesignSummary | null>(null)
  const rm = useAction((id: number) => del(`/designs/${id}`), { success: 'Design deleted', invalidate: [['designs', farm.id], ['farm', farm.id], ['farms']], onSuccess: () => setToDelete(null) })
  if (!data?.length) return <p className="text-[13px] text-muted py-2">No saved designs yet. <Link className="text-forest-700 hover:underline" to={`/farms/${farm.id}/layout`}>Open the layout builder</Link>.</p>
  return (
    <>
      <ul className="divide-y divide-line/70">
        {data.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-3 py-2 text-[13.5px]">
            <span className="font-medium">{d.name}</span>
            {d.is_active && <Badge tone="good">Active</Badge>}
            <Badge>{d.origin.toLowerCase()}</Badge>
            <span className="text-muted">{d.rack_count} racks · {d.rack_config.levels} levels · {timeAgo(d.updated_at)}</span>
            <span className="ml-auto flex gap-1">
              {!d.is_active && <Button size="sm" variant="ghost" onClick={() => activate.mutate(d.id)}>Make active</Button>}
              <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={() => dup.mutate(d.id)}>Duplicate</Button>
              <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => setToDelete(d)} aria-label={`Delete ${d.name}`} />
            </span>
          </li>
        ))}
      </ul>
      <ConfirmDialog open={!!toDelete} onClose={() => setToDelete(null)} title="Delete design?" danger confirmLabel="Delete design" loading={rm.isPending}
        onConfirm={() => toDelete && rm.mutate(toDelete.id)} body={<>“{toDelete?.name}” and its bill of materials will be permanently removed.</>} />
    </>
  )
}

export default function FarmsPage() {
  const [status, setStatus] = useState<'ACTIVE' | 'ARCHIVED'>('ACTIVE')
  const unit = useDisplayUnit()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['farms', status], queryFn: () => get<Farm[]>(`/farms?status=${status}`) })
  const [menu, setMenu] = useState<number | null>(null)
  const [renaming, setRenaming] = useState<Farm | null>(null)
  const [name, setName] = useState('')
  const [deleting, setDeleting] = useState<Farm | null>(null)
  const inv = [['farms'], ['dashboard']]
  const rename = useAction((v: { id: number; name: string }) => patch(`/farms/${v.id}`, { name: v.name }), { success: 'Farm renamed', invalidate: inv, onSuccess: () => setRenaming(null) })
  const archive = useAction((f: Farm) => patch(`/farms/${f.id}`, { status: f.status === 'ACTIVE' ? 'ARCHIVED' : 'ACTIVE' }), { success: (r: any) => (r.status === 'ARCHIVED' ? 'Farm archived' : 'Farm restored'), invalidate: inv })
  const dup = useAction((id: number) => post<Farm>(`/farms/${id}/duplicate`), { success: 'Farm duplicated with its room, obstacles and designs', invalidate: inv })
  const rm = useAction((id: number) => del(`/farms/${id}`), { success: 'Farm deleted', invalidate: inv, onSuccess: () => setDeleting(null) })

  return (
    <>
      <PageHeader title="Farms & designs" description="Every farm keeps its room, obstacles, saved layouts, scenarios and monitoring history."
        actions={<><Segmented label="Show" value={status} onChange={setStatus} options={[{ value: 'ACTIVE', label: 'Active' }, { value: 'ARCHIVED', label: 'Archived' }]} />
          <Link to="/farms/new"><Button icon={<Plus className="size-4" />}>New farm</Button></Link></>} />
      {isLoading ? <Spinner /> : error ? <ErrorState error={error} retry={refetch} /> : !data?.length ? (
        <Panel><Empty icon={<Sprout className="size-8" />} title={status === 'ACTIVE' ? 'No farms yet' : 'No archived farms'}
          action={status === 'ACTIVE' && <Link to="/farms/new"><Button>Create a farm</Button></Link>}>
          {status === 'ACTIVE' ? 'Start with the room setup wizard.' : 'Archived farms appear here and can be restored.'}</Empty></Panel>
      ) : (
        <div className="space-y-4">
          {data.map((f) => (
            <Panel key={f.id} title={<Link to={`/farms/${f.id}/layout`} className="hover:text-forest-700">{f.name}</Link>}
              description={f.room ? `${fmtLen(f.room.length_m, unit)} × ${fmtLen(f.room.width_m, unit)} · ${f.obstacle_count} obstacles · ${f.design_count} designs` : 'Room not set up'}
              actions={
                <div className="relative">
                  <Button size="sm" variant="ghost" aria-label={`Actions for ${f.name}`} aria-expanded={menu === f.id} onClick={() => setMenu(menu === f.id ? null : f.id)} icon={<MoreHorizontal className="size-4" />} />
                  {menu === f.id && (
                    <div className="absolute right-0 mt-1 w-44 rounded-lg border border-line bg-surface shadow-xl z-20 py-1 text-[13.5px]" onMouseLeave={() => setMenu(null)}>
                      {[
                        { icon: <Pencil className="size-4" />, label: 'Rename', fn: () => { setRenaming(f); setName(f.name) } },
                        { icon: <Copy className="size-4" />, label: 'Duplicate', fn: () => dup.mutate(f.id) },
                        { icon: f.status === 'ACTIVE' ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />, label: f.status === 'ACTIVE' ? 'Archive' : 'Restore', fn: () => archive.mutate(f) },
                        { icon: <Trash2 className="size-4 text-crit" />, label: 'Delete', fn: () => setDeleting(f) },
                      ].map((a) => <button key={a.label} className="w-full flex items-center gap-2 px-3 py-2 hover:bg-sage-50 text-left" onClick={() => { setMenu(null); a.fn() }}>{a.icon}{a.label}</button>)}
                    </div>
                  )}
                </div>}>
              <Designs farm={f} />
            </Panel>
          ))}
        </div>
      )}
      <Dialog open={!!renaming} onClose={() => setRenaming(null)} title="Rename farm"
        footer={<><Button variant="secondary" onClick={() => setRenaming(null)}>Cancel</Button><Button loading={rename.isPending} disabled={!name.trim()} onClick={() => renaming && rename.mutate({ id: renaming.id, name: name.trim() })}>Save name</Button></>}>
        <Field label="Farm name" htmlFor="rn"><Input id="rn" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
      </Dialog>
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} danger title="Delete this farm?" confirmLabel="Delete farm permanently" loading={rm.isPending}
        onConfirm={() => deleting && rm.mutate(deleting.id)}
        body={<>This permanently deletes <b>{deleting?.name}</b>: its room, photos, obstacles, {deleting?.design_count} design(s), scenarios, sensor history and alerts. Archive it instead if you might need it later.</>} />
    </>
  )
}

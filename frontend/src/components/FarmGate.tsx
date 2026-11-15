import { Ruler } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useFarm, useFarmId } from '../lib/hooks'
import type { Farm } from '../lib/types'
import { Badge, Button, Empty, ErrorState, Panel, Spinner } from './ui'

/** Loads the current farm and requires room dimensions before rendering spatial pages. */
export default function FarmGate({ children, needRoom = true, needDesign = false }: { children: (farm: Farm) => ReactNode; needRoom?: boolean; needDesign?: boolean }) {
  const id = useFarmId()
  const { data: farm, isLoading, error, refetch } = useFarm(id)
  if (isLoading) return <Spinner label="Loading farm" />
  if (error || !farm) return <ErrorState error={error} retry={refetch} />
  if (needRoom && !farm.room) return (
    <Panel><Empty icon={<Ruler className="size-8" />} title="Enter the room size first"
      action={<Link to={`/farms/${farm.id}/setup`}><Button>Open room setup</Button></Link>}>
      Every layout, capacity and cost figure is calculated from the room's length, width and height.
    </Empty></Panel>
  )
  if (needDesign && !farm.active_design_id) return (
    <Panel><Empty icon={<Ruler className="size-8" />} title="No saved layout yet"
      action={<Link to={`/farms/${farm.id}/layout`}><Button>Open layout builder</Button></Link>}>
      Generate a rack layout and save it; this page uses the saved design.
    </Empty></Panel>
  )
  return <>{children(farm)}</>
}

export function FarmCrumb({ farm, page }: { farm: Farm; page: string }) {
  return (
    <span className="flex items-center gap-2">
      <Link to="/farms" className="hover:underline">Farms</Link><span aria-hidden>/</span>
      <span className="text-ink-soft">{farm.name}</span><span aria-hidden>/</span><span>{page}</span>
      {farm.is_sample && <Badge tone="info">Sample data</Badge>}
    </span>
  )
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { errorMessage, get } from './api'
import type { Design, Farm, Obstacle, Unit, User } from './types'

export const useMe = () => useQuery({ queryKey: ['me'], queryFn: () => get<User>('/auth/me'), retry: false, staleTime: 60_000 })

export function useDisplayUnit(): Unit {
  const { data } = useMe()
  return (data?.preferences?.display_unit as Unit) ?? 'm'
}

export function useFarmId() {
  const { farmId } = useParams()
  return Number(farmId)
}

export const useFarm = (id: number) => useQuery({ queryKey: ['farm', id], queryFn: () => get<Farm>(`/farms/${id}`), enabled: !!id })
export const useObstacles = (id: number) => useQuery({ queryKey: ['obstacles', id], queryFn: () => get<Obstacle[]>(`/farms/${id}/obstacles`), enabled: !!id })
export const useDesign = (id: number | null | undefined) => useQuery({ queryKey: ['design', id], queryFn: () => get<Design>(`/designs/${id}`), enabled: !!id })

/** Mutation with toast feedback and cache invalidation. */
export function useAction<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, opts: { success?: string | ((r: TRes) => string); invalidate?: unknown[][]; onSuccess?: (r: TRes, v: TVars) => void; silentError?: boolean } = {}) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r, v) => {
      opts.invalidate?.forEach((k) => qc.invalidateQueries({ queryKey: k }))
      if (opts.success) toast.success(typeof opts.success === 'function' ? opts.success(r) : opts.success)
      opts.onSuccess?.(r, v)
    },
    onError: (e) => { if (!opts.silentError) toast.error(errorMessage(e)) },
  })
}

/** Invalidate everything that depends on a farm's spatial or design data. */
export function useInvalidateFarm() {
  const qc = useQueryClient()
  return (farmId: number) => {
    for (const k of ['farm', 'obstacles', 'grid', 'designs', 'recs', 'insights', 'report', 'costs', 'geometry']) qc.invalidateQueries({ queryKey: [k, farmId] })
    qc.invalidateQueries({ queryKey: ['design'] })
    qc.invalidateQueries({ queryKey: ['costs'] })
    qc.invalidateQueries({ queryKey: ['geometry'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
    qc.invalidateQueries({ queryKey: ['alert-summary'] })
  }
}

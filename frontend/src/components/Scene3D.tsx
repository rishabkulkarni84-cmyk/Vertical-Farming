import { OrbitControls } from '@react-three/drei'
import { Canvas } from '@react-three/fiber'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { fmtLen } from '../lib/units'
import type { Unit } from '../lib/types'

export interface Geometry {
  room: { length: number; width: number; height: number }
  obstacles: { id: number; kind: string; label: string | null; x: number; y: number; w: number; d: number; render_height: number }[]
  access_zones: { x: number; y: number; w: number; d: number }[]
  racks: { label: string; x: number; y: number; w: number; d: number; height: number; levels: number[]; access_side: string | null }[]
  aisles: { rack: string; x: number; y: number; w: number; d: number }[]
  planting: { per_row: number | null; per_col: number | null; plants_per_level: number | null; spacing_m: number | null; edge_margin_m: number; crop: string | null }
  validation: { valid: boolean }
  model_note: string
}

export type Layers = { walls: boolean; plants: boolean; lights: boolean; obstacles: boolean; aisles: boolean; dims: boolean }

const POST = 0.03

/** Text label as a canvas-texture sprite (no DOM portal, no external font fetch). */
function Label({ text, position, dark = false, size = 0.16 }: { text: string; position: [number, number, number]; dark?: boolean; size?: number }) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas')
    const ctx = c.getContext('2d')!
    const font = '600 44px "Schibsted Grotesk Variable", system-ui, sans-serif'
    ctx.font = font
    const w = Math.ceil(ctx.measureText(text).width) + 28
    c.width = w
    c.height = 64
    ctx.font = font
    ctx.fillStyle = dark ? '#1e4a37' : 'rgba(255,255,255,0.92)'
    ctx.beginPath()
    ctx.roundRect(0, 0, w, 64, 12)
    ctx.fill()
    ctx.fillStyle = dark ? '#ffffff' : '#13221b'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, 14, 34)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    return { t, aspect: w / 64 }
  }, [text, dark])
  useEffect(() => () => tex.t.dispose(), [tex])
  return (
    <sprite position={position} scale={[size * tex.aspect, size, 1]} renderOrder={10}>
      <spriteMaterial map={tex.t} depthTest={false} transparent />
    </sprite>
  )
}
const SHELF_T = 0.025

function Plants({ racks, planting }: { racks: Geometry['racks']; planting: Geometry['planting'] }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const positions = useMemo(() => {
    const out: [number, number, number][] = []
    const { per_row, per_col, spacing_m, edge_margin_m } = planting
    if (!per_row || !per_col || !spacing_m) return out
    for (const r of racks) {
      const along = r.w >= r.d
      for (const lv of r.levels) {
        for (let i = 0; i < per_row; i++) for (let j = 0; j < per_col; j++) {
          const a = edge_margin_m + spacing_m * (i + 0.5)
          const b = edge_margin_m + spacing_m * (j + 0.5)
          out.push(along ? [r.x + a, lv + SHELF_T + 0.06, r.y + b] : [r.x + b, lv + SHELF_T + 0.06, r.y + a])
        }
      }
    }
    return out
  }, [racks, planting])
  useLayoutEffect(() => {
    const m = new THREE.Matrix4()
    positions.forEach((p, i) => { m.makeTranslation(...p); ref.current?.setMatrixAt(i, m) })
    if (ref.current) ref.current.instanceMatrix.needsUpdate = true
  }, [positions])
  if (!positions.length) return null
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, positions.length]} castShadow>
      <sphereGeometry args={[Math.min(0.07, (planting.spacing_m ?? 0.2) * 0.38), 10, 8]} />
      <meshStandardMaterial color="#5fae6e" roughness={0.8} />
    </instancedMesh>
  )
}

function RackModel({ r, showLights }: { r: Geometry['racks'][number]; showLights: boolean }) {
  const corners: [number, number][] = [[r.x + POST / 2, r.y + POST / 2], [r.x + r.w - POST / 2, r.y + POST / 2], [r.x + POST / 2, r.y + r.d - POST / 2], [r.x + r.w - POST / 2, r.y + r.d - POST / 2]]
  const lights = [...r.levels.slice(1), r.height]
  return (
    <group>
      {corners.map(([x, z], i) => (
        <mesh key={i} position={[x, r.height / 2, z]} castShadow><boxGeometry args={[POST, r.height, POST]} /><meshStandardMaterial color="#9aa7a0" metalness={0.6} roughness={0.4} /></mesh>
      ))}
      {r.levels.map((lv, i) => (
        <mesh key={i} position={[r.x + r.w / 2, lv + SHELF_T / 2, r.y + r.d / 2]} castShadow receiveShadow>
          <boxGeometry args={[r.w, SHELF_T, r.d]} /><meshStandardMaterial color="#e9ece8" roughness={0.7} />
        </mesh>
      ))}
      {showLights && lights.map((h, i) => (
        <mesh key={`l${i}`} position={[r.x + r.w / 2, h - 0.03, r.y + r.d / 2]}>
          <boxGeometry args={[r.w >= r.d ? r.w * 0.85 : 0.04, 0.015, r.w >= r.d ? 0.04 : r.d * 0.85]} />
          <meshStandardMaterial color="#f5e6ff" emissive="#e8d4ff" emissiveIntensity={1.4} />
        </mesh>
      ))}
      <Label text={r.label} dark position={[r.x + r.w / 2, r.height + 0.14, r.y + r.d / 2]} />
    </group>
  )
}

export default function Scene3D({ geo, layers, unit }: { geo: Geometry; layers: Layers; unit: Unit }) {
  const { length: L, width: W, height: H } = geo.room
  const target: [number, number, number] = [L / 2, H * 0.3, W / 2]
  const dist = Math.max(L, W) * 1.35 + 1
  return (
    <Canvas shadows dpr={[1, 2]} camera={{ position: [L / 2 + dist * 0.7, H * 1.4 + 1, W / 2 + dist], fov: 42, near: 0.05, far: 200 }}
      aria-label="3D planning model" role="img">
      <color attach="background" args={['#eef2ee']} />
      <hemisphereLight args={['#ffffff', '#c9d4cc', 0.85]} />
      <directionalLight position={[L, H * 2.5, W * 1.5]} intensity={1.1} castShadow shadow-mapSize={[1024, 1024]} />
      {/* floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[L / 2, 0, W / 2]} receiveShadow>
        <planeGeometry args={[L, W]} /><meshStandardMaterial color="#f8f9f6" />
      </mesh>
      <gridHelper args={[Math.max(L, W), Math.round(Math.max(L, W) / 0.3048), '#c4cfc6', '#dfe5df']} position={[Math.max(L, W) / 2, 0.002, Math.max(L, W) / 2]} />
      {layers.walls && <>
        <mesh position={[L / 2, H / 2, 0]}><boxGeometry args={[L, H, 0.04]} /><meshStandardMaterial color="#dfe5df" transparent opacity={0.35} side={THREE.DoubleSide} /></mesh>
        <mesh position={[0, H / 2, W / 2]}><boxGeometry args={[0.04, H, W]} /><meshStandardMaterial color="#dfe5df" transparent opacity={0.35} side={THREE.DoubleSide} /></mesh>
        <lineSegments position={[L / 2, H / 2, W / 2]}><edgesGeometry args={[new THREE.BoxGeometry(L, H, W)]} /><lineBasicMaterial color="#3d4f45" /></lineSegments>
      </>}
      {layers.aisles && geo.aisles.map((a, i) => (
        <mesh key={i} rotation={[-Math.PI / 2, 0, 0]} position={[a.x + a.w / 2, 0.004, a.y + a.d / 2]}><planeGeometry args={[a.w, a.d]} /><meshBasicMaterial color="#bfcfc3" transparent opacity={0.6} /></mesh>
      ))}
      {layers.aisles && geo.access_zones.map((a, i) => (
        <mesh key={`z${i}`} rotation={[-Math.PI / 2, 0, 0]} position={[a.x + a.w / 2, 0.005, a.y + a.d / 2]}><planeGeometry args={[a.w, a.d]} /><meshBasicMaterial color="#e6b860" transparent opacity={0.45} /></mesh>
      ))}
      {layers.obstacles && geo.obstacles.map((o) => {
        if (o.kind === 'WINDOW') return (
          <mesh key={o.id} position={[o.x + o.w / 2, 0.9 + 0.6, o.y + o.d / 2]}><boxGeometry args={[Math.max(o.w, 0.03), 1.2, Math.max(o.d, 0.03)]} /><meshStandardMaterial color="#9cc3e4" transparent opacity={0.55} /></mesh>)
        if (o.kind === 'DOOR') return (
          <mesh key={o.id} position={[o.x + o.w / 2, o.render_height / 2, o.y + o.d / 2]}><boxGeometry args={[Math.max(o.w, 0.04), o.render_height, Math.max(o.d, 0.04)]} /><meshStandardMaterial color="#c49a5a" /></mesh>)
        return (
          <mesh key={o.id} position={[o.x + o.w / 2, o.render_height / 2, o.y + o.d / 2]} castShadow>
            <boxGeometry args={[o.w, o.render_height, o.d]} /><meshStandardMaterial color={o.kind === 'RESTRICTED' ? '#d9a297' : '#8b958e'} transparent={o.kind === 'RESTRICTED'} opacity={o.kind === 'RESTRICTED' ? 0.6 : 1} />
          </mesh>)
      })}
      {geo.racks.map((r) => <RackModel key={r.label} r={r} showLights={layers.lights} />)}
      {layers.plants && <Plants racks={geo.racks} planting={geo.planting} />}
      {layers.dims && <>
        <Label text={`Length ${fmtLen(L, unit)}`} position={[L / 2, 0.05, W + 0.3]} />
        <Label text={`Width ${fmtLen(W, unit)}`} position={[L + 0.35, 0.05, W / 2]} />
        <Label text={`Ceiling ${fmtLen(H, unit)}`} position={[0, H + 0.12, 0]} />
      </>}
      <OrbitControls target={target} makeDefault enableDamping maxPolarAngle={Math.PI / 2.05} minDistance={0.8} maxDistance={dist * 3} />
    </Canvas>
  )
}

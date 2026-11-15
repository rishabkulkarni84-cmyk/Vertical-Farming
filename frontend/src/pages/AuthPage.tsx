import { zodResolver } from '@hookform/resolvers/zod'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { Button, Callout, Field, Input } from '../components/ui'
import { errorMessage, post } from '../lib/api'

const loginSchema = z.object({ email: z.email('Enter a valid email address'), password: z.string().min(1, 'Enter your password') })
const signupSchema = z.object({
  name: z.string().trim().min(1, 'Enter your name'),
  email: z.email('Enter a valid email address'),
  password: z.string().min(8, 'Use at least 8 characters'),
})
type FormVals = { name?: string; email: string; password: string }

/** A tiny drafted plan that reads as the product: room outline, door swing, racks, aisle. */
function PlanSketch() {
  return (
    <svg viewBox="0 0 320 240" className="w-full max-w-sm" aria-hidden>
      <g stroke="#dce5dd" fill="none">
        <rect x="20" y="30" width="280" height="180" strokeWidth="3" />
        <path d="M60 30 v6 M60 30 q0 42 42 42" strokeWidth="1.2" strokeDasharray="3 3" />
        <line x1="20" y1="14" x2="300" y2="14" strokeWidth="1" /><line x1="20" y1="9" x2="20" y2="19" /><line x1="300" y1="9" x2="300" y2="19" />
      </g>
      <text x="160" y="10" fill="#bfcfc3" fontSize="10" textAnchor="middle" fontFamily="inherit">10 ft</text>
      <rect x="22" y="160" width="120" height="44" fill="#34735a" /><rect x="148" y="160" width="120" height="44" fill="#34735a" />
      <rect x="166" y="80" width="120" height="44" fill="#34735a" />
      <rect x="22" y="124" width="276" height="34" fill="#8da594" opacity=".35" />
      <g fill="#dce5dd" fontSize="11" fontWeight="700" textAnchor="middle" fontFamily="inherit"><text x="82" y="186">R1</text><text x="208" y="186">R2</text><text x="226" y="106">R3</text></g>
    </svg>
  )
}

export default function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const nav = useNavigate()
  const loc = useLocation()
  const qc = useQueryClient()
  const [err, setErr] = useState<string | null>(null)
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormVals>({ resolver: zodResolver((mode === 'login' ? loginSchema : signupSchema) as any) })

  const onSubmit = async (v: FormVals) => {
    setErr(null)
    try {
      const r = await post<{ user: unknown }>(`/auth/${mode}`, v)
      qc.setQueryData(['me'], r.user)
      nav((loc.state as { from?: string })?.from ?? (mode === 'signup' ? '/farms/new' : '/'), { replace: true })
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  return (
    <div className="min-h-dvh grid lg:grid-cols-[1fr_1.1fr]">
      <div className="hidden lg:flex flex-col justify-between bg-forest-800 text-white p-12">
        <div className="font-display text-2xl font-semibold">Verdant</div>
        <div className="space-y-8">
          <PlanSketch />
          <div className="max-w-md">
            <h2 className="text-[32px] leading-[1.15] font-semibold">Find out whether a vertical farm fits your room — before you buy a single rack.</h2>
            <p className="mt-4 text-sage-200 leading-relaxed">Enter your room, mark the door and obstacles, and get rack layouts that pass every clearance check, crop suggestions that explain themselves, and a costed bill of materials.</p>
          </div>
        </div>
        <p className="text-[12.5px] text-sage-500">Monitoring in this version uses simulated sensor data, clearly labelled.</p>
      </div>
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <div className="lg:hidden font-display text-2xl font-semibold text-forest-800 mb-8">Verdant</div>
          <h1 className="text-[26px] font-semibold">{mode === 'login' ? 'Sign in' : 'Create your account'}</h1>
          <p className="text-sm text-muted mt-1">{mode === 'login' ? 'Welcome back. Your farms are where you left them.' : 'Free to use. Your designs are private to your account.'}</p>
          <form onSubmit={handleSubmit(onSubmit)} className="mt-8 space-y-4" noValidate>
            {err && <Callout tone="crit">{err}</Callout>}
            {mode === 'signup' && (
              <Field label="Name" htmlFor="name" error={errors.name?.message}><Input id="name" autoComplete="name" aria-invalid={!!errors.name} {...register('name')} /></Field>
            )}
            <Field label="Email" htmlFor="email" error={errors.email?.message}><Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register('email')} /></Field>
            <Field label="Password" htmlFor="password" error={errors.password?.message} hint={mode === 'signup' ? 'At least 8 characters.' : undefined}>
              <Input id="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} aria-invalid={!!errors.password} {...register('password')} />
            </Field>
            <Button type="submit" className="w-full" loading={isSubmitting}>{mode === 'login' ? 'Sign in' : 'Create account'}</Button>
          </form>
          <p className="mt-6 text-sm text-ink-soft">
            {mode === 'login' ? <>New to Verdant? <Link className="font-medium text-forest-700 hover:underline" to="/signup">Create an account</Link></>
              : <>Already have an account? <Link className="font-medium text-forest-700 hover:underline" to="/login">Sign in</Link></>}
          </p>
          {mode === 'login' && <p className="mt-3 text-[12.5px] text-muted">Running locally with demo data? Sign in as <code className="text-ink">demo@verdant.app</code> / <code className="text-ink">verdant-demo-2026</code>.</p>}
        </div>
      </div>
    </div>
  )
}

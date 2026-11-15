import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, CircleAlert, Info, Loader2, X } from 'lucide-react'
import { forwardRef, useEffect, useId, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { errorMessage } from '../lib/api'

/* ------------------------------------------------------------------ buttons */
type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle'
const btn: Record<BtnVariant, string> = {
  primary: 'bg-forest-800 text-white hover:bg-forest-700 shadow-[inset_0_-1px_0_rgba(0,0,0,.2)]',
  secondary: 'bg-surface text-ink border border-line-strong hover:border-forest-600 hover:text-forest-800',
  ghost: 'text-ink-soft hover:bg-sage-100 hover:text-ink',
  subtle: 'bg-sage-100 text-forest-800 hover:bg-sage-200',
  danger: 'bg-crit text-white hover:brightness-110',
}

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm' | 'md'; loading?: boolean; icon?: ReactNode }>(
  function Button({ variant = 'primary', size = 'md', loading, icon, className, children, disabled, ...rest }, ref) {
    return (
      <button ref={ref} disabled={disabled || loading}
        className={clsx('inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap',
          size === 'sm' ? 'h-8 px-3 text-[13px]' : 'h-10 px-4 text-sm', btn[variant], className)} {...rest}>
        {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
        {children}
      </button>
    )
  })

/* ------------------------------------------------------------------ form fields */
export function Field({ label, hint, error, children, htmlFor, required }: { label: string; hint?: ReactNode; error?: string; children: ReactNode; htmlFor?: string; required?: boolean }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}{required && <span className="text-crit ml-0.5" aria-hidden>*</span>}
      </label>
      {children}
      {error ? <p className="text-[12px] text-crit flex items-center gap-1" role="alert"><CircleAlert className="size-3.5" aria-hidden />{error}</p>
        : hint ? <p className="text-[12px] text-muted">{hint}</p> : null}
    </div>
  )
}

const inputCls = 'w-full h-10 rounded-md border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-muted/70 focus:border-forest-600 focus:outline-none focus:ring-3 focus:ring-forest-600/15 aria-[invalid=true]:border-crit'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { suffix?: string }>(function Input({ className, suffix, ...rest }, ref) {
  if (!suffix) return <input ref={ref} className={clsx(inputCls, className)} {...rest} />
  return (
    <div className="relative">
      <input ref={ref} className={clsx(inputCls, 'pr-12', className)} {...rest} />
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] text-muted">{suffix}</span>
    </div>
  )
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return <select ref={ref} className={clsx(inputCls, 'pr-8 appearance-none bg-[url("data:image/svg+xml;utf8,<svg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 24 24%27 fill=%27none%27 stroke=%27%2366766c%27 stroke-width=%272.5%27><path d=%27m6 9 6 6 6-6%27/></svg>")] bg-no-repeat bg-[right_0.75rem_center]', className)} {...rest}>{children}</select>
})

export function NumberField({ label, value, onChange, unit, step = 0.01, min, max, hint, id }: { label: string; value: number | null | undefined; onChange: (v: number | null) => void; unit?: string; step?: number; min?: number; max?: number; hint?: string; id?: string }) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <Field label={label} hint={hint} htmlFor={fid}>
      <Input id={fid} type="number" inputMode="decimal" step={step} min={min} max={max} suffix={unit}
        value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
    </Field>
  )
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line-strong bg-surface p-0.5">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={clsx('h-8 px-3 rounded text-[13px] font-medium transition-colors', value === o.value ? 'bg-forest-800 text-white' : 'text-ink-soft hover:text-ink')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ layout */
export function PageHeader({ title, description, actions, crumb }: { title: string; description?: ReactNode; actions?: ReactNode; crumb?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="min-w-0 max-w-3xl">
        {crumb && <div className="text-[13px] text-muted mb-1.5">{crumb}</div>}
        <h1 className="text-[28px] leading-tight font-semibold text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-[15px] text-ink-soft leading-relaxed">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Panel({ title, description, actions, children, className, pad = true }: { title?: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={clsx('rounded-[10px] border border-line bg-surface', className)}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
          <div className="min-w-0">
            {title && <h2 className="font-sans text-[15px] font-semibold tracking-normal text-ink">{title}</h2>}
            {description && <p className="text-[13px] text-muted mt-0.5">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={clsx(pad && 'px-5 pb-5', !title && !actions && pad && 'pt-5')}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'warn' | 'crit' | 'good' }) {
  return (
    <div className="min-w-0">
      <div className="text-[12.5px] text-muted">{label}</div>
      <div className={clsx('font-display text-[26px] leading-tight font-semibold mt-0.5', tone === 'warn' && 'text-warn', tone === 'crit' && 'text-crit', tone === 'good' && 'text-grow')}>{value}</div>
      {sub && <div className="text-[12.5px] text-ink-soft mt-0.5">{sub}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------ badges */
const SOURCE: Record<string, { cls: string; label: string; title: string }> = {
  SIMULATED: { cls: 'bg-sim-soft text-sim', label: 'Simulated', title: 'Generated by the software simulator — not a physical sensor reading' },
  ILLUSTRATIVE: { cls: 'bg-warn-soft text-warn', label: 'Illustrative', title: 'Sample planning price, not a quote' },
  USER_INPUT: { cls: 'bg-info-soft text-info', label: 'Your input', title: 'Value you entered' },
  RULE: { cls: 'bg-sage-100 text-forest-800', label: 'Rule', title: 'Deterministic, documented rule — not an AI prediction' },
  EXTERNAL_DATA: { cls: 'bg-sage-100 text-ink', label: 'External', title: 'From an external data provider' },
  ESTIMATE: { cls: 'bg-sage-50 text-ink-soft border border-line', label: 'Estimate', title: 'Calculated from assumptions' },
  MODEL: { cls: 'bg-sim-soft text-sim', label: 'Model', title: 'Machine-learning model output' },
}
export function SourceBadge({ source, className }: { source: string; className?: string }) {
  const s = SOURCE[source] ?? { cls: 'bg-sage-100 text-ink-soft', label: source, title: source }
  return <span title={s.title} className={clsx('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] font-medium', s.cls, className)}>{source === 'SIMULATED' && <span aria-hidden className="size-1.5 rounded-full bg-sim animate-pulse" />}{s.label}</span>
}

type Tone = 'good' | 'warn' | 'crit' | 'info' | 'neutral'
const toneCls: Record<Tone, string> = { good: 'bg-grow-soft text-grow', warn: 'bg-warn-soft text-warn', crit: 'bg-crit-soft text-crit', info: 'bg-info-soft text-info', neutral: 'bg-sage-100 text-ink-soft' }
export function Badge({ tone = 'neutral', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={clsx('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] font-medium', toneCls[tone], className)}>{children}</span>
}

export function Callout({ tone = 'info', title, children, className }: { tone?: Tone; title?: ReactNode; children?: ReactNode; className?: string }) {
  const Icon = tone === 'good' ? CheckCircle2 : tone === 'warn' || tone === 'crit' ? AlertTriangle : Info
  return (
    <div role={tone === 'crit' ? 'alert' : undefined} className={clsx('flex gap-3 rounded-lg px-4 py-3 text-[13.5px]', toneCls[tone], className)}>
      <Icon className="size-4 mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 text-ink">{title && <div className="font-semibold">{title}</div>}{children && <div className="text-ink-soft leading-relaxed">{children}</div>}</div>
    </div>
  )
}

/* ------------------------------------------------------------------ states */
export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <div className="flex items-center gap-2 text-sm text-muted py-10 justify-center" role="status"><Loader2 className="size-4 animate-spin" aria-hidden />{label}…</div>
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center py-12 px-6">
      {icon && <div className="mb-3 text-sage-500">{icon}</div>}
      <h3 className="font-sans text-[15px] font-semibold tracking-normal">{title}</h3>
      {children && <p className="mt-1 text-[13.5px] text-muted max-w-md">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="rounded-lg border border-crit/30 bg-crit-soft px-4 py-4 text-sm flex items-start gap-3" role="alert">
      <AlertTriangle className="size-4 text-crit mt-0.5" aria-hidden />
      <div className="flex-1"><div className="font-semibold text-ink">Couldn't load this</div><div className="text-ink-soft">{errorMessage(error)}</div></div>
      {retry && <Button size="sm" variant="secondary" onClick={retry}>Try again</Button>}
    </div>
  )
}

/* ------------------------------------------------------------------ dialog */
export function Dialog({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('input,select,textarea,button:not([data-close])')?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); prev?.focus() }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6">
      <div className="absolute inset-0 bg-ink/40" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className={clsx('relative w-full bg-surface rounded-t-xl sm:rounded-xl shadow-2xl max-h-[90vh] flex flex-col', wide ? 'sm:max-w-2xl' : 'sm:max-w-md')}>
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button data-close onClick={onClose} className="p-1 rounded hover:bg-sage-100" aria-label="Close dialog"><X className="size-4" /></button>
        </div>
        <div className="px-5 pb-4 overflow-y-auto">{children}</div>
        {footer && <div className="flex justify-end gap-2 px-5 py-3 border-t border-line bg-sage-50 rounded-b-xl">{footer}</div>}
      </div>
    </div>
  )
}

export function ConfirmDialog({ open, onClose, onConfirm, title, body, confirmLabel, danger, loading }: { open: boolean; onClose: () => void; onConfirm: () => void; title: string; body: ReactNode; confirmLabel: string; danger?: boolean; loading?: boolean }) {
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={loading}>{confirmLabel}</Button></>}>
      <div className="text-sm text-ink-soft leading-relaxed">{body}</div>
    </Dialog>
  )
}

export function Table({ head, children, className }: { head: ReactNode[]; children: ReactNode; className?: string }) {
  return (
    <div className={clsx('overflow-x-auto', className)}>
      <table className="w-full text-[13.5px]">
        <thead><tr className="border-b border-line text-left text-[12.5px] text-muted">{head.map((h, i) => <th key={i} scope="col" className="font-medium py-2 px-3 first:pl-0 last:pr-0 whitespace-nowrap">{h}</th>)}</tr></thead>
        <tbody className="[&>tr]:border-b [&>tr]:border-line/70 [&>tr:last-child]:border-0 [&_td]:py-2.5 [&_td]:px-3 [&_td:first-child]:pl-0 [&_td:last-child]:pr-0">{children}</tbody>
      </table>
    </div>
  )
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[13.5px]">
      {items.map(([k, v], i) => (<div key={i} className="contents"><dt className="text-muted">{k}</dt><dd className="text-ink text-right font-medium">{v}</dd></div>))}
    </dl>
  )
}

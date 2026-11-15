import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, KeyRound, PlugZap, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { del, get, post, put } from '../lib/api'
import { useAction } from '../lib/hooks'
import type { AiSettings } from '../lib/types'
import { Badge, Button, Callout, Field, Input, Panel, Select } from './ui'

const KEY_HELP: Record<string, { url: string; hint: string }> = {
  gemini: { url: 'https://aistudio.google.com/apikey', hint: 'Starts with “AIza”. Create one in Google AI Studio.' },
  anthropic: { url: 'https://console.anthropic.com/settings/keys', hint: 'Starts with “sk-ant-”. Create one in the Anthropic Console.' },
  openai: { url: 'https://platform.openai.com/api-keys', hint: 'Starts with “sk-”. Create one in the OpenAI dashboard.' },
}

export default function AiSettingsPanel() {
  const qc = useQueryClient()
  const { data: s } = useQuery({ queryKey: ['ai-settings'], queryFn: () => get<AiSettings>('/ai/settings') })
  const [provider, setProvider] = useState('gemini')
  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [web, setWeb] = useState(true)
  const [models, setModels] = useState<string[]>([])
  useEffect(() => {
    if (s?.configured) { setProvider(s.provider!); setModel(s.model ?? ''); setWeb(s.web_search) }
  }, [s])
  const def = s?.providers.find((p) => p.id === provider)?.default_model ?? ''
  const test = useAction(() => post<{ models: string[]; default_model: string }>('/ai/test', { provider, api_key: key || null }), {
    success: (r) => `Key works — ${r.models.length} models available`,
    onSuccess: (r) => { setModels(r.models); if (!model || !r.models.includes(model)) setModel(r.models.includes(r.default_model) ? r.default_model : r.models[0] ?? '') },
  })
  const save = useAction(() => put<AiSettings>('/ai/settings', { provider, api_key: key || null, model, web_search: web }), {
    success: 'AI assistant saved', onSuccess: (r) => { qc.setQueryData(['ai-settings'], r); setKey('') },
  })
  const remove = useAction(() => del('/ai/settings'), { success: 'API key removed', invalidate: [['ai-settings']], onSuccess: () => { setModels([]); setModel('') } })
  const sameProvider = s?.configured && s.provider === provider

  return (
    <Panel title={<span className="flex items-center gap-2">AI assistant {s?.configured ? <Badge tone="good"><CheckCircle2 className="size-3" />Connected</Badge> : <Badge>Not set up</Badge>}</span>}
      description="Reads room photos, and suggests crops for your location, season and budget with current prices. Your key stays on the Verdant server and is never shown in the browser again.">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined) }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Provider" htmlFor="ai-p">
            <Select id="ai-p" value={provider} onChange={(e) => { setProvider(e.target.value); setModels([]); setModel('') }}>
              {s?.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </Select>
          </Field>
          <Field label="API key" htmlFor="ai-k" hint={sameProvider ? `Saved key ${s?.key_hint}. Leave blank to keep it.` : KEY_HELP[provider]?.hint}>
            <Input id="ai-k" type="password" autoComplete="off" placeholder={sameProvider ? '••••••••' : 'Paste your key'} value={key} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <Field label="Model" htmlFor="ai-m" hint={models.length ? `${models.length} models from your account.` : `Use “Test & load models” to pick one. Default: ${def}`}>
            {models.length ? (
              <Select id="ai-m" value={model} onChange={(e) => setModel(e.target.value)}>{models.map((m) => <option key={m} value={m}>{m}</option>)}</Select>
            ) : <Input id="ai-m" value={model} placeholder={def} onChange={(e) => setModel(e.target.value)} />}
          </Field>
          <div className="flex items-end pb-2">
            <label className="flex items-start gap-2 text-[13.5px]">
              <input type="checkbox" className="accent-forest-700 size-4 mt-0.5" checked={web} onChange={(e) => setWeb(e.target.checked)} />
              <span>Use live web search for prices and trends<span className="block text-[12px] text-muted">Recommended. Sources are shown with every suggestion. May cost more per request.</span></span>
            </label>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" icon={<PlugZap className="size-4" />} loading={test.isPending} disabled={!key && !sameProvider} onClick={() => test.mutate(undefined)}>Test & load models</Button>
          <Button type="submit" icon={<KeyRound className="size-4" />} loading={save.isPending} disabled={!key && !sameProvider}>Save AI settings</Button>
          {s?.configured && s.origin === 'USER' && <Button type="button" variant="ghost" icon={<Trash2 className="size-4" />} onClick={() => remove.mutate(undefined)}>Remove key</Button>}
        </div>
        <p className="text-[12.5px] text-muted">Get a key: <a className="text-forest-700 underline" href={KEY_HELP[provider]?.url} target="_blank" rel="noreferrer">{KEY_HELP[provider]?.url.replace('https://', '')}</a>. Usage is billed by your provider.</p>
        {s?.origin === 'SERVER_ENV' && <Callout tone="info">Using the server's AI key from its environment settings. Saving here overrides it for your account.</Callout>}
      </form>
    </Panel>
  )
}

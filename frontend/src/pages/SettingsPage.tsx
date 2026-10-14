import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ExternalLink, Loader2, RefreshCw } from 'lucide-react'
import { BrandMark } from '@/components/BrandMark'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import type { AiProvider } from '@/lib/types'
import { useAiConfig, useHealth, useSaveAiConfig } from '@/store/api'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className="truncate font-mono text-zinc-200">{value}</span>
    </div>
  )
}

/** Placeholders de Base URL / Modelo / API key por provedor. */
const PROVIDER_PLACEHOLDERS: Record<
  AiProvider,
  { baseUrl: string; model: string; apiKey: string }
> = {
  ollama: { baseUrl: 'http://localhost:11434', model: 'qwen2.5-coder:latest', apiKey: '' },
  openai: { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini', apiKey: 'sk-...' },
  custom: { baseUrl: 'https://...', model: 'seu-modelo', apiKey: 'sk-...' },
  anthropic: {
    baseUrl: 'https://api.anthropic.com',
    model: 'claude-sonnet-4-20250514',
    apiKey: 'sk-ant-...',
  },
  gemini: {
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta',
    model: 'gemini-2.0-flash',
    apiKey: 'AIza...',
  },
}

/**
 * Card "Provedor de IA" (GET/PUT /api/ai/config).
 *
 * A API key só vai para o backend quando digitada; string vazia = manter a
 * chave já salva. O GET nunca devolve a chave — só `has_api_key`.
 */
function AiProviderCard() {
  const { data: config } = useAiConfig()
  const save = useSaveAiConfig()
  const [provider, setProvider] = useState<AiProvider>('ollama')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const synced = useRef(false)

  // Sincroniza o form com o backend quando os dados chegam (primeira carga ou
  // troca real de dados). O ref `synced` evita sobrescrever o que o usuário
  // está digitando em refetches de fundo com os mesmos dados.
  useEffect(() => {
    if (!config || synced.current) return
    synced.current = true
    setProvider(config.provider)
    setBaseUrl(config.base_url)
    setModel(config.model)
  }, [config])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (save.isPending) return
    save.mutate(
      {
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
        api_key: apiKey.trim() || null,
      },
      {
        onSuccess: () => {
          setApiKey('')
          // libera o próximo refetch (pós-invalidate) para re-sincronizar
          synced.current = false
        },
      },
    )
  }

  const placeholders = PROVIDER_PLACEHOLDERS[provider]

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Provedor de IA
          {config && (
            <Badge variant={config.has_api_key ? 'success' : 'secondary'}>
              {config.has_api_key ? 'Chave configurada' : 'Sem chave'}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          Modelo usado pelo relatório arquitetural. Ollama roda local; OpenAI,
          Anthropic, Gemini e customizado usam API key.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="ai-provider" className="text-sm text-zinc-500">
                Provedor
              </label>
              <Select
                id="ai-provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value as AiProvider)}
                className="w-full"
              >
                <option value="ollama">Ollama (local)</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="gemini">Google Gemini</option>
                <option value="custom">Customizado</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="ai-model" className="text-sm text-zinc-500">
                Modelo
              </label>
              <Input
                id="ai-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={placeholders.model}
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="ai-base-url" className="text-sm text-zinc-500">
              Base URL
            </label>
            <Input
              id="ai-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={placeholders.baseUrl}
              className="font-mono text-xs"
            />
          </div>

          {provider !== 'ollama' && (
            <div className="space-y-1.5">
              <label htmlFor="ai-api-key" className="text-sm text-zinc-500">
                API Key
              </label>
              <Input
                id="ai-api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={placeholders.apiKey}
                autoComplete="off"
                className="font-mono text-xs"
              />
              <p className="text-xs text-zinc-500">
                Em branco mantém a chave já salva.
              </p>
            </div>
          )}

          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : null}
              Salvar configuração
            </Button>
            <p className="text-xs text-zinc-500">
              A chave é armazenada apenas no backend e nunca é enviada de volta ao
              navegador.
            </p>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const { data: health, isLoading, error, refetch, isRefetching } = useHealth()

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Configurações</h1>
        <p className="text-sm text-zinc-500">
          Estado do serviço e informações do ambiente. Tudo roda localmente.
        </p>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <BrandMark className="h-5 w-5" />
              Serviço
            </CardTitle>
            <CardDescription>Health check da API Pandora.</CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => refetch()}
            disabled={isRefetching}
            aria-label="Atualizar status"
          >
            <RefreshCw className={isRefetching ? 'animate-spin' : undefined} />
          </Button>
        </CardHeader>
        <CardContent className="space-y-1">
          {isLoading && (
            <p className="flex items-center gap-2 text-sm text-zinc-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Consultando /api/health…
            </p>
          )}
          {error && (
            <div className="rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-sm text-rose-300">
              API indisponível — {error instanceof Error ? error.message : 'erro desconhecido'}.
              <p className="mt-1 text-xs text-rose-400/80">
                Suba o backend com <code className="font-mono">scripts/run.sh</code>.
              </p>
            </div>
          )}
          {health && (
            <>
              <Row label="Status" value={health.status} />
              <Row label="Serviço" value={health.service} />
              <Row label="Versão" value={health.version} />
              <Row label="Banco" value={health.database} />
              <Row label="Python" value={health.python} />
              <Row label="Projetos registrados" value={String(health.projects)} />
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Privacidade</CardTitle>
          <CardDescription>
            O Pandora lê apenas os caminhos de repositório que você registrar.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-zinc-400">
          <p>Nenhum arquivo é enviado para fora da máquina.</p>
          <p>Remover um projeto apaga só o registro e os dados analisados.</p>
          <p>
            Diretórios permitidos são controlados pela variável{' '}
            <code className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-cyan-300">
              PANDORA_ALLOWED_DIRS
            </code>{' '}
            no <code className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs">.env</code>.
          </p>
        </CardContent>
      </Card>

      <AiProviderCard />

      <Card>
        <CardHeader>
          <CardTitle>Atalhos</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-zinc-400">Documentação do backend</span>
            <span className="flex items-center gap-1.5 font-mono text-xs text-zinc-500">
              <ExternalLink className="h-3.5 w-3.5" /> backend/app/routers/
            </span>
          </div>
          <Separator />
          <div className="flex items-center justify-between text-sm">
            <span className="text-zinc-400">Interface</span>
            <Badge variant="secondary">v0.1.0</Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

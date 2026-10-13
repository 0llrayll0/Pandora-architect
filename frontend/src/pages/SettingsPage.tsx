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
import { Separator } from '@/components/ui/separator'
import { useHealth } from '@/store/api'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span className="truncate font-mono text-zinc-200">{value}</span>
    </div>
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

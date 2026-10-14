import { AlertTriangle, Check, Lightbulb, Loader2, Sparkles, Wand2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/EmptyState'
import { useActiveRun } from '@/hooks/useActiveRun'
import { ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { useGenerateReport, useReport } from '@/store/api'
import type { ArchitectureReport } from '@/lib/types'

const SEVERITY: Record<string, { label: string; variant: BadgeProps['variant'] }> = {
  high: { label: 'Alta', variant: 'danger' },
  medium: { label: 'Média', variant: 'warning' },
  low: { label: 'Baixa', variant: 'success' },
}

function severityBadge(severity: string) {
  const entry = SEVERITY[severity] ?? { label: severity, variant: 'secondary' as const }
  return (
    <Badge variant={entry.variant} className="shrink-0 capitalize">
      {entry.label}
    </Badge>
  )
}

function isReportNotFound(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 404 &&
    error.code === 'report_not_found'
  )
}

export function ArchitectPage({ projectId }: { projectId: number }) {
  const { runId } = useActiveRun(projectId)
  const reportQuery = useReport(runId)
  const generate = useGenerateReport(runId)

  if (runId === null) {
    return (
      <EmptyState
        icon={<Sparkles className="h-8 w-8" />}
        title="Execute uma análise primeiro"
        description="O Arquiteto IA lê o grafo real do código. Rode uma análise para liberar o relatório."
      />
    )
  }

  // Relatório inexistente é um estado comum (antes da 1ª geração), não um erro.
  const notFound = isReportNotFound(reportQuery.error)
  const hardError = reportQuery.error !== null && !notFound
  const report = reportQuery.data

  // Primeira geração (ainda não há nada em cache): spinner dedicado.
  if (generate.isPending && report === undefined) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
        <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
        <p className="text-sm text-zinc-300">Analisando arquitetura…</p>
        <p className="text-xs text-zinc-500">(pode levar até 1 minuto)</p>
      </div>
    )
  }

  // Regenerando com relatório em cache: mantém o relatório antigo visível com
  // um banner de progresso no lugar (não esconde tudo).
  if (report !== undefined) {
    return (
      <div className="space-y-5">
        {generate.isPending && (
          <div className="flex items-center gap-2 rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-200">
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
            Regenerando relatório… (pode levar até 1 minuto) — o relatório atual
            permanece visível.
          </div>
        )}
        <ReportView
          report={report}
          regenerating={generate.isPending}
          onRegenerate={() => generate.mutate()}
        />
      </div>
    )
  }

  if (reportQuery.isLoading) {
    return <p className="text-sm text-zinc-500">Carregando relatório…</p>
  }

  if (hardError) {
    return (
      <EmptyState
        title="Falha ao carregar o relatório"
        description={reportQuery.error instanceof Error ? reportQuery.error.message : 'Erro inesperado.'}
      />
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Arquiteto IA</h1>
        <p className="text-sm text-zinc-500">Relatório arquitetural da análise #{runId}.</p>
      </div>
      <EmptyState
        icon={<Wand2 className="h-8 w-8" />}
        title="Nenhum relatório gerado"
        description="Gere o relatório a partir do grafo real desta análise. Heurísticas sempre rodam; o Ollama é usado se estiver disponível."
        action={
          <Button size="sm" onClick={() => generate.mutate()}>
            <Wand2 /> Gerar relatório
          </Button>
        }
      />
    </div>
  )
}

function ReportView({
  report,
  regenerating,
  onRegenerate,
}: {
  report: ArchitectureReport
  regenerating: boolean
  onRegenerate: () => void
}) {
  return (
    <div className="space-y-5">
      {/* Header: run, modelo, origem do conteúdo e regenerar */}
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold text-zinc-100">Arquiteto IA</h1>
          <Badge variant="secondary">run #{report.run_id}</Badge>
          <Badge variant={report.ollama_used ? 'default' : 'secondary'}>
            {report.ollama_used ? 'Gerado com IA' : 'Só heurísticas'}
          </Badge>
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto"
            disabled={regenerating}
            onClick={onRegenerate}
            title="Gera novamente a partir do grafo desta análise"
          >
            {regenerating ? <Loader2 className="animate-spin" /> : <Wand2 />}
            {regenerating ? 'Regenerando…' : 'Regenerar relatório'}
          </Button>
        </div>
        <p className="text-xs text-zinc-500">
          Modelo: {report.ollama_model ?? 'heurísticas'} · gerado em{' '}
          {formatDateTime(report.generated_at)}
        </p>
      </div>

      {/* Resumo executivo */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Resumo executivo</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed text-zinc-300">{report.executive_summary}</p>
        </CardContent>
      </Card>

      {/* Pontos fortes | Riscos */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Pontos fortes</CardTitle>
          </CardHeader>
          <CardContent>
            {report.strengths.length === 0 ? (
              <p className="text-xs text-zinc-500">Nenhum ponto forte identificado.</p>
            ) : (
              <ul className="space-y-2">
                {report.strengths.map((item, index) => (
                  <li key={index} className="flex items-start gap-2 text-sm text-zinc-300">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle>Riscos</CardTitle>
          </CardHeader>
          <CardContent>
            {report.risks.length === 0 ? (
              <p className="text-xs text-zinc-500">Nenhum risco identificado.</p>
            ) : (
              <ul className="space-y-3">
                {report.risks.map((risk, index) => (
                  <li key={index} className="space-y-1">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                      <span className="text-sm font-medium text-zinc-200">{risk.title}</span>
                      {severityBadge(risk.severity)}
                    </div>
                    <p className="text-xs leading-relaxed text-zinc-400">{risk.description}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Dependências (interna/externa + recomendações) */}
      {report.dependencies && <DependenciesCard deps={report.dependencies} />}

      {/* Plano de ação */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Plano de ação</CardTitle>
        </CardHeader>
        <CardContent>
          {report.action_plan.length === 0 ? (
            <p className="text-xs text-zinc-500">Nenhuma ação recomendada.</p>
          ) : (
            <ol className="space-y-4">
              {report.action_plan.map((step, index) => (
                <li key={index} className="flex gap-3">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-[11px] font-semibold text-violet-300 ring-1 ring-inset ring-violet-500/30">
                    {index + 1}
                  </span>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-zinc-200">{step.action}</p>
                    <p className="text-xs text-zinc-400">
                      <span className="text-zinc-500">Justificativa: </span>
                      {step.justification}
                    </p>
                    <p className="text-xs text-zinc-400">
                      <span className="text-zinc-500">Impacto: </span>
                      {step.impact}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {/* Honestidade sobre a origem do conteúdo */}
      {!report.ollama_used && (
        <p className="text-[11px] text-zinc-600">
          Ollama indisponível — relatório baseado apenas em heurísticas determinísticas
        </p>
      )}
    </div>
  )
}

function DependenciesCard({ deps }: { deps: NonNullable<ArchitectureReport['dependencies']> }) {
  const thirdParty = deps.external.filter((d) => !d.is_stdlib)

  if (deps.internal.length === 0 && thirdParty.length === 0 && deps.recommendations.length === 0) {
    return null
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          Dependências
          <Badge variant="secondary">
            {deps.internal.length} internas · {thirdParty.length} externas
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Módulos internos */}
        {deps.internal.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Internas
            </h4>
            <ul className="space-y-1.5">
              {deps.internal.map((item) => (
                <li
                  key={item.name}
                  title={item.imported_by.join(', ')}
                  className="flex items-center justify-between gap-3 rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-1.5"
                >
                  <span className="truncate font-mono text-xs text-zinc-200">{item.name}</span>
                  <span className="shrink-0 text-xs text-zinc-500">
                    importado por {item.imported_by.length} arquivo(s)
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Pacotes de terceiros (não-stdlib) */}
        {thirdParty.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Externas (pacotes de terceiros)
            </h4>
            <div className="flex flex-wrap gap-2">
              {thirdParty.map((d) => (
                <Badge key={d.name} variant="outline">
                  {d.name} ×{d.import_count}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Recomendações */}
        {deps.recommendations.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Recomendações
            </h4>
            <ul className="space-y-2">
              {deps.recommendations.map((rec, index) => (
                <li key={index} className="flex items-start gap-2">
                  <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                  <p className="text-sm leading-relaxed text-zinc-300">{rec}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

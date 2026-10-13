import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AppState {
  /** Projeto ativo (persistido em localStorage). */
  activeProjectId: number | null
  /** Run selecionada/exibindo progresso no momento. */
  selectedRunId: number | null
  /** Progresso ao vivo vindo do SSE (null quando nenhuma análise roda). */
  liveProgress: LiveProgress | null
  setActiveProject: (id: number | null) => void
  setSelectedRun: (id: number | null) => void
  setLiveProgress: (progress: LiveProgress | null) => void
}

export interface LiveProgress {
  runId: number
  projectId: number
  state: string
  progress: number
  stage: string
  message: string
  filesTotal: number
  filesProcessed: number
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      activeProjectId: null,
      selectedRunId: null,
      liveProgress: null,
      setActiveProject: (id) =>
        set({ activeProjectId: id, selectedRunId: null, liveProgress: null }),
      setSelectedRun: (id) => set({ selectedRunId: id }),
      setLiveProgress: (progress) => set({ liveProgress: progress }),
    }),
    {
      name: 'pandora-architect',
      // só o projeto ativo persiste; run/progresso são voláteis
      partialize: (state) => ({ activeProjectId: state.activeProjectId }),
    },
  ),
)

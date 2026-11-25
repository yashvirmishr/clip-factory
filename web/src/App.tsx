import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, formatTime, formatTimecode, pollUntilDone } from './api'
import type {
  Analysis,
  ChatStatus,
  Clip,
  Hardware,
  JobState,
  LearnState,
  Peaks,
  SourceInfo,
  SourceRow,
  Verdict,
} from './types'
import { Inspector, type InspectorTab } from './components/Inspector'
import { Monitor, type MonitorHandle, type OverlayMode } from './components/Monitor'
import { ProjectPanel } from './components/ProjectPanel'
import { Reel, REJECT_REASONS, type ClipFilter, type ClipSort, type ClipView } from './components/Reel'
import { SetupModal } from './components/SetupModal'
import { Timeline } from './components/Timeline'
import { AboutDialog } from './workspace/AboutDialog'
import { CommandPalette } from './workspace/CommandPalette'
import { ContextMenu } from './workspace/ContextMenu'
import { Icon, type IconName } from './workspace/Icon'
import { InspectorFrame, type FloatRect } from './workspace/InspectorFrame'
import { MenuBar } from './workspace/MenuBar'
import { Resizer } from './workspace/Resizer'
import { ShortcutsDialog } from './workspace/ShortcutsDialog'
import { StatusBar } from './workspace/StatusBar'
import { Tabs } from './workspace/Tabs'
import type { AppCommand, MenuDefinition } from './workspace/types'
import { useMediaQuery } from './workspace/useMediaQuery'
import { usePersistentState } from './workspace/usePersistentState'
import { IconButton } from './workspace/ui'
import { ThemeAtelier } from './theme/ThemeAtelier'
import { useTheme } from './theme/useTheme'

const PHASES = [
  { id: 'audio', label: 'Audio', stages: ['audio'] },
  { id: 'transcribe', label: 'Transcribe', stages: ['transcribe', 'align'] },
  { id: 'signals', label: 'Signals', stages: ['windows', 'signals', 'gates'] },
  { id: 'score', label: 'Score', stages: ['score'] },
  { id: 'select', label: 'Select', stages: ['select', 'done'] },
]

const CHAT_PHASES = [{ id: 'chat', label: 'Chat', stages: ['chat'] }]

interface Toast {
  id: number
  kind: 'ok' | 'error' | 'info'
  message: string
}

type CentreTab = 'reel' | 'monitor' | 'timeline'
type WorkspacePreset = 'triage' | 'editing' | 'review'
type ProjectTab = 'project' | 'insights'

interface LayoutState {
  leftWidth: number
  rightWidth: number
  leftOpen: boolean
  rightOpen: boolean
  inspectorFloating: boolean
  floatRect: FloatRect
  centreTab: CentreTab
  inspectorTab: InspectorTab
  projectTab: ProjectTab
  clipFilter: ClipFilter
  clipSort: ClipSort
  clipView: ClipView
  clipQuery: string
  monitorOverlay: OverlayMode
  monitorLoop: boolean
  monitorGuides: boolean
  workspace: WorkspacePreset
}

interface ContextState {
  x: number
  y: number
  label: string
  items: Array<AppCommand | null>
}

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

function defaultFloatRect(): FloatRect {
  const width = typeof window === 'undefined' ? 1480 : window.innerWidth
  const height = typeof window === 'undefined' ? 940 : window.innerHeight
  return {
    x: Math.max(16, width - 432),
    y: 92,
    width: 400,
    height: clamp(height - 170, 420, 760),
  }
}

const DEFAULT_LAYOUT: LayoutState = {
  leftWidth: 264,
  rightWidth: 400,
  leftOpen: true,
  rightOpen: true,
  inspectorFloating: false,
  floatRect: defaultFloatRect(),
  centreTab: 'reel',
  inspectorTab: 'properties',
  projectTab: 'project',
  clipFilter: 'all',
  clipSort: 'rank',
  clipView: 'list',
  clipQuery: '',
  monitorOverlay: 'hook',
  monitorLoop: false,
  monitorGuides: false,
  workspace: 'triage',
}

const WORKSPACES: Array<{ id: WorkspacePreset; label: string; icon: IconName; hint: string }> = [
  { id: 'triage', label: 'Triage', icon: 'list', hint: 'Reel, inspector and project bin' },
  { id: 'editing', label: 'Editing', icon: 'scissors', hint: 'Monitor, timeline and inspector' },
  { id: 'review', label: 'Review', icon: 'monitor', hint: 'Full-frame review, panels stowed' },
]

const WORKSPACE_PRESETS: Record<
  WorkspacePreset,
  Partial<Pick<LayoutState, 'leftOpen' | 'rightOpen' | 'centreTab' | 'inspectorTab' | 'leftWidth' | 'rightWidth' | 'monitorOverlay' | 'monitorGuides' | 'monitorLoop'>>
> = {
  triage: {
    leftOpen: true,
    rightOpen: true,
    centreTab: 'reel',
    inspectorTab: 'properties',
    leftWidth: 264,
    rightWidth: 400,
    monitorOverlay: 'hook',
    monitorGuides: false,
    monitorLoop: false,
  },
  editing: {
    leftOpen: true,
    rightOpen: true,
    centreTab: 'monitor',
    inspectorTab: 'properties',
    leftWidth: 236,
    rightWidth: 420,
    monitorOverlay: 'captions',
    monitorGuides: true,
    monitorLoop: true,
  },
  review: {
    leftOpen: false,
    rightOpen: false,
    centreTab: 'monitor',
    inspectorTab: 'properties',
    monitorOverlay: 'captions',
    monitorGuides: true,
    monitorLoop: true,
  },
}

const MENUS: MenuDefinition[] = [
  { id: 'file', label: 'File', items: ['file.import', 'file.demo', 'file.fetchChat', '-', 'file.exportBundle', '-', 'file.setup'] },
  {
    id: 'edit',
    label: 'Edit',
    items: [
      'edit.searchSources',
      'edit.searchClips',
      '-',
      'edit.copyHook',
      'edit.copyTimecode',
      'edit.copyTranscript',
      '-',
      'edit.resetWorkspace',
    ],
  },
  {
    id: 'view',
    label: 'View',
    items: [
      'view.palette',
      'view.themes',
      '-',
      'view.toggleProject',
      'view.toggleInspector',
      'view.floatInspector',
      '-',
      'view.reel',
      'view.monitor',
      'view.timeline',
      '-',
      'view.inspectorProperties',
      'view.inspectorCaptions',
      'view.inspectorOutput',
    ],
  },
  {
    id: 'clip',
    label: 'Clip',
    items: [
      'clip.analyze',
      '-',
      'clip.approve',
      'clip.reject',
      'clip.render',
      '-',
      'clip.next',
      'clip.previous',
    ],
  },
  {
    id: 'workspace',
    label: 'Workspace',
    items: ['workspace.triage', 'workspace.editing', 'workspace.review', '-', 'edit.resetWorkspace'],
  },
  { id: 'help', label: 'Help', items: ['help.shortcuts', 'help.setup', 'help.about'] },
]

function phaseStates(job: JobState | null, phases: typeof PHASES = PHASES): Record<string, string> {
  if (!job) return {}
  const finished = job.status === 'done'
  const index = phases.findIndex((phase) => phase.stages.includes(job.stage))
  return Object.fromEntries(
    phases.map((phase, i) => {
      if (finished) return [phase.id, 'done']
      if (index === -1) return [phase.id, 'idle']
      if (i < index) return [phase.id, 'done']
      if (i === index) return [phase.id, 'active']
      return [phase.id, 'idle']
    }),
  )
}

export default function App() {
  const [layout, setLayout] = usePersistentState<LayoutState>('clip-factory.workspace.v2', DEFAULT_LAYOUT)
  const compact = useMediaQuery('(max-width: 1240px)')
  const theme = useTheme()

  const [sources, setSources] = useState<SourceRow[]>([])
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [learn, setLearn] = useState<LearnState | null>(null)
  const [peaks, setPeaks] = useState<Peaks | null>(null)
  const [job, setJob] = useState<JobState | null>(null)
  const [chat, setChat] = useState<ChatStatus | null>(null)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({})
  const [rejecting, setRejecting] = useState<string | null>(null)
  const [playhead, setPlayhead] = useState(0)
  const [seekRequest, setSeekRequest] = useState<{ seconds: number; nonce: number } | null>(null)
  const [captions, setCaptions] = useState<import('./types').Captions | null>(null)
  const [captionsLoading, setCaptionsLoading] = useState(false)
  const [renderRequest, setRenderRequest] = useState<{ clipId: string; nonce: number } | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [themesOpen, setThemesOpen] = useState(false)
  const [contextMenu, setContextMenu] = useState<ContextState | null>(null)
  const [hardware, setHardware] = useState<Hardware | null>(null)
  const [hardwareError, setHardwareError] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [ingestPath, setIngestPath] = useState('')
  const [ingesting, setIngesting] = useState(false)
  const [version, setVersion] = useState('0.1')

  const toastId = useRef(0)
  const jobSourceRef = useRef<string | null>(null)
  const monitorRef = useRef<MonitorHandle>(null)

  const pushToast = useCallback((kind: Toast['kind'], message: string) => {
    const id = (toastId.current += 1)
    setToasts((current) => [...current, { id, kind, message }])
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id))
    }, 4600)
  }, [])

  const refreshSources = useCallback(async () => {
    try {
      setSources(await api.sources())
    } catch (error) {
      pushToast('error', `Could not list sources: ${(error as Error).message}`)
    }
  }, [pushToast])

  const refreshLearn = useCallback(async () => {
    try {
      setLearn(await api.learn())
    } catch {
      /* the learning panel simply stays empty */
    }
  }, [])

  const selectSource = useCallback(
    async (sourceId: string, preserveTab = false) => {
      setSelectedSourceId(sourceId)
      setAnalysis(null)
      setPeaks(null)
      setSelectedClipId(null)
      setVerdicts({})
      setPlayhead(0)
      setChat(null)
      setCaptions(null)
      setRenderRequest(null)
      setJob(null)
      setRejecting(null)
      if (!preserveTab) setLayout((current) => ({ ...current, centreTab: 'reel' }))
      try {
        setChat(await api.chatStatus(sourceId))
      } catch {
        /* chat is optional - the source simply has none */
      }
      try {
        const payload = await api.analysis(sourceId)
        setAnalysis(payload)
        const first = payload.candidates.find((clip) => clip.rank)
        setSelectedClipId(first?.id ?? null)
        if (first) {
          setPlayhead(first.start)
          setSeekRequest({ seconds: first.start, nonce: Date.now() })
        }
        try {
          setPeaks(await api.peaks(sourceId))
        } catch {
          /* peaks are optional */
        }
      } catch {
        /* not analyzed yet - the reel offers the analyze action */
      }
    },
    [setLayout],
  )

  useEffect(() => {
    void refreshSources()
    void refreshLearn()
    api
      .health()
      .then((payload) => setVersion(payload.version))
      .catch(() => undefined)
  }, [refreshSources, refreshLearn])

  useEffect(() => {
    if (selectedSourceId || sources.length === 0) return
    const first = sources.find((source) => source.analyzed) ?? sources[0]
    void selectSource(first.id, true)
  }, [sources, selectedSourceId, selectSource])

  // Clamp persisted widths once, so a layout saved on a larger display still
  // opens as a working window on a smaller one.
  useEffect(() => {
    setLayout((current) => {
      const leftWidth = clamp(current.leftWidth, 220, 420)
      const rightWidth = clamp(current.rightWidth, 340, 560)
      if (leftWidth === current.leftWidth && rightWidth === current.rightWidth) return current
      return { ...current, leftWidth, rightWidth }
    })
  }, [setLayout])

  useEffect(() => {
    const onResize = () => {
      setLayout((current) => {
        if (!current.inspectorFloating) return current
        const width = clamp(current.floatRect.width, 336, Math.max(336, window.innerWidth - 24))
        const height = clamp(current.floatRect.height, 380, Math.max(380, window.innerHeight - 60))
        const x = clamp(current.floatRect.x, 8, Math.max(8, window.innerWidth - width - 8))
        const y = clamp(current.floatRect.y, 36, Math.max(36, window.innerHeight - height - 8))
        if (
          width === current.floatRect.width &&
          height === current.floatRect.height &&
          x === current.floatRect.x &&
          y === current.floatRect.y
        ) {
          return current
        }
        return { ...current, floatRect: { x, y, width, height } }
      })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [setLayout])

  useEffect(() => {
    if (!compact) return
    setLayout((current) =>
      current.leftOpen || current.rightOpen ? { ...current, leftOpen: false, rightOpen: false } : current,
    )
  }, [compact, setLayout])

  const selectClip = useCallback(
    (clipId: string) => {
      setSelectedClipId(clipId)
      const clip = (analysis?.candidates ?? []).find((item) => item.id === clipId)
      if (!clip) return
      setPlayhead(clip.start)
      setSeekRequest({ seconds: clip.start, nonce: Date.now() })
    },
    [analysis],
  )

  const clips = useMemo<Clip[]>(
    () =>
      (analysis?.candidates ?? [])
        .filter((clip) => Boolean(clip.rank))
        .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99)),
    [analysis],
  )

  const selectedClip = useMemo(
    () => clips.find((clip) => clip.id === selectedClipId) ?? null,
    [clips, selectedClipId],
  )

  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? null
  const fps = selectedSource?.fps || 30
  const duration = selectedSource?.duration ?? 0
  const mediaSrc = selectedSourceId ? api.mediaUrl(selectedSourceId) : null
  const busy = Boolean(job && (job.status === 'running' || job.status === 'queued'))
  const labeling = busy || ingesting
  const shownPhases = job?.kind === 'chat' ? CHAT_PHASES : job?.kind === 'download' ? [{ id: 'download', label: 'Download', stages: ['download', 'ingest', 'fetch'] }] : PHASES
  const phases = phaseStates(job, shownPhases)

  // Captions are shared by the inspector and the program monitor.
  useEffect(() => {
    let cancelled = false
    setCaptions(null)
    if (!selectedSourceId || !selectedClip) {
      setCaptionsLoading(false)
      return
    }
    setCaptionsLoading(true)
    api
      .captions(selectedSourceId, selectedClip.id)
      .then((payload) => {
        if (!cancelled) setCaptions(payload)
      })
      .catch(() => {
        if (!cancelled) setCaptions(null)
      })
      .finally(() => {
        if (!cancelled) setCaptionsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedSourceId, selectedClip?.id])

  // Job polling
  useEffect(() => {
    if (!job || (job.status !== 'running' && job.status !== 'queued')) return
    const timer = window.setInterval(async () => {
      try {
        const next = await api.job(job.id)
        setJob(next)
        if (next.status === 'done') {
          if (next.analysis && next.kind !== 'chat' && next.kind !== 'download') {
            const jobSource = jobSourceRef.current
            if (jobSource === selectedSourceId) {
              setAnalysis(next.analysis)
              const first = next.analysis.candidates.find((clip) => clip.rank)
              setSelectedClipId(first?.id ?? null)
              if (first) {
                setPlayhead(first.start)
                setSeekRequest({ seconds: first.start, nonce: Date.now() })
              }
              if (jobSource) {
                try {
                  setPeaks(await api.peaks(jobSource))
                } catch {
                  /* peaks are optional */
                }
              }
            }
            void refreshSources()
            pushToast('ok', firstCopy(next.analysis))
          }
          if (next.kind === 'chat' && selectedSourceId) {
            try {
              setChat(await api.chatStatus(selectedSourceId))
            } catch {
              /* the fetch succeeded; a status refresh is best-effort */
            }
            pushToast('ok', 'Chat replay saved — re-analyze to score audience reaction')
          }
          if (next.kind === 'download') {
            pushToast('ok', 'Download finished.')
          }
        }
        if (next.status === 'error') {
          pushToast('error', next.error || 'Analysis failed')
        }
      } catch (error) {
        pushToast('error', `Lost contact with the job: ${(error as Error).message}`)
        setJob((current) =>
          current ? { ...current, status: 'error', error: (error as Error).message } : current,
        )
      }
    }, 650)
    return () => window.clearInterval(timer)
  }, [job?.id, job?.status, selectedSourceId, refreshSources, pushToast])

  useEffect(() => {
    if (job?.status !== 'done') return
    const id = job.id
    const timer = window.setTimeout(() => {
      setJob((current) => (current?.id === id ? null : current))
    }, 4800)
    return () => window.clearTimeout(timer)
  }, [job?.id, job?.status])

  const runAnalyze = useCallback(
    async (force: boolean, sourceId?: string) => {
      const id = sourceId ?? selectedSourceId
      if (!id) return
      try {
        pushToast('info', force ? 'Re-analyzing…' : 'Analyzing…')
        jobSourceRef.current = id
        setJob(await api.analyze(id, { limit: 10, force }))
      } catch (error) {
        pushToast('error', `Could not start analysis: ${(error as Error).message}`)
      }
    },
    [selectedSourceId, pushToast],
  )

  const fetchChat = useCallback(
    async (sourceId?: string) => {
      const id = sourceId ?? selectedSourceId
      if (!id) return
      try {
        pushToast('info', 'Fetching chat replay…')
        jobSourceRef.current = id
        setJob(await api.fetchChat(id))
      } catch (error) {
        pushToast('error', `Chat fetch failed: ${(error as Error).message}`)
      }
    },
    [selectedSourceId, pushToast],
  )

  const handleIngest = useCallback(
    async (rawPath?: string) => {
      const path = (rawPath ?? ingestPath).trim()
      if (!path) return
      const isUrl = /^https?:\/\//i.test(path)
      setIngesting(true)
      try {
        if (isUrl) {
          pushToast('info', 'Fetching that VOD…')
          const started = await api.ingestUrl(path)
          jobSourceRef.current = null
          setJob(started)
          const finished = await pollUntilDone(started.id)
          if (finished.status === 'error') {
            pushToast('error', `Download failed: ${finished.error || 'unknown error'}`)
            return
          }
          const source = (finished as unknown as { analysis?: SourceInfo }).analysis
          await refreshSources()
          if (source?.id) await selectSource(source.id)
          setIngestPath('')
          setJob(null)
          pushToast('ok', `Ingested ${source?.name ?? 'the video'}`)
          return
        }
        setJob(null)
        const source = await api.ingest(path)
        await refreshSources()
        await selectSource(source.id)
        setIngestPath('')
        pushToast('ok', `Ingested ${source.name}`)
      } catch (error) {
        pushToast('error', `Ingest failed: ${(error as Error).message}`)
      } finally {
        setIngesting(false)
      }
    },
    [ingestPath, refreshSources, selectSource, pushToast],
  )

  const handleDemo = useCallback(async () => {
    setIngesting(true)
    try {
      pushToast('info', 'Building a demo stream…')
      setJob(null)
      const source = await api.createDemo()
      await refreshSources()
      await selectSource(source.id)
      pushToast('ok', 'Demo stream ready — press Analyze')
    } catch (error) {
      pushToast('error', `Demo failed: ${(error as Error).message}`)
    } finally {
      setIngesting(false)
    }
  }, [refreshSources, selectSource, pushToast])

  const handleVerdict = useCallback(
    async (clipId: string, verdict: Verdict, reason = '') => {
      if (!selectedSourceId) return
      if (verdict === 'reject' && reason === '') {
        setRejecting(clipId)
        return
      }
      setRejecting(null)
      const previous = verdicts[clipId]
      setVerdicts((current) => {
        const next = { ...current }
        if (verdict === 'undo') delete next[clipId]
        else next[clipId] = verdict
        return next
      })
      if (verdict === 'undo') return
      try {
        const result = await api.decide(selectedSourceId, clipId, verdict, reason)
        setLearn(result.state)
      } catch (error) {
        setVerdicts((current) => {
          const next = { ...current }
          if (previous) next[clipId] = previous
          else delete next[clipId]
          return next
        })
        pushToast('error', `Feedback not saved: ${(error as Error).message}`)
      }
    },
    [selectedSourceId, verdicts, pushToast],
  )

  const handleHookSaved = useCallback(
    (clipId: string, hook: string) => {
      setAnalysis((current) => {
        if (!current) return current
        return {
          ...current,
          candidates: current.candidates.map((clip) =>
            clip.id === clipId && clip.llm ? { ...clip, llm: { ...clip.llm, hook } } : clip,
          ),
        }
      })
      void refreshLearn()
    },
    [refreshLearn],
  )

  const handleClipUpdated = useCallback((updated: Clip) => {
    setAnalysis((current) => {
      if (!current) return current
      return {
        ...current,
        candidates: current.candidates.map((clip) => (clip.id === updated.id ? updated : clip)),
      }
    })
  }, [])

  const seekClip = useCallback((seconds: number) => {
    setSeekRequest({ seconds, nonce: Date.now() })
    setPlayhead(seconds)
  }, [])

  const openClip = useCallback(
    (clip: Clip) => {
      selectClip(clip.id)
      setLayout((current) => ({ ...current, centreTab: 'monitor' }))
    },
    [selectClip, setLayout],
  )

  const requestRender = useCallback(
    (target?: Clip | null) => {
      const clip = target ?? selectedClip
      if (!clip) {
        pushToast('info', 'Select a clip before rendering.')
        return
      }
      setSelectedClipId(clip.id)
      setLayout((current) => ({ ...current, rightOpen: true, inspectorTab: 'output' }))
      setRenderRequest({ clipId: clip.id, nonce: Date.now() })
      pushToast('info', `Rendering clip ${clip.rank ? String(clip.rank).padStart(2, '0') : ''}…`)
    },
    [selectedClip, setLayout, pushToast],
  )

  const copyText = useCallback(
    async (text: string, label: string) => {
      if (!text) {
        pushToast('info', `Nothing to copy for ${label.toLowerCase()}.`)
        return
      }
      try {
        await navigator.clipboard.writeText(text)
        pushToast('ok', `${label} copied.`)
      } catch (error) {
        pushToast('error', `Could not copy: ${(error as Error).message}`)
      }
    },
    [pushToast],
  )

  const focusField = useCallback(
    (field: 'ingest' | 'source-search' | 'clip-search') => {
      if (field === 'clip-search') {
        setLayout((current) => ({ ...current, centreTab: 'reel' }))
      } else {
        setLayout((current) => ({ ...current, leftOpen: true, projectTab: 'project' }))
      }
      window.setTimeout(() => {
        const node = document.querySelector<HTMLInputElement>(`[data-field="${field}"]`)
        node?.scrollIntoView({ block: 'nearest' })
        node?.focus()
        node?.select()
      }, 110)
    },
    [setLayout],
  )

  const applyWorkspace = useCallback(
    (name: WorkspacePreset) => {
      const preset = WORKSPACE_PRESETS[name]
      setLayout((current) => ({
        ...current,
        ...preset,
        workspace: name,
        ...(compact ? { leftOpen: false, rightOpen: false } : null),
      }))
      const label = WORKSPACES.find((item) => item.id === name)?.label ?? name
      pushToast('info', `${label} workspace.`)
    },
    [compact, setLayout, pushToast],
  )

  const openSetup = useCallback(async () => {
    setSetupOpen(true)
    setHardwareError(null)
    try {
      setHardware(await api.hardware())
    } catch (error) {
      setHardwareError(`Hardware probe failed: ${(error as Error).message}`)
    }
  }, [])

  const exportBundle = useCallback(() => {
    if (!selectedSourceId) return
    const anchor = document.createElement('a')
    anchor.href = `/api/sources/${selectedSourceId}/export?format=bundle`
    anchor.download = ''
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    pushToast('info', 'Building the handoff bundle…')
  }, [selectedSourceId, pushToast])

  const counts = useMemo(
    () => ({
      all: clips.length,
      approved: clips.filter((clip) => verdicts[clip.id] === 'approve').length,
      rejected: clips.filter((clip) => verdicts[clip.id] === 'reject').length,
      pending: clips.filter((clip) => !verdicts[clip.id]).length,
    }),
    [clips, verdicts],
  )

  const visibleClips = useMemo(() => {
    const needle = layout.clipQuery?.toLowerCase() ?? ''
    return clips
      .filter((clip) => {
        if (layout.clipFilter === 'approved' && verdicts[clip.id] !== 'approve') return false
        if (layout.clipFilter === 'rejected' && verdicts[clip.id] !== 'reject') return false
        if (layout.clipFilter === 'pending' && verdicts[clip.id]) return false
        return true
      })
      .filter((clip) => {
        if (!needle.trim()) return true
        const haystack = `${clip.llm?.hook ?? ''} ${clip.text} ${clip.llm?.reason ?? ''}`.toLowerCase()
        return haystack.includes(needle.trim())
      })
      .sort((a, b) => {
        if (layout.clipSort === 'score') return b.final - a.final
        if (layout.clipSort === 'duration') return b.end - b.start - (a.end - a.start)
        return (a.rank ?? 99) - (b.rank ?? 99)
      })
  }, [clips, layout.clipFilter, layout.clipSort, layout.clipQuery, verdicts])

  const stepClip = useCallback(
    (direction: 1 | -1) => {
      if (!visibleClips.length) return
      const current = visibleClips.findIndex((clip) => clip.id === selectedClip?.id)
      const next =
        current === -1
          ? visibleClips[direction === 1 ? 0 : visibleClips.length - 1]
          : visibleClips[clamp(current + direction, 0, visibleClips.length - 1)]
      if (next) selectClip(next.id)
    },
    [visibleClips, selectedClip, selectClip],
  )

  const commands = useMemo<Record<string, AppCommand>>(() => {
    const list: AppCommand[] = [
      { id: 'file.import', label: 'Import source…', group: 'File', icon: 'upload', keywords: 'add ingest file path', run: () => focusField('ingest') },
      { id: 'file.demo', label: 'Generate demo stream', group: 'File', icon: 'sparkles', keywords: 'sample test', run: () => void handleDemo() },
      {
        id: 'file.fetchChat',
        label: 'Fetch chat replay',
        group: 'File',
        icon: 'activity',
        keywords: 'twitch messages audience',
        disabled: !selectedSourceId || !chat?.twitch_vod || chat.available || labeling,
        run: () => void fetchChat(),
      },
      {
        id: 'file.exportBundle',
        label: 'Export bundled project',
        group: 'File',
        icon: 'download',
        keywords: 'zip premiere resolve handoff',
        disabled: !selectedSourceId,
        run: exportBundle,
      },
      { id: 'file.setup', label: 'Hardware & models…', group: 'File', icon: 'sliders', keywords: 'setup gpu whisper', run: () => void openSetup() },

      { id: 'edit.searchSources', label: 'Search sources', group: 'Edit', icon: 'search', shortcut: 'Ctrl F', keywords: 'project bin filter', run: () => focusField('source-search') },
      { id: 'edit.searchClips', label: 'Search clips', group: 'Edit', icon: 'search', shortcut: 'Ctrl Shift F', keywords: 'reel filter', run: () => focusField('clip-search') },
      {
        id: 'edit.copyHook',
        label: 'Copy hook',
        group: 'Edit',
        icon: 'copy',
        disabled: !selectedClip?.llm?.hook,
        run: () => void copyText(selectedClip?.llm?.hook ?? '', 'Hook'),
      },
      {
        id: 'edit.copyTimecode',
        label: 'Copy timecode',
        group: 'Edit',
        icon: 'clock',
        disabled: !selectedClip,
        run: () =>
          void copyText(
            selectedClip
              ? `${formatTimecode(selectedClip.start, fps)} → ${formatTimecode(selectedClip.end, fps)}`
              : '',
            'Timecode',
          ),
      },
      {
        id: 'edit.copyTranscript',
        label: 'Copy transcript',
        group: 'Edit',
        icon: 'copy',
        disabled: !selectedClip?.text,
        run: () => void copyText(selectedClip?.text ?? '', 'Transcript'),
      },
      { id: 'edit.resetWorkspace', label: 'Reset workspace layout', group: 'Edit', icon: 'refresh', danger: true, run: () => { setLayout({ ...DEFAULT_LAYOUT, floatRect: defaultFloatRect() }); pushToast('ok', 'Workspace reset.') } },

      { id: 'view.palette', label: 'Command palette', group: 'View', icon: 'command', shortcut: 'Ctrl K', run: () => setPaletteOpen(true) },
      { id: 'view.themes', label: 'Theme atelier…', group: 'View', icon: 'palette', keywords: 'appearance color palette dark light marketplace studio', run: () => setThemesOpen(true) },
      { id: 'view.toggleProject', label: 'Project panel', group: 'View', icon: 'panel-left', shortcut: 'Ctrl B', checked: layout.leftOpen, run: () => setLayout((current) => ({ ...current, leftOpen: !current.leftOpen })) },
      { id: 'view.toggleInspector', label: 'Inspector', group: 'View', icon: 'panel-right', shortcut: 'Ctrl Shift B', checked: layout.rightOpen, run: () => setLayout((current) => ({ ...current, rightOpen: !current.rightOpen })) },
      { id: 'view.floatInspector', label: 'Float inspector', group: 'View', icon: 'grip', checked: layout.inspectorFloating, disabled: !layout.rightOpen, run: () => setLayout((current) => ({ ...current, inspectorFloating: !current.inspectorFloating })) },
      { id: 'view.reel', label: 'Reel tab', group: 'View', icon: 'film', shortcut: '1', checked: layout.centreTab === 'reel', run: () => setLayout((current) => ({ ...current, centreTab: 'reel' })) },
      { id: 'view.monitor', label: 'Monitor tab', group: 'View', icon: 'monitor', shortcut: '2', checked: layout.centreTab === 'monitor', run: () => setLayout((current) => ({ ...current, centreTab: 'monitor' })) },
      { id: 'view.timeline', label: 'Timeline tab', group: 'View', icon: 'timeline', shortcut: '3', checked: layout.centreTab === 'timeline', run: () => setLayout((current) => ({ ...current, centreTab: 'timeline' })) },
      { id: 'view.inspectorProperties', label: 'Inspector — Properties', group: 'View', checked: layout.inspectorTab === 'properties', run: () => setLayout((current) => ({ ...current, rightOpen: true, inspectorTab: 'properties' })) },
      { id: 'view.inspectorCaptions', label: 'Inspector — Captions', group: 'View', checked: layout.inspectorTab === 'captions', run: () => setLayout((current) => ({ ...current, rightOpen: true, inspectorTab: 'captions' })) },
      { id: 'view.inspectorOutput', label: 'Inspector — Output', group: 'View', checked: layout.inspectorTab === 'output', run: () => setLayout((current) => ({ ...current, rightOpen: true, inspectorTab: 'output' })) },

      { id: 'clip.analyze', label: analysis ? 'Re-analyze source' : 'Analyze source', group: 'Clip', icon: 'sparkles', disabled: !selectedSourceId || labeling, run: () => void runAnalyze(Boolean(analysis)) },
      {
        id: 'clip.approve',
        label: selectedClip && verdicts[selectedClip.id] === 'approve' ? 'Undo approval' : 'Approve clip',
        group: 'Clip',
        icon: 'check',
        shortcut: 'A',
        checked: Boolean(selectedClip && verdicts[selectedClip.id] === 'approve'),
        disabled: !selectedClip,
        run: () => selectedClip && void handleVerdict(selectedClip.id, verdicts[selectedClip.id] === 'approve' ? 'undo' : 'approve'),
      },
      {
        id: 'clip.reject',
        label: selectedClip && verdicts[selectedClip.id] === 'reject' ? 'Undo rejection' : 'Reject clip',
        group: 'Clip',
        icon: 'x',
        shortcut: 'X',
        danger: true,
        checked: Boolean(selectedClip && verdicts[selectedClip.id] === 'reject'),
        disabled: !selectedClip,
        run: () => selectedClip && void handleVerdict(selectedClip.id, verdicts[selectedClip.id] === 'reject' ? 'undo' : 'reject'),
      },
      { id: 'clip.render', label: 'Render clip', group: 'Clip', icon: 'download', shortcut: 'R', disabled: !selectedClip, run: () => requestRender() },
      { id: 'clip.next', label: 'Next clip', group: 'Clip', icon: 'chevron-down', shortcut: 'J', disabled: visibleClips.length < 2, run: () => stepClip(1) },
      { id: 'clip.previous', label: 'Previous clip', group: 'Clip', icon: 'chevron-up', shortcut: 'K', disabled: visibleClips.length < 2, run: () => stepClip(-1) },

      { id: 'workspace.triage', label: 'Triage workspace', group: 'Workspace', checked: layout.workspace === 'triage', run: () => applyWorkspace('triage') },
      { id: 'workspace.editing', label: 'Editing workspace', group: 'Workspace', checked: layout.workspace === 'editing', run: () => applyWorkspace('editing') },
      { id: 'workspace.review', label: 'Review workspace', group: 'Workspace', checked: layout.workspace === 'review', run: () => applyWorkspace('review') },

      { id: 'help.shortcuts', label: 'Keyboard shortcuts', group: 'Help', icon: 'keyboard', shortcut: '?', run: () => setShortcutsOpen(true) },
      { id: 'help.setup', label: 'Hardware & models', group: 'Help', icon: 'sliders', run: () => void openSetup() },
      { id: 'help.about', label: 'About Clip Factory', group: 'Help', icon: 'info', run: () => setAboutOpen(true) },
    ]
    return Object.fromEntries(list.map((command) => [command.id, command]))
  }, [
    analysis,
    applyWorkspace,
    chat,
    copyText,
    exportBundle,
    fetchChat,
    focusField,
    fps,
    handleDemo,
    handleVerdict,
    labeling,
    layout.centreTab,
    layout.inspectorFloating,
    layout.inspectorTab,
    layout.leftOpen,
    layout.rightOpen,
    layout.workspace,
    openSetup,
    pushToast,
    requestRender,
    runAnalyze,
    selectedClip,
    selectedSourceId,
    setLayout,
    stepClip,
    verdicts,
    visibleClips.length,
  ])

  const openSourceMenu = useCallback(
    (source: SourceRow, position: { x: number; y: number }) => {
      const items: Array<AppCommand | null> = [
        {
          id: 'ctx.source.open',
          label: 'Open source',
          group: 'Source',
          run: () => void selectSource(source.id),
        },
        {
          id: 'ctx.source.analyze',
          label: source.analyzed ? 'Re-analyze source' : 'Analyze source',
          group: 'Source',
          disabled: labeling,
          run: () => {
            void (async () => {
              await selectSource(source.id)
              await runAnalyze(source.analyzed, source.id)
            })()
          },
        },
        source.id === selectedSourceId && chat?.twitch_vod && !chat.available
          ? {
              id: 'ctx.source.chat',
              label: 'Fetch chat replay',
              group: 'Source',
              disabled: labeling,
              run: () => void fetchChat(source.id),
            }
          : null,
        null,
        {
          id: 'ctx.source.copyPath',
          label: 'Copy source path',
          group: 'Source',
          run: () => void copyText(source.path, 'Source path'),
        },
        {
          id: 'ctx.source.copyMedia',
          label: 'Copy media URL',
          group: 'Source',
          run: () => void copyText(api.mediaUrl(source.id), 'Media URL'),
        },
        {
          id: 'ctx.source.reveal',
          label: 'Open preview in browser',
          group: 'Source',
          run: () => window.open(api.mediaUrl(source.id), '_blank', 'noopener,noreferrer'),
        },
      ]
      setContextMenu({ x: position.x, y: position.y, label: `${source.name} actions`, items })
    },
    [chat, copyText, fetchChat, labeling, runAnalyze, selectSource, selectedSourceId],
  )

  const openClipMenu = useCallback(
    (clip: Clip, position: { x: number; y: number }) => {
      const current = verdicts[clip.id]
      const items: Array<AppCommand | null> = [
        {
          id: 'ctx.clip.play',
          label: 'Open in monitor',
          group: 'Clip',
          run: () => openClip(clip),
        },
        null,
        {
          id: 'ctx.clip.approve',
          label: current === 'approve' ? 'Undo approval' : 'Approve clip',
          group: 'Clip',
          checked: current === 'approve',
          run: () => void handleVerdict(clip.id, current === 'approve' ? 'undo' : 'approve'),
        },
        {
          id: 'ctx.clip.reject',
          label: current === 'reject' ? 'Undo rejection' : 'Reject clip…',
          group: 'Clip',
          checked: current === 'reject',
          danger: true,
          run: () => void handleVerdict(clip.id, current === 'reject' ? 'undo' : 'reject'),
        },
        {
          id: 'ctx.clip.render',
          label: 'Render clip',
          group: 'Clip',
          run: () => requestRender(clip),
        },
        null,
        {
          id: 'ctx.clip.copyHook',
          label: 'Copy hook',
          group: 'Clip',
          disabled: !clip.llm?.hook,
          run: () => void copyText(clip.llm?.hook ?? '', 'Hook'),
        },
        {
          id: 'ctx.clip.copyTimecode',
          label: 'Copy timecode',
          group: 'Clip',
          run: () =>
            void copyText(
              `${formatTimecode(clip.start, fps)} → ${formatTimecode(clip.end, fps)}`,
              'Timecode',
            ),
        },
        {
          id: 'ctx.clip.copyTranscript',
          label: 'Copy transcript',
          group: 'Clip',
          run: () => void copyText(clip.text, 'Transcript'),
        },
      ]
      setContextMenu({ x: position.x, y: position.y, label: `Clip ${clip.rank ?? ''} actions`, items })
    },
    [copyText, fps, handleVerdict, openClip, requestRender, verdicts],
  )

  // Global keyboard map. Fields, modals and open menus own their own keys.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const inField = Boolean(target?.closest('input, textarea, select, [contenteditable="true"]'))
      const mod = event.ctrlKey || event.metaKey

      if (themesOpen) return

      if (mod && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      if (paletteOpen || shortcutsOpen || aboutOpen || setupOpen) return

      if (mod && !event.shiftKey && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        setLayout((current) => ({ ...current, leftOpen: !current.leftOpen }))
        return
      }
      if (mod && event.shiftKey && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        setLayout((current) => ({ ...current, rightOpen: !current.rightOpen }))
        return
      }
      if (inField) return
      if (event.altKey) return
      if (event.repeat && !['j', 'k', 'ArrowDown', 'ArrowUp'].includes(event.key)) return

      if (event.key === 'Escape') {
        setRejecting(null)
        if (compact) setLayout((current) => ({ ...current, leftOpen: false, rightOpen: false }))
        return
      }
      if (event.key === '?' || (event.shiftKey && event.key === '/')) {
        event.preventDefault()
        setShortcutsOpen(true)
        return
      }
      if (event.key === '1') {
        setLayout((current) => ({ ...current, centreTab: 'reel' }))
        return
      }
      if (event.key === '2') {
        setLayout((current) => ({ ...current, centreTab: 'monitor' }))
        return
      }
      if (event.key === '3') {
        setLayout((current) => ({ ...current, centreTab: 'timeline' }))
        return
      }
      if (event.key === 'j' || event.key === 'ArrowDown') {
        event.preventDefault()
        stepClip(1)
        return
      }
      if (event.key === 'k' || event.key === 'ArrowUp') {
        event.preventDefault()
        stepClip(-1)
        return
      }
      if (!selectedClip) return
      if (event.key === 'a') {
        event.preventDefault()
        void handleVerdict(selectedClip.id, verdicts[selectedClip.id] === 'approve' ? 'undo' : 'approve')
        return
      }
      if (event.key === 'x') {
        event.preventDefault()
        void handleVerdict(selectedClip.id, verdicts[selectedClip.id] === 'reject' ? 'undo' : 'reject')
        return
      }
      if (event.key === 'r') {
        event.preventDefault()
        requestRender()
        return
      }
      if (event.key === 'l') {
        event.preventDefault()
        setLayout((current) => ({ ...current, monitorLoop: !current.monitorLoop }))
        return
      }
      if (event.code === 'Space') {
        event.preventDefault()
        if (layout.centreTab !== 'monitor') {
          setLayout((current) => ({ ...current, centreTab: 'monitor' }))
          window.setTimeout(() => monitorRef.current?.play(), 120)
        } else {
          monitorRef.current?.togglePlay()
        }
        return
      }
      if (layout.centreTab !== 'monitor') return
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault()
        monitorRef.current?.nudge((event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 5 : 1))
        return
      }
      if (event.key === ',' || event.key === '.') {
        event.preventDefault()
        monitorRef.current?.step(event.key === '.' ? 1 : -1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    aboutOpen,
    compact,
    handleVerdict,
    layout.centreTab,
    paletteOpen,
    requestRender,
    selectedClip,
    setLayout,
    setupOpen,
    shortcutsOpen,
    stepClip,
    themesOpen,
    verdicts,
  ])

  const closeContext = useCallback(() => setContextMenu(null), [])
  const onRunCommand = useCallback((command: AppCommand) => command.run(), [])

  const showLeft = !compact && layout.leftOpen
  const showRightDocked = !compact && layout.rightOpen && !layout.inspectorFloating
  const columns = [
    showLeft ? `${layout.leftWidth}px` : null,
    showLeft ? '5px' : null,
    'minmax(0, 1fr)',
    showRightDocked ? '5px' : null,
    showRightDocked ? `${layout.rightWidth}px` : null,
  ]
    .filter(Boolean)
    .join(' ')

  const rejectingClip = clips.find((clip) => clip.id === rejecting) ?? null

  const statusLabel = ingesting
    ? 'Ingesting'
    : busy
      ? job?.stage || 'Working'
      : job?.status === 'error'
        ? 'Job failed'
        : selectedSourceId
          ? 'Ready'
          : 'No source'
  const statusDetail = ingesting
    ? 'reading the source'
    : busy
      ? job?.detail || `${Math.round((job?.pct ?? 0) * 100)}%`
      : job?.status === 'error'
        ? job?.error
        : undefined

  const inspectorProps = {
    sourceId: selectedSourceId ?? '',
    clip: selectedClip,
    captions,
    captionsLoading,
    verdict: selectedClip ? verdicts[selectedClip.id] : undefined,
    playhead,
    fps,
    tab: layout.inspectorTab,
    clipCount: clips.length,
    hasSource: Boolean(selectedSourceId),
    renderRequest,
    onTab: (tab: InspectorTab) => setLayout((current) => ({ ...current, inspectorTab: tab })),
    onVerdict: (verdict: Verdict) => {
      if (selectedClip) void handleVerdict(selectedClip.id, verdict)
    },
    onSeek: seekClip,
    onHookSaved: handleHookSaved,
    onClipUpdated: handleClipUpdated,
    onNotify: pushToast,
  }

  return (
    <div className="app-shell" data-compact={compact ? 'true' : undefined}>
      <MenuBar
        menus={MENUS}
        commands={commands}
        onRun={onRunCommand}
        onOpenPalette={() => setPaletteOpen(true)}
        onOpenShortcuts={() => setShortcutsOpen(true)}
      />

      <header className="app-toolbar">
        <div className="workspace-switch" role="group" aria-label="Workspace">
          {WORKSPACES.map((workspace) => (
            <button
              type="button"
              key={workspace.id}
              className="workspace-button"
              data-active={layout.workspace === workspace.id ? 'true' : undefined}
              aria-label={workspace.label}
              aria-pressed={layout.workspace === workspace.id}
              title={workspace.hint}
              onClick={() => applyWorkspace(workspace.id)}
            >
              <Icon name={workspace.icon} size={14} />
              <span>{workspace.label}</span>
            </button>
          ))}
        </div>

        <span className="toolbar-divider" aria-hidden="true" />

        <div className="source-heading">
          <span className="source-heading-name" title={selectedSource?.name ?? 'No source'}>
            {selectedSource?.name ?? 'No source'}
          </span>
          {selectedSource ? (
            <span className="source-heading-meta num">
              {formatTime(selectedSource.duration)}
              <span aria-hidden="true"> · </span>
              {selectedSource.width}×{selectedSource.height}
              <span aria-hidden="true"> · </span>
              {selectedSource.fps ? `${selectedSource.fps.toFixed(2)} fps` : 'fps —'}
            </span>
          ) : (
            <span className="source-heading-meta">Nothing loaded</span>
          )}
        </div>

        <span className="toolbar-spacer" />

        {compact ? (
          <div className="compact-toggles" role="group" aria-label="Panel visibility">
            <IconButton
              icon="panel-left"
              size="sm"
              label="Project panel"
              active={layout.leftOpen}
              onClick={() =>
                setLayout((current) => ({
                  ...current,
                  leftOpen: !current.leftOpen,
                  rightOpen: false,
                }))
              }
            />
            <IconButton
              icon="panel-right"
              size="sm"
              label="Inspector"
              active={layout.rightOpen}
              onClick={() =>
                setLayout((current) => ({
                  ...current,
                  rightOpen: !current.rightOpen,
                  leftOpen: false,
                }))
              }
            />
          </div>
        ) : null}

        {analysis ? (
          <div className="engine-pills" aria-label="Active engines">
            <span className="pill" title={`ASR: ${analysis.asr_backend || 'none'}`}>
              ASR <b>{analysis.asr_backend || '—'}</b>
            </span>
            <span className="pill" title={`Scorer: ${analysis.llm_backend || 'none'}`}>
              LLM <b>{analysis.llm_backend || '—'}</b>
            </span>
            {chat?.available ? (
              <span className="pill" title={`${chat.messages.toLocaleString()} messages`}>
                chat <b className="num">{chat.messages.toLocaleString()}</b>
              </span>
            ) : null}
          </div>
        ) : null}

        {selectedSourceId && chat?.twitch_vod && !chat.available ? (
          <button type="button" className="btn sm ghost chat-fetch" disabled={labeling} onClick={() => void fetchChat()}>
            <Icon name="activity" size={13} />
            Fetch chat
          </button>
        ) : null}

        <button
          type="button"
          className="btn sm primary analyze-button"
          disabled={!selectedSourceId || labeling}
          onClick={() => void runAnalyze(Boolean(analysis))}
        >
          <Icon name="sparkles" size={13} />
          {analysis ? 'Re-analyze' : 'Analyze'}
        </button>

        <IconButton
          icon="download"
          size="sm"
          className="toolbar-aux"
          label="Export bundle"
          disabled={!selectedSourceId}
          onClick={exportBundle}
        />
        <IconButton
          icon="sliders"
          size="sm"
          className="toolbar-aux"
          label="Hardware and models"
          onClick={() => void openSetup()}
        />
      </header>

      {job ? (
        <div className="jobbar" data-status={job.status} role="status" aria-live="polite">
          <div className="job-phases">
            {shownPhases.map((phase) => (
              <span className="phase" key={phase.id} data-state={phases[phase.id] ?? 'idle'}>
                <span className="tick" />
                {phase.label}
              </span>
            ))}
          </div>
          <span className="job-detail">
            {job.status === 'error' ? job.error : `${job.detail || job.stage}`}
          </span>
          <span className="job-pct num">{Math.round(job.pct * 100)}%</span>
          <IconButton icon="x" size="sm" label="Dismiss job status" onClick={() => setJob(null)} />
          <span className="job-track" aria-hidden="true">
            <i style={{ width: `${Math.round(job.pct * 100)}%` }} />
          </span>
        </div>
      ) : null}

      {rejectingClip ? (
        <div className="reject-bar" role="group" aria-label="Choose a rejection reason">
          <span className="reject-lead">
            <Icon name="flag" size={13} />
            Reject clip {rejectingClip.rank ? String(rejectingClip.rank).padStart(2, '0') : ''} — why?
          </span>
          <div className="reject-reasons">
            {REJECT_REASONS.map((reason) => (
              <button
                type="button"
                className="reason-chip"
                key={reason}
                onClick={() => void handleVerdict(rejectingClip.id, 'reject', reason)}
              >
                {reason}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="btn sm ghost"
            onClick={() => void handleVerdict(rejectingClip.id, 'reject', 'unspecified')}
          >
            Skip
          </button>
          <IconButton icon="x" size="sm" label="Cancel rejection" onClick={() => setRejecting(null)} />
        </div>
      ) : null}

      <div className="workspace" style={{ gridTemplateColumns: columns }}>
        {showLeft ? (
          <>
            <ProjectPanel
              sources={sources}
              selectedId={selectedSourceId}
              learn={learn}
              analysis={analysis}
              busy={labeling}
              compact={false}
              tab={layout.projectTab}
              ingestPath={ingestPath}
              onTab={(tab) => setLayout((current) => ({ ...current, projectTab: tab }))}
              onSelect={(source) => void selectSource(source.id)}
              onIngestPath={setIngestPath}
              onIngest={() => void handleIngest()}
              onDemo={() => void handleDemo()}
              onRefreshLearn={refreshLearn}
              onOpenSetup={() => void openSetup()}
              onSourceMenu={openSourceMenu}
              onCollapse={() => setLayout((current) => ({ ...current, leftOpen: false }))}
            />
            <Resizer
              side="left"
              value={layout.leftWidth}
              min={220}
              max={420}
              onChange={(value) => setLayout((current) => ({ ...current, leftWidth: value }))}
              onReset={() => setLayout((current) => ({ ...current, leftWidth: 264 }))}
              label="Resize project panel"
              controls="project-panel"
            />
          </>
        ) : null}

        <main className="centre-pane" aria-label="Workspace">
          <Tabs
            idPrefix="centre"
            variant="workspace"
            ariaLabel="Working area"
            value={layout.centreTab}
            onChange={(id) => setLayout((current) => ({ ...current, centreTab: id as CentreTab }))}
            items={[
              { id: 'reel', label: 'Reel', icon: 'film', badge: clips.length || undefined },
              { id: 'monitor', label: 'Monitor', icon: 'monitor', title: 'Source monitor (2)' },
              { id: 'timeline', label: 'Timeline', icon: 'timeline', title: 'Timeline (3)' },
            ]}
          />

          <div
            className="centre-panel"
            id={`centre-panel-${layout.centreTab}`}
            role="tabpanel"
            aria-labelledby={`centre-tab-${layout.centreTab}`}
          >
            {layout.centreTab === 'reel' ? (
              <Reel
                clips={visibleClips}
                counts={counts}
                mediaSrc={mediaSrc ?? ''}
                selectedId={selectedClip?.id ?? null}
                verdicts={verdicts}
                filter={layout.clipFilter}
                sort={layout.clipSort}
                view={layout.clipView}
                query={layout.clipQuery ?? ''}
                hasSource={Boolean(selectedSourceId)}
                analysis={analysis}
                busy={labeling}
                onFilter={(filter) => setLayout((current) => ({ ...current, clipFilter: filter }))}
                onSort={(sort) => setLayout((current) => ({ ...current, clipSort: sort }))}
                onView={(view) => setLayout((current) => ({ ...current, clipView: view }))}
                onQuery={(query) => setLayout((current) => ({ ...current, clipQuery: query }))}
                onSelect={selectClip}
                onOpen={openClip}
                onVerdict={(clipId, verdict) => void handleVerdict(clipId, verdict)}
                onMenu={openClipMenu}
                onAnalyze={() => void runAnalyze(Boolean(analysis))}
                onDemo={() => void handleDemo()}
                onImport={() => focusField('ingest')}
              />
            ) : layout.centreTab === 'monitor' ? (
              <Monitor
                ref={monitorRef}
                clip={selectedClip}
                mediaSrc={mediaSrc}
                sourceName={selectedSource?.name ?? 'No source'}
                sourceDuration={duration}
                fps={fps}
                captions={captions}
                captionsLoading={captionsLoading}
                seekRequest={seekRequest}
                overlay={layout.monitorOverlay}
                loop={layout.monitorLoop}
                guides={layout.monitorGuides}
                verdict={selectedClip ? verdicts[selectedClip.id] : undefined}
                onOverlay={(overlay) => setLayout((current) => ({ ...current, monitorOverlay: overlay }))}
                onLoop={(loop) => setLayout((current) => ({ ...current, monitorLoop: loop }))}
                onGuides={(guides) => setLayout((current) => ({ ...current, monitorGuides: guides }))}
                onTime={setPlayhead}
                onVerdict={(verdict) => {
                  if (selectedClip) void handleVerdict(selectedClip.id, verdict)
                }}
                onOpenOutput={() => setLayout((current) => ({ ...current, rightOpen: true, inspectorTab: 'output' }))}
                onNotify={pushToast}
              />
            ) : (
              <Timeline
                clips={clips}
                selectedId={selectedClip?.id ?? null}
                peaks={peaks}
                duration={duration}
                playhead={playhead}
                fps={fps}
                verdicts={verdicts}
                hasSource={Boolean(selectedSourceId)}
                onSeek={seekClip}
                onSelect={selectClip}
                onOpenMonitor={() => setLayout((current) => ({ ...current, centreTab: 'monitor' }))}
                themeId={theme.activeTheme.id}
              />
            )}
          </div>
        </main>

        {showRightDocked ? (
          <Resizer
            side="right"
            value={layout.rightWidth}
            min={340}
            max={560}
            onChange={(value) => setLayout((current) => ({ ...current, rightWidth: value }))}
            onReset={() => setLayout((current) => ({ ...current, rightWidth: 400 }))}
            label="Resize inspector"
            controls="inspector"
          />
        ) : null}

        {!compact ? (
          <div className="inspector-slot" data-floating={layout.inspectorFloating ? 'true' : undefined} hidden={!layout.rightOpen}>
            <InspectorFrame
              floating={layout.inspectorFloating}
              rect={layout.floatRect}
              onRect={(rect) => setLayout((current) => ({ ...current, floatRect: rect }))}
              onDock={() => setLayout((current) => ({ ...current, inspectorFloating: false }))}
            >
              <Inspector
                {...inspectorProps}
                onFloat={
                  layout.inspectorFloating
                    ? undefined
                    : () => setLayout((current) => ({ ...current, inspectorFloating: true }))
                }
              />
            </InspectorFrame>
          </div>
        ) : null}
      </div>

      {compact && layout.leftOpen ? (
        <>
          <button type="button" className="drawer-scrim" aria-label="Close project panel" onClick={() => setLayout((current) => ({ ...current, leftOpen: false }))} />
          <div className="drawer drawer-left" role="dialog" aria-modal="true" aria-label="Project panel">
            <ProjectPanel
              sources={sources}
              selectedId={selectedSourceId}
              learn={learn}
              analysis={analysis}
              busy={labeling}
              compact
              tab={layout.projectTab}
              ingestPath={ingestPath}
              onTab={(tab) => setLayout((current) => ({ ...current, projectTab: tab }))}
              onSelect={(source) => void selectSource(source.id)}
              onIngestPath={setIngestPath}
              onIngest={() => void handleIngest()}
              onDemo={() => void handleDemo()}
              onRefreshLearn={refreshLearn}
              onOpenSetup={() => void openSetup()}
              onSourceMenu={openSourceMenu}
              onCollapse={() => setLayout((current) => ({ ...current, leftOpen: false }))}
            />
          </div>
        </>
      ) : null}

      {compact && layout.rightOpen ? (
        <>
          <button type="button" className="drawer-scrim" aria-label="Close inspector" onClick={() => setLayout((current) => ({ ...current, rightOpen: false }))} />
          <div className="drawer drawer-right" role="dialog" aria-modal="true" aria-label="Inspector">
            <Inspector {...inspectorProps} />
          </div>
        </>
      ) : null}

      <StatusBar
        busy={busy || ingesting}
        statusLabel={statusLabel}
        statusDetail={statusDetail}
        progress={job && (job.status === 'running' || job.status === 'queued') ? job.pct * 100 : null}
        sourceName={selectedSource?.name ?? null}
        playhead={playhead}
        duration={duration}
        clipLabel={selectedClip ? `Clip ${selectedClip.rank ? String(selectedClip.rank).padStart(2, '0') : '—'}` : null}
        leftOpen={layout.leftOpen}
        rightOpen={layout.rightOpen}
        onToggleLeft={() => setLayout((current) => ({ ...current, leftOpen: !current.leftOpen }))}
        onToggleRight={() => setLayout((current) => ({ ...current, rightOpen: !current.rightOpen }))}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        workspaceLabel={WORKSPACES.find((item) => item.id === layout.workspace)?.label ?? 'Triage'}
        themeName={theme.activeTheme.name}
        themeSwatch={theme.activeTheme.seeds.canvas}
        onOpenThemes={() => setThemesOpen(true)}
      />

      {contextMenu ? (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          label={contextMenu.label}
          items={contextMenu.items}
          onRun={onRunCommand}
          onClose={closeContext}
        />
      ) : null}

      <CommandPalette
        open={paletteOpen}
        commands={Object.values(commands)}
        onRun={onRunCommand}
        onClose={() => setPaletteOpen(false)}
      />

      {themesOpen ? (
        <ThemeAtelier
          themes={theme.themes}
          activeId={theme.activeTheme.id}
          onClose={() => setThemesOpen(false)}
          onApply={theme.useThemeById}
          onSave={theme.saveCustom}
          onDelete={theme.deleteCustom}
          onToast={pushToast}
        />
      ) : null}

      {shortcutsOpen ? <ShortcutsDialog onClose={() => setShortcutsOpen(false)} /> : null}
      {aboutOpen ? (
        <AboutDialog
          version={version}
          onClose={() => setAboutOpen(false)}
          onOpenShortcuts={() => {
            setAboutOpen(false)
            setShortcutsOpen(true)
          }}
        />
      ) : null}
      {setupOpen ? (
        <SetupModal
          hardware={hardware}
          error={hardwareError}
          onClose={() => setSetupOpen(false)}
          onRefresh={() => void openSetup()}
        />
      ) : null}

      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div className="toast" key={toast.id} data-kind={toast.kind} role={toast.kind === 'error' ? 'alert' : 'status'}>
            <Icon name={toast.kind === 'error' ? 'alert' : toast.kind === 'ok' ? 'check' : 'info'} size={14} />
            <span>{toast.message}</span>
            <button
              type="button"
              className="toast-close"
              aria-label="Dismiss notification"
              onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
            >
              <Icon name="x" size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function firstCopy(analysis: Analysis): string {
  const first = analysis.candidates.find((clip) => clip.rank)
  return first ? `${analysis.candidates.filter((clip) => clip.rank).length} clips ready` : 'Analysis finished with no clips'
}

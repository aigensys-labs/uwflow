import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import {
  AlertCircle,
  ArrowDownToLine,
  Check,
  ChevronRight,
  CircleHelp,
  Code2,
  FolderPlus,
  GitBranch,
  GitCommitHorizontal,
  LoaderCircle,
  PackagePlus,
  LockKeyhole,
  Save,
  ShieldCheck,
  Settings2,
  Table2,
  Workflow,
  X,
} from 'lucide-react'
import { DmnEditor } from './components/DmnEditor'
import { RoutingEditor } from './components/RoutingEditor'
import { api, type Workspace } from './lib/api'
import {
  DEFAULT_STUDIO_PREFERENCES,
  STUDIO_THEMES,
  TEXT_SIZES,
  loadStudioPreferences,
  saveStudioPreferences,
  type StudioPreferences,
} from './lib/appearance'
import type {
  DevCandidate,
  DmnPolicy,
  LoadedPolicy,
  Policy,
  PreviewResult,
  Stage,
  StageCatalog,
  ValidationResult,
} from './lib/types'

function stageIcon(editor: Stage['editor']) {
  if (editor === 'dmn_table') return <Table2 size={16} />
  if (editor === 'routing_dag') return <Workflow size={16} />
  return <LockKeyhole size={16} />
}

function statusLabel(stage: Stage) {
  if (stage.status === 'editable') return 'Editable'
  if (stage.status === 'planned') return 'Planned'
  return 'Protected'
}

export default function App() {
  const [stages, setStages] = useState<Stage[]>([])
  const [activeStageId, setActiveStageId] = useState('stage_1_hard_gates')
  const [loaded, setLoaded] = useState<LoadedPolicy | null>(null)
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [catalog, setCatalog] = useState<StageCatalog | null>(null)
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [busy, setBusy] = useState<'load' | 'validate' | 'preview' | 'save' | 'candidate' | null>('load')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [stageLoadError, setStageLoadError] = useState<string | null>(null)
  const [apiStatus, setApiStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking')
  const [candidate, setCandidate] = useState<DevCandidate | null>(null)
  const [candidateOpen, setCandidateOpen] = useState(false)
  const [baselineRelease, setBaselineRelease] = useState('')
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspaceId, setWorkspaceId] = useState('')
  const [preferences, setPreferences] = useState<StudioPreferences>(loadStudioPreferences)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const activeStage = stages.find((stage) => stage.id === activeStageId) ?? null

  useEffect(() => {
    saveStudioPreferences(preferences)
  }, [preferences])

  useEffect(() => {
    if (!settingsOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSettingsOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [settingsOpen])
  const dirty = Boolean(policy && loaded && JSON.stringify(policy) !== JSON.stringify(loaded.spec))

  const loadStage = useCallback(async (stageId: string) => {
    setBusy('load')
    setError(null)
    setNotice(null)
    setValidation(null)
    setPreview(null)
    setPreviewOpen(false)
    setCandidate(null)
    setCandidateOpen(false)
    try {
      const [loadedPolicy, stageCatalog] = await Promise.all([api.policy(stageId, workspaceId), api.catalog(stageId)])
      setLoaded(loadedPolicy)
      setPolicy(loadedPolicy.spec)
      setCatalog(stageCatalog)
      setActiveStageId(stageId)
      setStageLoadError(null)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Unable to load policy.'
      setLoaded(null)
      setPolicy(null)
      setCatalog(null)
      setStageLoadError(message)
    } finally {
      setBusy(null)
    }
  }, [workspaceId])

  useEffect(() => {
    let active = true
    Promise.all([api.stages(), api.workspaces()])
      .then(([items, workspacePayload]) => {
        if (!active) return
        setApiStatus('connected')
        setStages(items)
        setWorkspaces(workspacePayload.items)
        setWorkspaceId(workspacePayload.default_workspace_id)
        const initialStage = items.find((stage) => stage.id === 'stage_1_hard_gates' && stage.editable)
          ?? items.find((stage) => stage.editable)
        if (initialStage) setActiveStageId(initialStage.id)
        else setBusy(null)
      })
      .catch((reason: Error) => {
        if (active) {
          setApiStatus('disconnected')
          setBusy(null)
          setError(reason.message)
        }
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (workspaceId && stages.length) void loadStage(activeStageId)
  }, [workspaceId, stages, loadStage, activeStageId])

  const selectStage = async (stage: Stage) => {
    if (stage.id !== activeStageId && dirty && !window.confirm('Discard unsaved policy changes and open another stage?')) return
    if (!stage.editable) {
      setActiveStageId(stage.id)
      setLoaded(null)
      setPolicy(null)
      setCatalog(null)
      setValidation(null)
      setPreview(null)
      setStageLoadError(null)
      setError(null)
      setNotice(null)
      return
    }
    await loadStage(stage.id)
  }

  const updatePolicy = (next: Policy) => {
    setPolicy(next)
    setValidation(null)
    setPreview(null)
    setCandidate(null)
    setError(null)
  }

  useEffect(() => {
    if (!policy) return
    let active = true
    const timeoutId = window.setTimeout(() => {
      api.validate(activeStageId, policy, workspaceId)
        .then((result) => {
          if (active) setValidation(result)
        })
        .catch((reason: Error) => {
          if (active) setValidation({ valid: false, errors: [reason.message] })
        })
    }, 450)
    return () => {
      active = false
      window.clearTimeout(timeoutId)
    }
  }, [activeStageId, policy])

  const validate = async () => {
    if (!policy) return
    setBusy('validate')
    setError(null)
    setNotice(null)
    try {
      const result = await api.validate(activeStageId, policy, workspaceId)
      setValidation(result)
      if (result.valid) setNotice('Policy is valid. Generated Python compiles successfully.')
      else setError(result.errors.join('\n'))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Validation failed.')
    } finally {
      setBusy(null)
    }
  }

  const openPreview = async () => {
    if (!policy) return
    setBusy('preview')
    setError(null)
    try {
      const result = await api.preview(activeStageId, policy, workspaceId)
      setPreview(result)
      setPreviewOpen(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Python preview failed.')
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    if (!policy || !loaded) return
    setBusy('save')
    setError(null)
    setNotice(null)
    try {
      const result = await api.save(activeStageId, policy, loaded.sha256, workspaceId)
      const nextLoaded: LoadedPolicy = { ...loaded, spec: policy, sha256: result.sha256 }
      setLoaded(nextLoaded)
      setNotice('Saved strategy to the selected workspace. Core source and production were not modified.')
      setValidation({ valid: true, errors: [], policy_sha256: result.sha256, generated_sha256: result.generated_sha256 })
      setPreview(null)
      setCandidate(null)
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Save failed.'
      setError(message)
    } finally {
      setBusy(null)
    }
  }

  const buildDevCandidate = async () => {
    if (!policy || dirty || validation?.valid !== true) return
    if (!/^\d+\.\d+\.\d+$/.test(baselineRelease.trim())) {
      setError('Enter the exact MAJOR.MINOR.PATCH runtime release currently deployed in PROD. Verify it in Kestra first.')
      return
    }
    setBusy('candidate')
    setError(null)
    setNotice(null)
    try {
      const result = await api.buildDevCandidate(baselineRelease.trim(), workspaceId)
      setCandidate(result)
      setCandidateOpen(true)
      setNotice(`Built immutable DEV candidate ${result.candidate_id}. No Kestra deployment or production change was made.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'DEV candidate build failed.')
    } finally {
      setBusy(null)
    }
  }

  const switchWorkspace = (id: string) => {
    if (dirty && !window.confirm('Discard unsaved changes and switch workspace?')) return
    setWorkspaceId(id)
  }

  const createWorkspace = async () => {
    if (dirty && !window.confirm('Discard unsaved changes and create a new workspace?')) return
    const name = window.prompt('Name the new strategy workspace')
    if (!name) return
    try {
      const item = await api.createWorkspace(name)
      setWorkspaces((items) => [...items, item])
      setWorkspaceId(item.workspace_id)
      setNotice(`Created independent workspace ${item.workspace_id}.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Workspace creation failed.') }
  }

  const forkWorkspace = async () => {
    if (dirty && !window.confirm('Discard unsaved changes and fork an immutable source?')) return
    try {
      const available = await api.sources()
      if (!available.items.length) {
        setNotice('No immutable DEV candidates or approved releases are available to fork yet.')
        return
      }
      const choices = available.items.map((item, index) => `${index + 1}. ${item.label}`).join('\n')
      const selected = window.prompt(`Select the source number to fork:\n${choices}`)
      if (!selected) return
      const source = available.items[Number(selected) - 1]
      if (!source) throw new Error('Select a valid source number.')
      const name = window.prompt('Name the new strategy workspace', 'Forked strategy')
      if (!name) return
      const item = await api.forkWorkspace(source.source_type, source.source_id, name)
      setWorkspaces((items) => [...items, item])
      setWorkspaceId(item.workspace_id)
      setNotice(`Forked ${source.label} into ${item.workspace_id}.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Fork failed.') }
  }

  const copyText = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setNotice(`${label} copied to clipboard.`)
    } catch {
      setError('Clipboard access was blocked by the browser.')
    }
  }

  const reset = () => {
    if (!loaded) return
    if (!window.confirm('Discard all unsaved changes and reload the saved policy?')) return
    setPolicy(structuredClone(loaded.spec))
    setValidation(null)
    setPreview(null)
    setError(null)
    setNotice('Unsaved changes discarded.')
  }

  const copyPreview = async () => {
    if (!preview) return
    try {
      await navigator.clipboard.writeText(preview.code)
      setNotice('Generated Python copied to clipboard.')
    } catch {
      setError('Clipboard access was blocked by the browser.')
    }
  }


  return (
    <div
      className="app-shell"
      data-theme={preferences.theme}
      style={{ '--uwflow-text-scale': TEXT_SIZES.find((item) => item.id === preferences.textSize)?.scale ?? 1 } as CSSProperties & { '--uwflow-text-scale': number }}
    >
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><span>UW</span><i /></div>
          <div><strong>uwflow</strong><small>POLICY STUDIO</small></div>
        </div>
        <div className="sidebar-section-label">UNDERWRITING FLOW</div>
        <nav className="stage-nav" aria-label="Underwriting stages">
          {stages.map((stage) => (
            <button key={stage.id} className={`stage-nav-item ${stage.id === activeStageId ? 'active' : ''} ${!stage.editable ? 'locked' : ''}`}
              onClick={() => void selectStage(stage)}>
              <span className="stage-number">{String(stage.number).padStart(2, '0')}</span>
              <span className="stage-nav-icon">{stageIcon(stage.editor)}</span>
              <span className="stage-nav-text"><strong>{stage.label}</strong><small>{statusLabel(stage)}</small></span>
              {stage.id === activeStageId && <ChevronRight size={15} className="stage-chevron" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-release-card">
          <div className="release-card-top"><ShieldCheck size={15} /><span>RUNTIME RELEASE</span></div>
          <strong>v2.0.0</strong>
          <small>Immutable · current repository runtime</small>
          <div className="release-status"><i /> DEV authoring · PROD untouched</div>
        </div>
        <div className="sidebar-foot"><span>UWflow Policy Studio</span><span>Local policy authoring</span></div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><ChevronRight size={13} /><strong>Policy authoring</strong></div>
          <div className="topbar-right">
            <span className="environment-label"><i /> DEV AUTHORING · LOCAL</span>
            <select aria-label="Strategy workspace" value={workspaceId} onChange={(event) => switchWorkspace(event.target.value)} disabled={!workspaceId}>
              {workspaces.map((item) => <option key={item.workspace_id} value={item.workspace_id}>{item.name} · {item.source?.type === 'core-default' ? 'Core default' : `${item.source?.type ?? 'workspace'} ${item.source?.id ?? ''}`}</option>)}
            </select>
            <button className="help-button" title="Create workspace" onClick={() => void createWorkspace()}><FolderPlus size={16} /></button>
            <button className="help-button" title="Fork candidate or approved release" onClick={() => void forkWorkspace()}><GitBranch size={16} /></button>
            <button className="settings-trigger" title="Display settings" aria-label="Display settings" onClick={() => setSettingsOpen(true)}><Settings2 size={16} /><span>Display</span></button>
            <button className="help-button" title="About the studio" onClick={() => setNotice('Save writes canonical JSON and generated Python locally. Build DEV candidate packages the saved policy pair and runtime into a content-addressed bundle; explicit Kestra commands publish it only to com.ai.credit.dev. Production remains gated by Git review and the uwflow-production environment.')}><CircleHelp size={17} /></button>
          </div>
        </header>

        <div className={`page-content ${policy?.kind === 'routing_dag' ? 'routing-page-content' : ''}`}>
          <div className="page-heading">
            <div>
              <div className="eyebrow page-eyebrow">POLICY DESIGN / STAGE {activeStage?.number ?? '—'}</div>
              <div className="heading-line">
                <h1>{activeStage?.label ?? 'Loading studio'}</h1>
                {activeStage && <span className={`status-pill ${activeStage.status}`}>{activeStage.status === 'editable' ? 'EDITABLE' : activeStage.status === 'planned' ? 'PLANNED' : 'PROTECTED'}</span>}
              </div>
              <p>{activeStage?.description}</p>
            </div>
            {activeStage?.editable && (
              <div className="heading-meta">
                <div><span>POLICY ID</span><strong>{policy?.id ?? '—'}</strong></div>
                <div><span>POLICY MODEL</span><strong>{policy?.kind === 'dmn_table' ? 'ONE PREDICATE / INPUT' : policy?.kind === 'routing_dag' ? 'DAG · PRIORITY' : '—'}</strong></div>
                <div><span>SOURCE STATE</span><strong className={dirty ? 'dirty-text' : ''}>{dirty ? 'UNSAVED CHANGES' : 'IN SYNC'}</strong></div>
              </div>
            )}
          </div>

          {error && <div className="notice-banner error"><AlertCircle size={16} /><span>{error}</span><button onClick={() => setError(null)}><X size={15} /></button></div>}
          {notice && <div className="notice-banner success"><Check size={16} /><span>{notice}</span><button onClick={() => setNotice(null)}><X size={15} /></button></div>}

          {busy === 'load' && !policy ? (
            <div className="loading-state"><LoaderCircle className="spin" size={22} /><span>Loading policy contract…</span></div>
          ) : !activeStage ? (
            <div className="loading-state error-state"><AlertCircle size={20} /><span>{apiStatus === 'disconnected' ? 'The local Policy Studio API is not available. Start uvicorn on the API port configured in frontend/.env.local and reload this page.' : 'No editable stage is available in the stage catalogue.'}</span></div>
          ) : !activeStage.editable ? (
            <section className="protected-stage-card">
              <div className="protected-icon"><LockKeyhole size={23} /></div>
              <span className="eyebrow">SINGLE-RESPONSIBILITY BOUNDARY</span>
              <h2>{activeStage?.label} is protected</h2>
              <p>{activeStage?.description}</p>
              <p className="protected-note">This stage remains part of the UWflow runtime and is not currently editable in the local Policy Studio.</p>
              <div className="protected-footer"><ShieldCheck size={16} /> No runtime or deployment controls are exposed here.</div>
            </section>
          ) : stageLoadError ? (
            <div className="loading-state error-state"><AlertCircle size={20} /><span>{stageLoadError}</span></div>
          ) : policy && catalog ? (
            <>
              <div className={`editor-toolbar ${policy.kind === 'routing_dag' ? 'routing-toolbar' : 'dmn-toolbar'}`}>
                <div className="editor-mode-label">
                  <span className="mode-icon">{policy.kind === 'dmn_table' ? <Table2 size={17} /> : <GitBranch size={17} />}</span>
                  <div><strong>{policy.kind === 'dmn_table' ? 'Underwriting checks' : 'Routing graph editor'}</strong><small>{policy.kind === 'dmn_table' ? `${(policy as DmnPolicy).checks.length} variables · one positive predicate each` : `${(policy as Extract<Policy, { kind: 'routing_dag' }>).nodes.length} nodes · ${(policy as Extract<Policy, { kind: 'routing_dag' }>).edges.length} edges`}</small></div>
                </div>
                <div className="editor-actions">
                  {dirty && <button className="text-action reset-action" onClick={reset}>Discard changes</button>}
                  <button className="secondary-button" onClick={() => void validate()} disabled={busy !== null}><ShieldCheck size={15} /> Validate</button>
                  <button className="secondary-button" onClick={() => void openPreview()} disabled={busy !== null || validation?.valid !== true}><Code2 size={15} /> Python preview</button>
                  <button className="primary-button" onClick={() => void save()} disabled={!dirty || busy !== null || validation?.valid !== true}><Save size={15} /> Save policy</button>
                  <label className="baseline-release-control">
                    <span>Verified PROD baseline</span>
                    <input
                      value={baselineRelease}
                      onChange={(event) => setBaselineRelease(event.target.value)}
                      placeholder="e.g. 2.0.0"
                      aria-label="Verified production baseline release"
                      inputMode="numeric"
                      spellCheck={false}
                    />
                  </label>
                  <button className="secondary-button dev-candidate-button" onClick={() => void buildDevCandidate()} disabled={dirty || busy !== null || validation?.valid !== true || !/^\d+\.\d+\.\d+$/.test(baselineRelease.trim())} title="Build an immutable local bundle against the verified production baseline"><PackagePlus size={15} /> {busy === 'candidate' ? 'Building DEV…' : 'Build DEV candidate'}</button>
                </div>
              </div>

              {validation && (
                <div className={`validation-strip ${validation.valid ? 'valid' : 'invalid'}`}>
                  {validation.valid ? <Check size={15} /> : <AlertCircle size={15} />}
                  <span>{validation.valid ? 'Schema and generated Python checks passed' : validation.errors.join('; ')}</span>
                  {validation.generated_sha256 && <code>{validation.generated_sha256.slice(0, 12)}</code>}
                </div>
              )}

              <div className={`editor-body ${policy.kind === 'routing_dag' ? 'routing-editor-body' : 'dmn-editor-body'}`} key={activeStageId}>
                {policy.kind === 'dmn_table' ? (
                  <DmnEditor policy={policy} catalog={catalog} onChange={updatePolicy} />
                ) : (
                  <RoutingEditor policy={policy} catalog={catalog} onChange={updatePolicy} />
                )}
              </div>
            </>
          ) : (
            <div className="loading-state"><LoaderCircle className="spin" size={22} /><span>Preparing editor…</span></div>
          )}
        </div>

        <footer className="workspace-footer">
          <div><span className={`footer-dot ${apiStatus}`} /> {apiStatus === 'connected' ? 'API connected' : apiStatus === 'checking' ? 'Connecting to API' : 'API disconnected'}</div>
          <span>Canonical JSON <b>→</b> Validator <b>→</b> Python compiler</span>
          <div><GitCommitHorizontal size={14} /> Git working tree only</div>
        </footer>
      </main>

      {settingsOpen && (
        <div className="settings-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false) }}>
          <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
            <header className="settings-header">
              <div>
                <div className="eyebrow">PERSONAL DISPLAY PREFERENCES</div>
                <h2 id="settings-title">Studio appearance</h2>
                <p>Changes apply immediately and are saved in this browser. They do not change policies, candidates or runtime output.</p>
              </div>
              <button className="icon-button" aria-label="Close display settings" onClick={() => setSettingsOpen(false)}><X size={18} /></button>
            </header>

            <div className="settings-section">
              <div className="settings-section-heading">
                <strong>Theme</strong>
                <span>Choose the workspace surface and contrast.</span>
              </div>
              <div className="theme-choice-grid">
                {STUDIO_THEMES.map((theme) => (
                  <button
                    key={theme.id}
                    type="button"
                    className={`theme-choice ${preferences.theme === theme.id ? 'selected' : ''}`}
                    aria-pressed={preferences.theme === theme.id}
                    onClick={() => setPreferences((current) => ({ ...current, theme: theme.id }))}
                  >
                    <span className="theme-swatches" aria-hidden="true">
                      {theme.swatches.map((swatch) => <i key={swatch} style={{ backgroundColor: swatch }} />)}
                    </span>
                    <span className="theme-choice-copy"><strong>{theme.label}</strong><small>{theme.description}</small></span>
                    <span className="theme-choice-check" aria-hidden="true">{preferences.theme === theme.id ? '✓' : ''}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="settings-section text-size-section">
              <div className="settings-section-heading">
                <strong>Text size</strong>
                <span>Increase labels, descriptions, fields and controls together.</span>
              </div>
              <div className="text-size-choices" role="group" aria-label="Text size">
                {TEXT_SIZES.map((size) => (
                  <button
                    key={size.id}
                    type="button"
                    className={`text-size-choice ${preferences.textSize === size.id ? 'selected' : ''}`}
                    aria-pressed={preferences.textSize === size.id}
                    onClick={() => setPreferences((current) => ({ ...current, textSize: size.id }))}
                  >
                    <span className={`text-size-sample ${size.id}`}>Aa</span>
                    <strong>{size.label}</strong>
                    <small>{Math.round(size.scale * 100)}%</small>
                  </button>
                ))}
              </div>
            </div>

            <footer className="settings-footer">
              <span>Saved locally · browser-specific</span>
              <div>
                <button className="text-action" onClick={() => setPreferences(DEFAULT_STUDIO_PREFERENCES)}>Reset defaults</button>
                <button className="primary-button" onClick={() => setSettingsOpen(false)}>Done</button>
              </div>
            </footer>
          </section>
        </div>
      )}

      {candidateOpen && candidate && (
        <div className="preview-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setCandidateOpen(false) }}>
          <section className="candidate-drawer">
            <header className="preview-header">
              <div><div className="eyebrow">DEV RELEASE CANDIDATE</div><h2>{candidate.candidate_id}</h2><small>Content-addressed · manual DEV flow · production untouched</small></div>
              <button className="icon-button" onClick={() => setCandidateOpen(false)}><X size={18} /></button>
            </header>
            <div className="candidate-metadata">
              <div><span>BASELINE RELEASE</span><strong>v{candidate.based_on_production_release}</strong></div>
              <div><span>APPROVED RELEASE</span><strong>Assigned after approval</strong></div>
              <div><span>DEV NAMESPACE</span><strong>{candidate.dev_namespace}</strong></div>
            </div>
            <div className="candidate-step">
              <div className="eyebrow">01 · ONE-TIME DEV BASELINE</div>
              <p>Upload the verified PROD baseline <strong>v{candidate.based_on_production_release}</strong> into DEV. The baseline is selected explicitly for this candidate and must match the live production runtime-release label.</p>
              <pre><code>{candidate.setup_commands}</code></pre>
              <button className="secondary-button small" onClick={() => void copyText(candidate.setup_commands, 'Baseline setup commands')}><Code2 size={13} /> Copy commands</button>
            </div>
            <div className="candidate-step">
              <div className="eyebrow">02 · PUBLISH THIS CANDIDATE TO DEV</div>
              <p>Uploads the immutable candidate bundle under its own path and deploys a manual-only flow. Namespace Files upload deliberately has no overwrite flag.</p>
              <pre><code>{candidate.candidate_commands}</code></pre>
              <button className="secondary-button small" onClick={() => void copyText(candidate.candidate_commands, 'Candidate deploy commands')}><Code2 size={13} /> Copy commands</button>
            </div>
            <div className="candidate-step">
              <div className="eyebrow">03 · REPLAY A DE-IDENTIFIED COHORT</div>
              <p>Runs every case through both DEV baseline and DEV candidate flows, then writes decision-change and approved-amount comparisons.</p>
              <pre><code>{candidate.replay_command}</code></pre>
              <button className="secondary-button small" onClick={() => void copyText(candidate.replay_command, 'Cohort replay command')}><Code2 size={13} /> Copy command</button>
            </div>
            <footer className="preview-footer"><ShieldCheck size={15} /><span>Building a candidate writes local files only. No Kestra call, production release or approval is performed.</span></footer>
          </section>
        </div>
      )}

      {previewOpen && preview && (
        <div className="preview-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setPreviewOpen(false) }}>
          <section className="preview-drawer">
            <header className="preview-header">
              <div><div className="eyebrow">DETERMINISTIC COMPILER OUTPUT</div><h2>Generated Python preview</h2><small>Read-only preview · not yet deployed</small></div>
              <div className="preview-header-actions"><button className="secondary-button small" onClick={() => void copyPreview()}><ArrowDownToLine size={14} /> Copy code</button><button className="icon-button" onClick={() => setPreviewOpen(false)}><X size={18} /></button></div>
            </header>
            <div className="preview-metadata">
              <div><span>GENERATED SHA-256</span><code>{preview.generated_sha256}</code></div>
              <div><span>POLICY SHA-256</span><code>{preview.policy_sha256}</code></div>
            </div>
            <pre className="python-preview"><code>{preview.code}</code></pre>
            <footer className="preview-footer"><ShieldCheck size={15} /><span>This preview does not write a release bundle or invoke Kestra.</span></footer>
          </section>
        </div>
      )}
    </div>
  )
}

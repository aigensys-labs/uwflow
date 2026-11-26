import type {
  DevCandidate,
  LoadedPolicy,
  Policy,
  PreviewResult,
  SaveResult,
  Stage,
  StageCatalog,
  ValidationResult,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = await response.json() as { detail?: unknown }
      if (typeof payload.detail === 'string') detail = payload.detail
      else if (payload.detail && typeof payload.detail === 'object') {
        detail = JSON.stringify(payload.detail)
      }
    } catch {
      // Keep the HTTP status as a useful fallback.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export interface Workspace { workspace_id: string; name: string; source: { type: string; id: string }; updated_at: string }
export interface WorkspaceSource { source_type: 'candidate' | 'approved-release'; source_id: string; label: string }

const workspaceQuery = (id?: string) => id ? `?workspace_id=${encodeURIComponent(id)}` : ''

export const api = {
  stages: () => request<Stage[]>('/api/stages'),
  catalog: (stageId: string) => request<StageCatalog>(`/api/catalog/${stageId}`),
  policy: (stageId: string, workspaceId?: string) => request<LoadedPolicy>(`/api/policies/${stageId}${workspaceQuery(workspaceId)}`),
  validate: (stageId: string, spec: Policy, workspaceId?: string) =>
    request<ValidationResult>(`/api/policies/${stageId}/validate${workspaceQuery(workspaceId)}`, {
      method: 'POST', body: JSON.stringify({ spec }),
    }),
  preview: (stageId: string, spec: Policy, workspaceId?: string) =>
    request<PreviewResult>(`/api/policies/${stageId}/preview${workspaceQuery(workspaceId)}`, {
      method: 'POST', body: JSON.stringify({ spec }),
    }),
  save: (stageId: string, spec: Policy, expectedSha256: string, workspaceId?: string) =>
    request<SaveResult>(`/api/policies/${stageId}${workspaceQuery(workspaceId)}`, {
      method: 'PUT', body: JSON.stringify({ spec, expected_sha256: expectedSha256 }),
    }),
  workspaces: () => request<{ items: Workspace[]; default_workspace_id: string }>('/api/workspaces'),
  sources: () => request<{ items: WorkspaceSource[] }>('/api/workspaces/sources'),
  createWorkspace: (name: string) => request<Workspace>('/api/workspaces', { method: 'POST', body: JSON.stringify({ name }) }),
  forkWorkspace: (source_type: string, source_id: string, name: string) => request<Workspace>('/api/workspaces/fork', {
    method: 'POST', body: JSON.stringify({ source_type, source_id, name }),
  }),
  buildDevCandidate: (baselineRelease: string, workspaceId: string) =>
    request<DevCandidate>('/api/dev-candidates/build', {
      method: 'POST', body: JSON.stringify({ baseline_release: baselineRelease, workspace_id: workspaceId }),
    }),
}

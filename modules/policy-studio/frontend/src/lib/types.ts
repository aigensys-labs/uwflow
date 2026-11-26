export type FieldType = 'boolean' | 'integer' | 'number' | 'string'
export type Operator = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'in' | 'between'

export interface Condition {
  field: string
  op: Operator
  value: unknown
}

export interface DmnCheck {
  check_id: string
  field: string
  description: string
  valid_when: {
    op: Operator
    value: unknown
  }
  failure_reason_code: string
}

export interface DmnPolicy {
  schema_version: 2
  id: string
  stage: string
  kind: 'dmn_table'
  description: string
  inputs: { field: string; type: string }[]
  checks: DmnCheck[]
}

export interface RoutingNode {
  id: string
  type: 'condition_split' | 'source_plan' | 'outcome'
  label: string
  source_ids?: string[]
  action?: string
  reason?: string
}

export interface RoutingEdge {
  id: string
  source: string
  target: string
  is_default: boolean
  condition?: Condition
  priority?: number
}

export interface RoutingPolicy {
  schema_version: number
  id: string
  stage: string
  kind: 'routing_dag'
  description: string
  entry_node: string
  inputs: { field: string; type: string }[]
  nodes: RoutingNode[]
  edges: RoutingEdge[]
}

export type Policy = DmnPolicy | RoutingPolicy

export interface Stage {
  id: string
  number: number
  label: string
  description: string
  editable: boolean
  editor: 'dmn_table' | 'routing_dag' | null
  status: 'editable' | 'protected' | 'planned'
}

export interface StageCatalog {
  stage: string
  fields: Record<string, { type: FieldType; description: string }>
  source_ids: string[]
}

export interface LoadedPolicy {
  spec: Policy
  sha256: string
  kind: Policy['kind']
  stage: string
}

export interface ValidationResult {
  valid: boolean
  errors: string[]
  policy_sha256?: string
  generated_sha256?: string
}

export interface PreviewResult {
  stage: string
  code: string
  policy_sha256: string
  generated_sha256: string
}

export interface SaveResult {
  saved: boolean
  stage: string
  sha256: string
  generated_sha256: string
  message: string
}

export interface DevCandidate {
  candidate_id: string
  based_on_production_release: string
  dev_namespace: string
  baseline_flow_id: string
  candidate_flow_id: string
  bundle_relative_path: string
  flow_relative_path: string
  manifest_sha256: string
  setup_commands: string
  candidate_commands: string
  replay_command: string
}

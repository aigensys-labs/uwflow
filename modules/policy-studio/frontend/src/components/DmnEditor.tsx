import type { DmnCheck, DmnPolicy, StageCatalog } from '../lib/types'
import { ConditionEditor } from './ConditionEditor'

interface Props {
  policy: DmnPolicy
  catalog: StageCatalog
  onChange: (policy: DmnPolicy) => void
}

const LABELS: Record<string, string> = {
  APPLICATION_DATA_VALID: 'Application data',
  MINIMUM_AGE: 'Applicant age',
  MINIMUM_INCOME: 'Monthly income',
  EMPLOYMENT_STATUS: 'Employment status',
  REQUEST_AMOUNT: 'Requested amount',
  LOAN_TERM: 'Loan term',
}

export function DmnEditor({ policy, catalog, onChange }: Props) {
  const updateCheck = (checkId: string, update: (check: DmnCheck) => DmnCheck) => {
    onChange({
      ...policy,
      checks: policy.checks.map((check) => check.check_id === checkId ? update(check) : check),
    })
  }

  return (
    <div className="dmn-editor">
      <section className="dmn-intro">
        <div>
          <div className="eyebrow">UNDERWRITING POLICY CONTRACT</div>
          <h3>One eligibility condition per variable</h3>
          <p>Define when each input is valid. UWflow derives the result: a matching predicate is PASS; its logical complement is FAIL.</p>
        </div>
        <span className="tag tag-neutral">{policy.checks.length} policy checks</span>
      </section>

      <div className="rule-list">
        {policy.checks.map((check, index) => {
          const input = policy.inputs.find((item) => item.field === check.field)
          const type = catalog.fields[check.field]?.type ?? input?.type ?? 'string'
          return (
            <article className="rule-card policy-check-card" key={check.check_id}>
              <header className="policy-check-header">
                <div className="rule-identity">
                  <span className="rule-index">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <div className="policy-check-title">{LABELS[check.check_id] ?? check.check_id.replaceAll('_', ' ')}</div>
                    <span className="rule-group">{check.check_id} · {type}</span>
                  </div>
                </div>
                <span className="derived-status"><i /> PASS / FAIL DERIVED</span>
              </header>

              <label className="field-control policy-description">
                <span>Policy description</span>
                <input value={check.description} onChange={(event) => updateCheck(check.check_id, (current) => ({ ...current, description: event.target.value }))} />
              </label>

              <div className="conditions-heading">
                <span>VALID WHEN</span>
                <small>One positive predicate · no duplicated PASS/FAIL rows</small>
              </div>
              <ConditionEditor
                condition={{ field: check.field, ...check.valid_when }}
                catalog={catalog}
                fieldReadOnly
                onChange={(condition) => updateCheck(check.check_id, (current) => ({
                  ...current,
                  valid_when: { op: condition.op, value: condition.value },
                }))}
              />

              <div className="derived-outcome-row">
                <div className="derived-outcome pass"><span className="result-dot" /> Predicate true <strong>PASS</strong></div>
                <span className="derived-else">ELSE</span>
                <div className="derived-outcome fail"><span className="result-dot" /> Predicate false <strong>FAIL</strong></div>
              </div>

              <label className="field-control failure-reason-field">
                <span>Failure reason code · used only when predicate is false</span>
                <input value={check.failure_reason_code} onChange={(event) => updateCheck(check.check_id, (current) => ({
                  ...current,
                  failure_reason_code: event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'),
                }))} />
              </label>
            </article>
          )
        })}
      </div>
      <p className="policy-contract-note">The six Stage 1 inputs are part of the existing runtime contract. The studio lets you change policy thresholds and allowed values, not add or remove runtime fields.</p>
    </div>
  )
}

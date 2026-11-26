import type { Condition, FieldType, Operator, StageCatalog } from '../lib/types'

const OPERATORS: Operator[] = ['==', '!=', '<', '<=', '>', '>=', 'in', 'between']

function allowedOperators(type: FieldType): Operator[] {
  return type === 'integer' || type === 'number'
    ? OPERATORS
    : ['==', '!=', 'in']
}

function emptyValue(): unknown {
  return null
}

function parseList(raw: string, type: FieldType): unknown[] {
  return raw.split(',').map((item) => item.trim()).filter(Boolean).map((item) => {
    if (type === 'boolean') {
      const normalized = item.toLowerCase()
      return normalized === 'true' ? true : normalized === 'false' ? false : null
    }
    if (type === 'integer') {
      if (!/^[+-]?\d+$/.test(item)) return null
      const parsed = Number(item)
      return Number.isSafeInteger(parsed) ? parsed : null
    }
    if (type === 'number') {
      const parsed = Number(item)
      return Number.isFinite(parsed) ? parsed : null
    }
    return item
  })
}

interface Props {
  condition: Condition
  catalog: StageCatalog
  onChange: (next: Condition) => void
  fieldReadOnly?: boolean
}

export function ConditionEditor({ condition, catalog, onChange, fieldReadOnly = false }: Props) {
  const fields = Object.entries(catalog.fields)
  const selectedType = catalog.fields[condition.field]?.type ?? 'string'
  const operators = allowedOperators(selectedType)

  const changeField = (field: string) => {
    const type = catalog.fields[field]?.type ?? 'string'
    const nextOperator: Operator = type === 'integer' || type === 'number' ? '<' : '=='
    onChange({ field, op: nextOperator, value: emptyValue() })
  }

  const changeOperator = (op: Operator) => {
    let value = condition.value
    if (op === 'between') value = [null, null]
    else if (op === 'in') value = []
    else if (Array.isArray(value)) value = emptyValue()
    onChange({ ...condition, op, value })
  }

  const updateValue = (value: unknown) => onChange({ ...condition, value })

  return (
    <div className="condition-editor">
      <label className="field-control">
        <span>Input field</span>
        {fieldReadOnly ? (
          <input value={`${condition.field} · ${selectedType}`} disabled readOnly />
        ) : (
          <select value={condition.field} onChange={(event) => changeField(event.target.value)}>
            {fields.map(([name, field]) => (
              <option key={name} value={name}>{name} · {field.type}</option>
            ))}
          </select>
        )}
      </label>
      <label className="field-control operator-control">
        <span>Operator</span>
        <select value={condition.op} onChange={(event) => changeOperator(event.target.value as Operator)}>
          {operators.map((op) => <option key={op} value={op}>{op}</option>)}
        </select>
      </label>
      <div className="field-control condition-value">
        <span>Value</span>
        {condition.op === 'between' && Array.isArray(condition.value) ? (
          <div className="range-value">
            <input type="number" value={String(condition.value[0] ?? '')}
              onChange={(event) => updateValue([event.target.value === '' ? null : Number(event.target.value), condition.value instanceof Array ? condition.value[1] : 0])} />
            <span>to</span>
            <input type="number" value={String(condition.value[1] ?? '')}
              onChange={(event) => updateValue([condition.value instanceof Array ? condition.value[0] : 0, event.target.value === '' ? null : Number(event.target.value)])} />
          </div>
        ) : condition.op === 'in' ? (
          <input type="text" value={Array.isArray(condition.value) ? condition.value.join(', ') : ''}
            placeholder="Separate values with commas"
            onChange={(event) => updateValue(parseList(event.target.value, selectedType))} />
        ) : selectedType === 'boolean' ? (
          <select value={condition.value === null ? '' : String(condition.value)} onChange={(event) => updateValue(event.target.value === 'true')}>
            <option value="" disabled>Choose true or false</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : selectedType === 'integer' || selectedType === 'number' ? (
          <input type="number" step={selectedType === 'integer' ? 1 : 'any'} value={String(condition.value ?? '')}
            onChange={(event) => updateValue(event.target.value === '' ? null : Number(event.target.value))} />
        ) : (
          <input type="text" value={String(condition.value ?? '')} onChange={(event) => updateValue(event.target.value)} />
        )}
      </div>
    </div>
  )
}

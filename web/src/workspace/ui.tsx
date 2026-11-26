import { useId, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: IconName
  label: string
  active?: boolean
  size?: 'sm' | 'md'
}

export function IconButton({ icon, label, active, size = 'md', className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      className={`icon-btn ${size === 'sm' ? 'icon-btn-sm' : ''} ${className ?? ''}`.trim()}
      aria-label={label}
      title={label}
      aria-pressed={active === undefined ? undefined : active}
      data-active={active ? 'true' : undefined}
      {...rest}
    >
      <Icon name={icon} size={size === 'sm' ? 14 : 15} />
    </button>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>
}

interface SegmentedOption<T extends string> {
  value: T
  label: string
  count?: number
  title?: string
}

interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  ariaLabel: string
  size?: 'sm' | 'md'
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = 'md',
}: SegmentedProps<T>) {
  return (
    <div className={`segmented ${size === 'sm' ? 'segmented-sm' : ''}`} role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          className="segmented-item"
          aria-pressed={value === option.value}
          data-active={value === option.value ? 'true' : undefined}
          onClick={() => onChange(option.value)}
          title={option.title ?? option.label}
        >
          <span>{option.label}</span>
          {option.count !== undefined ? <span className="segmented-count num">{option.count}</span> : null}
        </button>
      ))}
    </div>
  )
}

/**
 * The one way a labelled control is laid out in an inspector.
 *
 * These primitives exist because the same markup - label, value, control - was
 * being retyped per panel, and each copy drifted a few pixels. `Field` is a
 * div, not a label: some fields wrap buttons, and nesting a button inside a
 * label misreports what the label belongs to. The two controls below therefore
 * name their label explicitly with `aria-labelledby`.
 */
export function Field({
  label,
  value,
  labelId,
  children,
}: {
  label: string
  value?: ReactNode
  labelId?: string
  children: ReactNode
}) {
  return (
    <div className="field-stack">
      <span className="field-label" id={labelId}>
        {label}
        {value !== undefined && value !== null ? <b className="num">{value}</b> : null}
      </span>
      {children}
    </div>
  )
}

export function RangeField({
  label,
  value,
  min,
  max,
  step = 1,
  suffix = '',
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  suffix?: string
  onChange: (value: number) => void
}) {
  const labelId = useId()
  return (
    <Field label={label} value={`${value}${suffix}`} labelId={labelId}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-labelledby={labelId}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </Field>
  )
}

export function TextField({
  label,
  value,
  valueLabel,
  placeholder,
  maxLength,
  rows,
  type = 'text',
  onChange,
}: {
  label: string
  value: string
  valueLabel?: ReactNode
  placeholder?: string
  maxLength?: number
  rows?: number
  type?: 'text' | 'password'
  onChange: (value: string) => void
}) {
  const labelId = useId()
  return (
    <Field label={label} value={valueLabel} labelId={labelId}>
      {rows ? (
        <textarea
          rows={rows}
          value={value}
          placeholder={placeholder}
          maxLength={maxLength}
          aria-labelledby={labelId}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          type={type}
          value={value}
          placeholder={placeholder}
          maxLength={maxLength}
          autoComplete="off"
          spellCheck={false}
          aria-labelledby={labelId}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  )
}

export function Spinner({ label = 'Working' }: { label?: string }) {
  return (
    <span className="spinner" role="status" aria-label={label}>
      <span aria-hidden="true" />
    </span>
  )
}

export function EmptyHint({
  icon,
  title,
  children,
  action,
}: {
  icon: IconName
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty-hint">
      <span className="empty-hint-icon" aria-hidden="true">
        <Icon name={icon} size={20} />
      </span>
      <div>
        <p className="empty-hint-title">{title}</p>
        {children ? <div className="empty-hint-copy">{children}</div> : null}
        {action ? <div className="empty-hint-action">{action}</div> : null}
      </div>
    </div>
  )
}

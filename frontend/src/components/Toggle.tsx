interface ToggleProps {
  label: string
  title: string
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
}

function Toggle({ label, title, checked, disabled, onChange }: ToggleProps) {
  return (
    <label className="toggle" title={title}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="toggle-track" aria-hidden="true" />
      <span className="toggle-label">{label}</span>
    </label>
  )
}

export default Toggle

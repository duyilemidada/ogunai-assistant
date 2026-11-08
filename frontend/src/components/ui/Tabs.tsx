interface Tab {
  key: string
  label: string
}
interface Props {
  tabs: Tab[]
  active: string
  onChange: (key: string) => void
}

export default function Tabs({ tabs, active, onChange }: Props) {
  return (
    <div className="px-4 py-3">
      <div className="inline-flex gap-1 rounded-xl border border-border bg-bg-surface p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className={`rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${
              active === t.key
                ? 'bg-bg-elevated text-text-primary shadow-soft'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
    </div>
  )
}

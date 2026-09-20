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
    <div className="flex gap-1 border-b border-border px-4">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-3 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            active === t.key
              ? 'border-primary text-text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

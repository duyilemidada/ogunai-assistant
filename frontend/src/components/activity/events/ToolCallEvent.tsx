import Collapsible from '../../ui/Collapsible'

const TOOL_ICONS: Record<string, string> = {
  web_search: '🔍',
  fetch_url: '🌐',
  browse_js: '🌐',
  browse_authenticated: '🌐',
  run_terminal: '⌨️',
  github_api: '🐙',
  read_file: '📄',
  upload_pdf: '📄',
  ask_document: '📄',
  check_balance: '💰',
  fetch_transactions: '💰',
  draft_transfer: '💰',
  execute_transfer: '💰',
  log_nutrition: '🍽️',
  fetch_macros: '🍽️',
  log_workout: '🏋️',
  log_physical_status: '🏋️',
  adjust_program: '🏋️',
  predict_injury_risk: '🏋️',
  explain_concept: '📚',
  assess_prerequisite: '📚',
  build_learning_plan: '📚',
  generate_practice: '📚',
  record_mastery: '📚',
  daily_deep_read: '📚',
  predict_affinity: '⭐',
  delegate_to: '🔀',
}

interface Props {
  agent: string
  tool: string
  args: Record<string, string>
}

export default function ToolCallEvent({ agent, tool, args }: Props) {
  const icon = TOOL_ICONS[tool] || '⚙️'
  return (
    <div className="px-3 py-2 bg-bg-elevated/50 rounded-lg mx-2 mb-1">
      <Collapsible
        summary={
          <div className="flex items-center gap-2 text-xs min-w-0">
            <span className="shrink-0">{icon}</span>
            <span className="text-text-primary font-mono truncate">{tool}</span>
            <span className="text-text-dim shrink-0">· {agent}</span>
          </div>
        }
      >
        <pre className="text-[11px] text-text-muted font-mono bg-bg-base rounded p-2 overflow-x-auto">
          {JSON.stringify(args, null, 2)}
        </pre>
      </Collapsible>
    </div>
  )
}

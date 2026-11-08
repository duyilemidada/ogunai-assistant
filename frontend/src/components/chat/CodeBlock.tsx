import { useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import {
  oneDark,
  oneLight,
} from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useUiStore } from '../../stores/uiStore'

const LABELS: Record<string, string> = {
  python: 'Python',
  py: 'Python',
  bash: 'Bash',
  sh: 'Shell',
  shell: 'Shell',
  powershell: 'PowerShell',
  json: 'JSON',
  tsx: 'TSX',
  ts: 'TypeScript',
  typescript: 'TypeScript',
  javascript: 'JavaScript',
  js: 'JavaScript',
  jsx: 'JSX',
  sql: 'SQL',
  yaml: 'YAML',
  yml: 'YAML',
  html: 'HTML',
  css: 'CSS',
  diff: 'Diff',
  text: 'Text',
  txt: 'Text',
}

// navigator.clipboard only exists on HTTPS or localhost; fall back for plain HTTP.
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

export default function CodeBlock({
  language,
  children,
}: {
  language: string
  children: string
}) {
  const [copied, setCopied] = useState(false)
  const theme = useUiStore((s) => s.theme)
  const label = LABELS[language.toLowerCase()] ?? language

  const handleCopy = async () => {
    if (await copyText(children)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    }
  }

  return (
    <div className="my-4 overflow-hidden rounded-xl border border-border bg-code-bg shadow-soft">
      <div className="flex items-center justify-between border-b border-border bg-bg-elevated/70 px-3.5 py-2">
        <span className="font-mono text-[11px] font-medium uppercase tracking-wider text-text-muted">
          {label}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-text-muted transition-colors hover:bg-bg-hover hover:text-text-primary"
          aria-label="Copy code"
        >
          {copied ? (
            <>
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className="text-success"
              >
                <path
                  d="M20 6 9 17l-5-5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              Copied
            </>
          ) : (
            <>
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <rect x="9" y="9" width="11" height="11" rx="2" />
                <path d="M5 15V5a2 2 0 0 1 2-2h10" strokeLinecap="round" />
              </svg>
              Copy
            </>
          )}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={theme === 'dark' ? oneDark : oneLight}
        customStyle={{
          margin: 0,
          background: 'transparent',
          fontSize: '13px',
          lineHeight: 1.65,
          padding: '14px 16px',
        }}
        codeTagProps={{
          style: { background: 'transparent', fontFamily: 'var(--font-mono)' },
        }}
      >
        {children}
      </SyntaxHighlighter>
    </div>
  )
}

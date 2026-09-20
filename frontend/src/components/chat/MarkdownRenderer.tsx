import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CodeBlock from './CodeBlock'

export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose-ogun">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...rest }) {
            const match = /language-(\w+)/.exec(className || '')
            const isBlock = Boolean(match) || String(children).includes('\n')
            if (!isBlock) {
              return (
                <code
                  className="bg-bg-elevated text-primary px-1.5 py-0.5 rounded text-[13px] font-mono"
                  {...rest}
                >
                  {children}
                </code>
              )
            }
            return (
              <CodeBlock language={match?.[1] || 'text'}>
                {String(children).replace(/\n$/, '')}
              </CodeBlock>
            )
          },
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:underline"
            />
          ),
          table: (props) => (
            <div className="overflow-x-auto my-3">
              <table {...props} className="w-full text-sm border-collapse" />
            </div>
          ),
          th: (props) => (
            <th
              {...props}
              className="border border-border px-3 py-1.5 bg-bg-elevated text-left"
            />
          ),
          td: (props) => (
            <td {...props} className="border border-border px-3 py-1.5" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

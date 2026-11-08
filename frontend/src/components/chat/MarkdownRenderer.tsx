import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CodeBlock from './CodeBlock'

export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose-ogun">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // CodeBlock draws its own frame, so skip the default <pre> wrapper.
          pre: ({ children }) => <>{children}</>,
          code({ className, children, ...rest }) {
            const match = /language-(\w+)/.exec(className || '')
            const isBlock = Boolean(match) || String(children).includes('\n')
            if (!isBlock) {
              return (
                <code
                  className="rounded-md border border-border/60 bg-bg-elevated px-1.5 py-0.5 font-mono text-[0.86em] text-primary"
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
            <div className="my-4 overflow-x-auto rounded-lg border border-border">
              <table {...props} className="w-full border-collapse text-sm" />
            </div>
          ),
          th: (props) => (
            <th
              {...props}
              className="border-b border-border bg-bg-elevated px-3 py-2 text-left font-semibold"
            />
          ),
          td: (props) => (
            <td {...props} className="border-b border-border/60 px-3 py-2" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

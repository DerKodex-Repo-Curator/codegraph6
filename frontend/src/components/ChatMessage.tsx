import { Bot, User, Loader2, AlertTriangle } from 'lucide-react'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  isError?: boolean
}

interface Props {
  message: Message
}

function renderContent(text: string) {
  // Basic markdown-like rendering without a library
  const lines = text.split('\n')
  const output: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    if (line.trimStart().startsWith('```')) {
      const lang = line.replace(/```/, '').trim()
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      output.push(
        <pre key={i} className="bg-slate-900 border border-slate-700 rounded-lg p-3 overflow-x-auto my-2 text-xs leading-relaxed">
          {lang && <div className="text-slate-500 text-xs mb-2 font-sans">{lang}</div>}
          <code className="text-slate-200">{codeLines.join('\n')}</code>
        </pre>
      )
      i++
      continue
    }

    // Heading
    if (/^#{1,3}\s/.test(line)) {
      const level = line.match(/^(#+)/)?.[1].length ?? 1
      const text = line.replace(/^#+\s/, '')
      const cls = level === 1 ? 'text-base font-semibold text-slate-100 mt-3 mb-1'
        : level === 2 ? 'text-sm font-semibold text-slate-200 mt-2 mb-1'
        : 'text-sm font-medium text-slate-300 mt-1 mb-0.5'
      output.push(<p key={i} className={cls}>{inlineFormat(text)}</p>)
      i++
      continue
    }

    // Bullet list item
    if (/^[-*]\s/.test(line.trimStart())) {
      const items: string[] = []
      while (i < lines.length && /^[-*]\s/.test(lines[i].trimStart())) {
        items.push(lines[i].replace(/^[-*]\s/, ''))
        i++
      }
      output.push(
        <ul key={i} className="list-disc list-inside my-1 flex flex-col gap-0.5">
          {items.map((item, j) => (
            <li key={j} className="text-sm text-slate-300">{inlineFormat(item)}</li>
          ))}
        </ul>
      )
      continue
    }

    // Blank line
    if (line.trim() === '') {
      i++
      continue
    }

    // Normal paragraph
    output.push(
      <p key={i} className="text-sm text-slate-300 leading-relaxed mb-1">
        {inlineFormat(line)}
      </p>
    )
    i++
  }

  return output
}

function inlineFormat(text: string): React.ReactNode {
  // Handle inline code: `...`
  const parts = text.split(/(`[^`]+`)/)
  return parts.map((part, i) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="bg-slate-800 text-violet-300 px-1 py-0.5 rounded text-xs font-mono">
          {part.slice(1, -1)}
        </code>
      )
    }
    // Handle **bold**
    const boldParts = part.split(/(\*\*[^*]+\*\*)/)
    return boldParts.map((bp, j) => {
      if (bp.startsWith('**') && bp.endsWith('**')) {
        return <strong key={j} className="text-slate-200 font-semibold">{bp.slice(2, -2)}</strong>
      }
      return bp
    })
  })
}

export default function ChatMessage({ message }: Props) {
  const isUser = message.role === 'user'
  const isError = message.isError

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${
        isUser ? 'bg-violet-600' : isError ? 'bg-red-900/60' : 'bg-slate-700'
      }`}>
        {isUser
          ? <User size={14} className="text-white" />
          : isError
          ? <AlertTriangle size={13} className="text-red-400" />
          : <Bot size={14} className="text-violet-400" />}
      </div>

      {/* Bubble */}
      <div className={`max-w-[80%] rounded-xl px-4 py-3 ${
        isUser
          ? 'bg-violet-600/20 border border-violet-500/30'
          : isError
          ? 'bg-red-900/20 border border-red-700/40'
          : 'bg-slate-800/60 border border-slate-700/50'
      }`}>
        {isUser ? (
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{message.content}</p>
        ) : message.streaming && !message.content ? (
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 size={13} className="animate-spin" />
            <span className="text-sm">Thinking…</span>
          </div>
        ) : isError ? (
          <p className="text-sm text-red-300 leading-relaxed">{message.content}</p>
        ) : (
          <div className="prose-answer">
            {renderContent(message.content)}
            {message.streaming && (
              <span className="inline-block w-1.5 h-4 bg-violet-400 ml-0.5 animate-pulse rounded-sm" />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

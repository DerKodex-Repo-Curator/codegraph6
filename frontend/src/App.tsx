import { useState } from 'react'
import { X, GitBranch } from 'lucide-react'
import Sidebar from './components/Sidebar'
import ChatPanel from './components/ChatPanel'
import IndexPanel from './components/IndexPanel'

export default function App() {
  const [showIndex, setShowIndex] = useState(false)
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0)

  function handleIndexed() {
    setSidebarRefreshKey(k => k + 1)
  }

  return (
    <div className="flex h-screen bg-[#0d0f14] text-slate-200 overflow-hidden">
      <Sidebar key={sidebarRefreshKey} />

      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 px-5 py-3 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-violet-600 flex items-center justify-center">
              <span className="text-xs font-bold text-white">CG</span>
            </div>
            <span className="font-semibold text-slate-100 text-sm tracking-tight">CodeGraph</span>
          </div>
          <span className="text-slate-700 text-xs">·</span>
          <span className="text-xs text-slate-500">Codebase intelligence</span>
        </header>

        {showIndex ? (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="max-w-xl mx-auto">
              <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <GitBranch size={14} />
                  <span>Repository Indexing</span>
                </div>
                <button
                  onClick={() => setShowIndex(false)}
                  className="text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
              <IndexPanel onIndexed={() => { handleIndexed(); setShowIndex(false) }} />
            </div>
          </div>
        ) : (
          <ChatPanel onShowIndex={() => setShowIndex(true)} />
        )}
      </div>
    </div>
  )
}

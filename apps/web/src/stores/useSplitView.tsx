import { useState, createContext, useContext, useCallback } from 'react'

export type PageId = 'ruyi' | 'tiangong' | 'kairos' | 'juanzong'

export const ALL_PAGES: { id: PageId; label: string }[] = [
  { id: 'ruyi', label: '如意' },
  { id: 'tiangong', label: '天工' },
  { id: 'juanzong', label: '卷宗' },
  { id: 'kairos', label: 'Kairos' },
]

type SplitViewState = {
  rightPanel: PageId | null
  splitRatio: number
  setRightPanel: (id: PageId | null) => void
  toggleSplit: (currentRoute: string) => void
}

const SplitViewContext = createContext<SplitViewState>({
  rightPanel: null,
  splitRatio: 0.5,
  setRightPanel: () => {},
  toggleSplit: () => {},
})

export function SplitViewProvider({ children }: { children: React.ReactNode }) {
  const [rightPanel, setRightPanelRaw] = useState<PageId | null>(null)
  const splitRatio = 0.5

  const setRightPanel = useCallback((id: PageId | null) => {
    setRightPanelRaw(id)
  }, [])

  const toggleSplit = useCallback((currentRoute: string) => {
    setRightPanelRaw((prev) => {
      if (prev !== null) return null
      const first = ALL_PAGES.find((p) => p.id !== currentRoute)
      return first?.id ?? null
    })
  }, [])

  return (
    <SplitViewContext.Provider value={{ rightPanel, splitRatio, setRightPanel, toggleSplit }}>
      {children}
    </SplitViewContext.Provider>
  )
}

export function useSplitView() {
  return useContext(SplitViewContext)
}

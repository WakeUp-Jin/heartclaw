import RuyiPage from '../pages/RuyiPage'
import TiangongPage from '../pages/TiangongPage'
import KairosPage from '../pages/KairosPage'
import JuanzongPage from '../pages/JuanzongPage'

const PAGE_LABELS: Record<string, string> = {
  ruyi: '如意',
  tiangong: '天工',
  kairos: 'Kairos',
  juanzong: '卷宗',
}

export function getPageLabel(pageId: string): string {
  return PAGE_LABELS[pageId] || pageId
}

export default function PageRenderer({ pageId }: { pageId: string }) {
  switch (pageId) {
    case 'ruyi': return <RuyiPage />
    case 'tiangong': return <TiangongPage />
    case 'kairos': return <KairosPage />
    case 'juanzong': return <JuanzongPage />
    default: return null
  }
}

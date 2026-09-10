import { closeSession } from '../api'
import { useGameStore } from '../store'

export function Header() {
  const busy = useGameStore(s => s.busy)
  const sessionId = useGameStore(s => s.sessionId)
  const newChat = () => {
    if (busy) return
    if (sessionId && !confirm('开新一卷？当前对话将不再续接。')) return
    void closeSession(sessionId)
    useGameStore.setState({ sessionId: '', messages: [] })
    sessionStorage.removeItem('wuxia_sid')
    sessionStorage.removeItem('wuxia_log')
  }
  return (
    <header>
      <div className="seal">武</div>
      <h1>武侠 · 江湖</h1>
      <span className="sub">新界面</span>
      <div className="spacer"></div>
      <a href="/classic" title="切回经典聊天界面">↩ 经典界面</a>
      <button id="newchat" onClick={newChat}>新对话</button>
    </header>
  )
}

import { useEffect } from 'react'
import { useGameStore } from './store'
import { Header } from './components/Header'
import { TabsNav } from './components/TabsNav'
import { Gate } from './components/Gate/Gate'
import { Travel } from './components/Travel/Travel'
import { PartySidebar } from './components/Party/PartySidebar'
import { Toaster } from './components/Toaster'
import { CardPanel } from './components/Tabs/CardPanel'
import { UiModal } from './components/Modals/UiModal'
import { CreateWizard } from './components/Wizard/CreateWizard'
import { BattleScreen } from './components/Battle/BattleScreen'

/**
 * dsh view tab 适配版 App。
 * 与独立 webui 的 App 区别：
 * - 不切 document.body class（dsh 外壳的 body 不能被改），改用 wrapper div 的 gate/battle class
 * - 不用 app-shell（dsh view tab 自带容器），直接渲染 main + 弹窗
 */
export default function App() {
  const gateMode = useGameStore(s => s.gateMode)
  const activeTab = useGameStore(s => s.activeTab)
  const inBattle = useGameStore(s => s.inBattle)
  const boot = useGameStore(s => s.boot)

  useEffect(() => {
    boot()
  }, [boot])

  const cls = ['wuxia-root']
  if (gateMode) cls.push('gate')
  if (inBattle) cls.push('battle')

  return (
    <div className={cls.join(' ')}>
      <Header />
      <main>
        <TabsNav />
        <section className="center">
          {gateMode ? (
            <Gate />
          ) : activeTab === 'travel' ? (
            <Travel />
          ) : (
            <div id="panelCard" className="show">
              <CardPanel />
            </div>
          )}
        </section>
        <PartySidebar />
      </main>
      <Toaster />
      <UiModal />
      <CreateWizard />
      <BattleScreen />
    </div>
  )
}

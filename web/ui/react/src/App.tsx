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

export default function App() {
  const gateMode = useGameStore(s => s.gateMode)
  const activeTab = useGameStore(s => s.activeTab)
  const inBattle = useGameStore(s => s.inBattle)
  const boot = useGameStore(s => s.boot)

  useEffect(() => {
    boot()
  }, [boot])

  // game.css 用 body.gate / body.battle 选择器，需切 document.body 的 class
  useEffect(() => {
    document.body.classList.toggle('gate', gateMode)
    document.body.classList.toggle('battle', inBattle)
  }, [gateMode, inBattle])

  return (
    <div className="app-shell">
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

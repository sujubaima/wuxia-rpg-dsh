/* ================= 启动 =================
   有当前档 → 直进主界面；无 → 入门厅（建档/读档流程）。 */
renderTabs();showTab();loadLog();
/* 演武场测试战接线：fight-lab 跳转前暂存 SSE 里未被渲染的界面事件，
   本页启动一律经 routeUi 统一路由（不只是 battle-ui——新界面跟着路由表自然生效）。 */
let _pendingBattle=null;
try{
  const pb=sessionStorage.getItem('wuxia_pending_battle');
  if(pb){
    sessionStorage.removeItem('wuxia_pending_battle');
    _pendingBattle=JSON.parse(pb);
  }
}catch(e){}
/* 有暂存战斗时跳过 enterGame 的 refreshParty——否则「返回游戏」go 异步返回的
   exploration-ui 会在战斗接管后到达，经 routeUi 触发 exitBattle 把战斗退掉。 */
if(_pendingBattle){
  gateMode=false;
  document.body.classList.remove('gate');
  document.getElementById('gateTop').style.display='none';
}else if(currentSlot>0){enterGame();}
else{enterGate();}
if(_pendingBattle){routeUi(_pendingBattle);}
$input.focus();


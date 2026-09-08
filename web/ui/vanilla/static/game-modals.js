/* ================= 功能弹窗（trade-buy/trade-sell/travel/inn）=================
   这四个界面由 engine go 返回（玩家自然语言表达功能意图→GM 调 go→state 事件回传）。
   routeUi 收到对应 界面 值即弹本窗；窗内操作按钮直调 engineGo 做机制结算，
   结果（exploration-ui 等）经 handleStateEvent→routeUi 自然接管。
   场景要素行的特殊指令快捷按钮（elemCmdGo，在 game-explore.js）亦复用本弹窗。*/
const $modUi=document.getElementById('modUi');
const $modUiTitle=document.getElementById('modUiTitle');
const $modUiBody=document.getElementById('modUiBody');
document.getElementById('modUiClose').onclick=closeUiModal;
$modUi.addEventListener('click',e=>{if(e.target===$modUi)closeUiModal();});

function openUiModal(kind,d){
  const cfg=UI_MODALS[kind];
  if(!cfg){closeUiModal();return false;}
  const sub=cfg.sub(d);
  $modUiTitle.innerHTML=cfg.title(d)+(sub?` <span class="ui-sub">${esc(sub)}</span>`:'');
  $modUiBody.innerHTML='';
  cfg.build(d,$modUiBody);
  $modUi.classList.add('show');
  return true;
}
function closeUiModal(){$modUi.classList.remove('show');$modUiBody.innerHTML='';}

/* 弹窗内操作：调 engineGo 结算，结果交 routeUi 接管；成功后关弹窗 */
async function uiModalGo(action,opts){
  opts=opts||{};
  try{
    /* 进度/结算变更均不弹 toast——仅保留错误/异常与 message-ui 提示 */
    const d=await engineGo([action]);
    const fails=(d.结算||[]).filter(r=>r&&r.ok===false);
    if(d.错误||fails.length){addSysLine('操作未成功：'+(d.错误||fails.map(r=>r.msg).join('；')));return;}
    const routed=routeUi(d,{from:'modal'});
    if(routed){closeUiModal();return;}      // 已路由到新界面（exploration-ui/再次弹窗）→ 关旧窗
    if(d.界面){closeUiModal();return;}       // 其它带界面返回也关窗
    /* 无界面（go 已结算落盘，需 GM judge 推演）→ 关弹窗，发隐藏指令通知 GM 据已落盘状态 judge */
    closeUiModal();
    notifyGmJudge(action,d);
  }catch(e){addSysLine('调用失败：'+e);}
}

/* go 返回无界面（交 GM judge）时，发隐藏 chat 指令通知 GM：该动作 go 已由前端结算落盘，
   请直接据 go 返回的已落盘状态下调 engine judge 写剧情，不要再调 go（避免重复结算）。
   d 为 go 返回（带 当前位置/区域场景 等供 GM 设计剧情/移动）。 */
function notifyGmJudge(action,d){
  const t=action&&action.类型;
  let intent;
  if(t==='远行（舟车）')intent=`远行前往${action.目的地||'目的地'}`;
  else if(t==='休息')intent=`休息（${action.等级||''}，${action.时长||''}刻${action.免费?'，免费':''}）`;
  else if(t==='攻击')intent='发起攻击';
  else if(t==='休息')intent=`休息${action.时长||''}刻`;
  else if(t==='交谈观察')intent='交谈观察';
  else intent=t||'行动';
  const pos=d.当前位置||'';
  const lines=[
    `【系统：前端已直调 engine go 结算】玩家执行「${intent}」，engine go 已结算落盘（不要再调 go，直接调 engine judge）。`,
    `go 返回状态：当前位置 ${pos||'—'}，时辰 ${d.时间||'—'}，体力 ${d.体力!=null?d.体力:'—'}。`,
    `请据此下调 engine judge（顶层 当前剧情/场景要素/经历概括，槽位用 ${currentSlot}），写本回合剧情并落盘，渲染 exploration-ui。`,
  ];
  send(lines.join('\n'),{hidden:true});
}

const UI_MODALS={
  'trade-buy-ui':{
    title:d=>`购买 · ${esc(d.卖家||'')}${d.商人?' （商人）':''}`,
    sub:d=>`金钱 ${fmtMoney(d.金钱)}`,
    build(d,body){
      const rows=(d.货架||[]).map(it=>{
        const buy=el('button','row-btn','购买');
        buy.onclick=()=>{
          const n=prompt(`购买 ${it.名称} 数量（默认1）：`,'1');
          const cnt=parseInt(n,10);if(!cnt||cnt<1)return;
          uiModalGo({"类型":"购买","卖家":d.卖家,"物品":it.名称,"数量":cnt,
            "商人":!!d.商人,"价格":it.价格,"买家":d.买家},
            {narrate:`购买 ${it.名称}×${cnt}…`});
        };
        if(d.金钱!=null&&it.价格!=null&&parseInt(d.金钱,10)<parseInt(it.价格,10)){
          buy.classList.add('dis');buy.textContent='金钱不足';buy.title='金钱不足，无法购买';
        }
        return [`<span class="rt-name">${esc(it.名称||'')}</span>`,`×${it.数量??1}`,
          fmtMoney(it.价格),esc(it.类型||''),esc(it.子类型||'—'),esc(it.品名||(it.品级??'')),buy];
      });
      body.appendChild(rows.length?uiTable(['物品','数量','价格','类型','子类型','品级',''],rows)
        :el('div','ui-empty',`${d.卖家||''}暂无可售物品`));
    }
  },
  'trade-sell-ui':{
    title:d=>`出售 · ${esc(d.买家||'')}${d.商人?' （商人）':''}`,
    sub:d=>`金钱 ${fmtMoney(d.金钱)}`,
    build(d,body){
      const rows=(d.可售物品||[]).map(it=>{
        const sell=el('button','row-btn','出售');
        sell.onclick=()=>{
          const n=prompt(`出售 ${it.名称} 数量（默认1）：`,'1');
          const cnt=parseInt(n,10);if(!cnt||cnt<1)return;
          uiModalGo({"类型":"出售","买家":d.买家,"物品":it.名称,"数量":cnt,
            "商人":!!d.商人,"价格":it.价格,"卖家":d.卖家},
            {narrate:`出售 ${it.名称}×${cnt}…`});
        };
        return [`<span class="rt-name">${esc(it.名称||'')}</span>`,`×${it.数量??1}`,
          fmtMoney(it.价格),esc(it.类型||''),esc(it.子类型||'—'),esc(it.品名||(it.品级??'')),sell];
      });
      body.appendChild(rows.length?uiTable(['物品','数量','估价','类型','子类型','品级',''],rows)
        :el('div','ui-empty','无可售物品'));
    }
  },
  'travel-ui':{
    title:d=>`驿站 · ${esc(d.当前区域||'')}`,
    sub:d=>esc(d.驿站类型||''),
    build(d,body){
      const rows=(d.路线||[]).map(r=>{
        const go=el('button','row-btn','前往');
        go.onclick=()=>uiModalGo({"类型":"远行（舟车）","目的地":r.目的地},
          {narrate:`远行 ${r.目的地}…`});
        return [`<span class="rt-name">${esc(r.目的地||'')}</span>`,
          `${r.耗时}天`,fmtMoney(r.费用),go];
      });
      body.appendChild(rows.length?uiTable(['目的地','耗时','费用',''],rows)
        :el('div','ui-empty','此驿站暂无直达路线，需经他处换乘'));
    }
  },
  'inn-ui':{
    title:d=>`客栈 · ${esc(d.场景||'')}`,
    sub:d=>`金钱 ${fmtMoney(d.金钱)}（固定4时辰/32刻）`,
    build(d,body){
      const pct={0.15:'上限15%',0.2:'上限20%',0.25:'上限25%'};
      const rows=(d.等级||[]).map(r=>{
        const fee=(r.每刻单价||0)*(r.时长||32);
        const stay=el('button','row-btn','休息');
        stay.onclick=()=>uiModalGo({"类型":"休息","等级":r.等级,"时长":r.时长||32,"免费":false},
          {narrate:`休息（${r.等级}）…`});
        if(d.金钱!=null&&fee>0&&parseInt(d.金钱,10)<fee){
          stay.classList.add('dis');stay.textContent='金钱不足';stay.title='金钱不足，无法休息';
        }
        return [`<span class="rt-name">${esc(r.等级||'')}</span>`,`${r.每刻单价||0}钱/刻`,
          `${r.体力每时辰||0}/时辰`,esc(pct[r.气血内力比例]||('上限'+(r.气血内力比例||0))),fmtMoney(fee),stay];
      });
      body.appendChild(rows.length?uiTable(['等级','每刻单价','体力/时辰','气血内力/时辰','费用(32刻)',''],rows)
        :el('div','ui-empty','无可休息等级'));
      body.appendChild(el('div','ui-foot','休息结算后由 GM 承接休息剧情。差等级（露宿）不经此界面。'));
    }
  }
};

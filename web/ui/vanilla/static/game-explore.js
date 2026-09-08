/* ================= 中央场景视图（游历） =================
   exploration-ui 结构化渲染：抬头带（地点/时辰）+ 叙事 + 状态变更徽章
   + 场景要素 chips + 八向罗盘。数据来自 SSE state / TAB 直调返回。
   配置类 go 的 exploration-ui 无剧情/要素/出口——只刷右栏，不重绘场景面板。 */
const HB_ICON={"白天":"☀","清晨":"☀","傍晚":"☾","夜晚":"☾"};
const C_DIRS=[["西北","北","东北"],["西","","东"],["西南","南","东南"]];
let inBattle=false;
let lastExpl=null;

/* 场景要素特殊指令 → 快捷直调 engineGo 弹对应功能界面。
   cmd 为 go 行为名（购买/出售/远行（舟车）/休息），主体为该要素主体名。
   商人身份据当前场景类型：店铺/客栈=货架商人交易，其余（山野小贩等）=个人交易。 */
async function elemCmdGo(cmd,subject,merchant){
  let action;
  if(cmd==='购买')action={"类型":"购买","卖家":subject,"商人":merchant};
  else if(cmd==='出售')action={"类型":"出售","买家":subject,"商人":merchant};
  else if(cmd==='远行（舟车）')action={"类型":"远行（舟车）"};
  else if(cmd==='休息'||cmd==='投宿')action={"类型":"休息","免费":false};
  else{return;}
  try{
    /* 进度/结算变更均不弹 toast——仅保留错误/异常与 message-ui 提示 */
    const d=await engineGo([action]);
    const fails=(d.结算||[]).filter(r=>r&&r.ok===false);
    if(d.错误||fails.length){addSysLine('操作未成功：'+(d.错误||fails.map(r=>r.msg).join('；')));return;}
    if(routeUi(d,{from:'elemcmd'}))return;  // 命中 trade/travel/inn-ui → 弹窗；exploration-ui → 刷新
    /* 无界面（go 已结算，需 GM judge）→ 通知 GM 据已落盘状态 judge */
    notifyGmJudge(action,d);
  }catch(e){addSysLine('调用失败：'+e);}
}
function setBattleMode(b){
  inBattle=!!b;
  document.body.classList.toggle('battle',inBattle);
}
/* ================= 引擎界面统一路由 =================
   任何 engine go/judge 返回（SSE state / TAB 直调 / 演武场暂存）一律经这张表
   决定前台动作，调用点不各自写 界面 判断；新引擎界面未来只在此加 case。*/
function routeUi(d,ctx){
  if(!d||typeof d!=='object')return false;
  syncSlot(d);
  ctx=ctx||{};
  switch(d.界面){
    case 'battle-ui':          // 战斗中（含战斗-推进/战斗-开始产出）：全屏接管
    case 'battle-end-ui':      // 我方胜终局：全屏接管+处决裁定遮罩
      enterBattle(d);
      return true;
    case 'exploration-battle-ui':  // 战前：先出剧情 card，点击后才出操控选择面板
      showPreFightNarration(d);
      return true;
    case 'exploration-ui':     // 大世界：退出战斗（若在）、刷场景与队伍
      if(inBattle)exitBattle('auto');
      applyExplorationState(d);
      renderParty(d);
      if(ctx.showExpl)addGmBlockText(d.界面渲染||composeExploration(d));
      return true;
    case 'message-ui':         // 提示界面：弹出显眼 toast，内容取返回的 提示 字段；新提示替换旧 warn toast
      if(d.提示)addSysLine(d.提示,{long:true,cls:'warn',replace:true});
      return true;
    case 'trade-buy-ui':       // 购买货架：弹窗选购
    case 'trade-sell-ui':      // 出售估价：弹窗售物
    case 'travel-ui':          // 驿站出行：弹窗选目的地
    case 'inn-ui':             // 客栈休息：弹窗选等级
      return openUiModal(d.界面,d);
    default:
      return false;            // 未收编界面：由调用点各自渲染（title/save/map/…的 TAB）
  }
}
function handleStateEvent(d){routeUi(d,{from:'sse'});}
function applyExplorationState(d){
  if(!d||d.界面!=='exploration-ui')return;
  const pt=document.getElementById('panelTravel');if(pt)pt.classList.remove('working');
  const pos=d.当前位置||'';
  const parts=pos.split('·');
  document.getElementById('hbRegion').textContent=parts.length>1?parts[0]:'—';
  const sceneName=parts.length>1?parts[1]:(pos||'待 启 程');
  /* 地点变更时地名从右侧轻划入（上一帧名≠本次名） */
  if(prevSceneKey!==null&&prevSceneKey!==sceneName){
    const loc=document.querySelector('.hb-loc');
    if(loc){loc.classList.remove('flip');void loc.offsetWidth;loc.classList.add('flip');}
  }
  document.getElementById('hbScene').textContent=sceneName.split('').join(' ');
  document.getElementById('hbClock').textContent=d.时段||'';
  document.getElementById('hbIcon').textContent=HB_ICON[d.时段]||'◐';
  document.getElementById('hbCal').textContent=d.时间||'';
  const hbSave=document.getElementById('hbSave');
  if(d.剩余==null){hbSave.style.display='none';}
  else{hbSave.style.display='';hbSave.textContent=`距自动存档 ${d.剩余} 轮`;}
  if(d.剧情描写==null&&!(d.场景要素||[]).length&&!(d.相邻出口||[]).length)return;
  /* 防 server 一份探索态两频采收（judge 落盘时+回合收尾各发一次）触发舞台重播入场动画：
     与上次重绘内容指纹一致则跳过重绘（抬头/右栏照常刷新，只跳舞台） */
  /* 防重复重绘哨（指纹不含 结算）：SSE state 与回合收尾、refreshParty 回调都可能各带一份
     同场探索态——但 结算 在 judge 回执与 返回游戏 回执里组成不同（tips 已消费后返回游戏不再带），
     含 结算 的比较会永远不匹配、从而重播。位置/剧情/要素/出口四个回合级因子一致即判同一场。 */
  const sig=(d.当前位置||'')+'|'+(d.剧情描写||'')+'|'+JSON.stringify(d.场景要素||[])+'|'+
    JSON.stringify(d.相邻出口||[]);
  if(sig===_lastStageSig)return;
  _lastStageSig=sig;
  lastExpl=d;
  renderStage(d);
  prevSceneKey=sceneName;
}
/* A1 节奏灯控制：1=结算 2=判盘 3=运笔；0=全开标志位，-1=熄灭 */
let _turnTools=0;
/* 等待面板：GM 运笔期间在游历界面中央显示一个半透明面板，实时打印 SSE 事件流 */
function setSteps(idx){
  const pt=document.getElementById('panelTravel');
  const panel=document.getElementById('waitPanel');
  if(idx>0){
    if(pt)pt.classList.add('working');
    if(panel){panel.classList.add('show');panel.querySelector('.wait-log').innerHTML='';}
    _waitAppend('— 等待 GM 响应 —');
  }else{
    if(pt)pt.classList.remove('working');
    if(panel)panel.classList.remove('show');
  }
}
function _waitAppend(text,detail){
  const panel=document.getElementById('waitPanel');
  if(!panel)return;
  const log=panel.querySelector('.wait-log');
  if(!log)return;
  const line=document.createElement('div');line.className='wait-line';
  if(detail){
    const summary=document.createElement('span');summary.className='wait-summary';
    summary.textContent=text;
    const det=document.createElement('pre');det.className='wait-detail';
    det.textContent=detail;
    det.style.display='none';
    summary.style.cursor='pointer';
    summary.onclick=()=>{const show=det.style.display==='none';
      det.style.display=show?'block':'none';};
    line.appendChild(summary);line.appendChild(det);
  }else{
    line.textContent=text;
  }
  log.appendChild(line);log.scrollTop=log.scrollHeight;
}
/* B1 章节式入场助理：给节点配 nfp 入场动画递增延时 */
function makeEnter(delay){
  return (nd)=>{
    nd.classList.add('nfp');
    nd.style.animationDelay=(delay.t.toFixed(2)+'s');
    delay.t+=delay.step;
    return nd;
  };
}
let prevSceneKey=null,_lastStageSig='',_stageExpanded=false;
function renderStage(d){
  const box=document.getElementById('stageIn');
  box.innerHTML='';
  const enter=makeEnter({t:0.08,step:0.11});
  /* 第一阶段：只渲染剧情叙事 + 状态变更（一张 card），隐藏要素/罗盘/聊天框 */
  _stageExpanded=false;
  /* 归一换行：GM 偶把 \n 当转义符直传（字面两字符）而非真换行，统一转成真换行再渲染 */
  const nar=(d.剧情描写==null?'':String(d.剧情描写).replace(/\\n/g,'\n')).trim();
  if(nar){
    const nd=document.createElement('div');nd.className='narration';
    /* 连续空行分段，单换行转 <br> 行内换行 */
    for(const para of nar.split(/\n{2,}/).map(s=>s.trim()).filter(Boolean)){
      const p=document.createElement('p');
      p.innerHTML=renderInline(para).replace(/\n/g,'<br>');
      enter(p);
      nd.appendChild(p);
    }
    box.appendChild(nd);
  }
  const chgs=(d.结算||[]) .map(r=>r&&r.变更).filter(Boolean);
  if(chgs.length){
    const cw=document.createElement('div');cw.className='changes';
    for(const v of chgs){
      const s=document.createElement('span');
      s.className='chg'+(/体力-|气血-|内力-/.test(v)?' hurt':'');
      s.textContent=v;
      enter(s);
      cw.appendChild(s);
    }
    box.appendChild(cw);
  }
  /* 点击舞台任意位置展开要素/罗盘/聊天框 */
  const expandHint=document.createElement('div');
  expandHint.className='expand-hint';
  expandHint.textContent='点击此处继续…';
  box.appendChild(expandHint);
  const stg=document.getElementById('stage');
  stg.classList.add('awaiting-click');
  const composer=document.getElementById('composer');
  if(composer)composer.style.display='none';
  const logEl=document.getElementById('travelLog');
  if(logEl)logEl.style.display='none';
  stg.onclick=()=>{if(_stageExpanded)return;expandStage(d,enter,box,expandHint);};
  stg.scrollTop=stg.scrollHeight;
}
function expandStage(d,enter,box,expandHint){
  _stageExpanded=true;
  const stg=document.getElementById('stage');
  stg.classList.remove('awaiting-click');
  stg.onclick=null;
  if(expandHint&&expandHint.parentNode)expandHint.remove();
  /* 显示聊天框 + 足迹 */
  const composer=document.getElementById('composer');
  if(composer)composer.style.display='';
  const logEl=document.getElementById('travelLog');
  if(logEl)logEl.style.display='';
  /* 渲染要素 + 罗盘；出口行（{方位}（通往XX））由八向罗盘展示，周围情况列表不再重复列出 */
  const DIR_RE=/^(西北|北|东北|西|东|西南|南|东南)（通往.+）$/;
  /* 场景要素归一化为 {主体, 描写, 特殊指令?}：兼容对象与旧版 "主体（描写）" 字符串。
     特殊指令为对象数组 [{名称,可用}]，可用为 bool（GM 据场景判断；不可用时置灰禁用）。 */
  const normEl=f=>{
    if(f&&typeof f==='object'&&f!==null){
      const raw=f.特殊指令;
      const cmds=Array.isArray(raw)
        ? raw.filter(c=>c&&typeof c==='object'&&typeof c.名称==='string'&&c.名称.trim()&&typeof c.可用==='boolean')
            .map(c=>({名称:String(c.名称).trim(),可用:Boolean(c.可用)}))
        : null;
      return {主体:f.主体||'', 描写:f.描写||'', 特殊指令:cmds&&cmds.length?cmds:null};
    }
    const s=String(f||'').trim();
    if(!DIR_RE.test(s)&&s.includes('（')){
      const i=s.indexOf('（');return {主体:s.slice(0,i).trim(), 描写:s.slice(i+1).replace(/）$/,'').trim(), 特殊指令:null};
    }
    return {主体:s, 描写:'', 特殊指令:null};
  };
  const els=(d.场景要素||[]).map(normEl).filter(f=>f.主体&&!DIR_RE.test(f.主体+'（'+f.描写+'）'));
  if(els.length){
    const t=document.createElement('div');t.className='sc-title';t.textContent='周 围 情 况';
    enter(t);
    box.appendChild(t);
  }
  const srow=document.createElement('div');srow.className='scrow';
  const scol=document.createElement('div');scol.className='sc-col';
  if(els.length){
    const list=document.createElement('div');list.className='sc-list';
    for(const f of els){
      const e=document.createElement('div');e.className='sc-elem';
      const dot=document.createElement('span');dot.className='dot';dot.textContent='◆';
      const label=f.描写?(f.主体+'（'+f.描写+'）'):f.主体;
      const tx=document.createElement('span');tx.innerHTML=renderInline(label);
      e.appendChild(dot);e.appendChild(tx);
      /* 行后追加特殊指令快捷按钮：点击直调 engineGo 弹对应功能界面（trade/travel/inn） */
      if(f.特殊指令){
        const btns=document.createElement('span');btns.className='sc-cmds';
        const merchant=(d.当前场景类型==='店铺'||d.当前场景类型==='客栈');
        for(const cmd of f.特殊指令){
          const labelMap={'购买':'购买','出售':'出售','远行（舟车）':'远行','休息':'休息','投宿':'投宿'};
          const b=document.createElement('button');b.className='sc-cmd';
          b.textContent=labelMap[cmd.名称]||cmd.名称;
          if(!cmd.可用){
            b.disabled=true;b.title='当前不可用';
          }else{
            b.onclick=(ev=>{ev.stopPropagation();elemCmdGo(cmd.名称,f.主体,merchant);});
          }
          btns.appendChild(b);
        }
        e.appendChild(btns);
      }
      e.title='填入对话指令';
      e.onclick=()=>{const inp=document.getElementById('input');
        inp.value='与'+f.主体+'交谈';inp.focus();};
      enter(e);
      list.appendChild(e);
    }
    scol.appendChild(list);
  }
  srow.appendChild(scol);
  renderCompass(srow,d.相邻出口||[],enter);
  box.appendChild(srow);
  stg.scrollTop=stg.scrollHeight;
}
function renderCompass(box,exits,enter){
  const exitMap={};
  for(const e of exits)if(e&&e.方位)exitMap[e.方位]=e.邻场景;
  const n=Object.keys(exitMap).length;
  const wrap=document.createElement('div');wrap.className='compass-wrap';
  const cp=document.createElement('div');cp.className='compass';
  for(const row of C_DIRS)for(const dir of row){
    if(dir===""){
      const c=document.createElement('div');c.className='ccell here';
      const nm=document.createElement('span');nm.className='nm';
      nm.textContent='◈ '+(lastExpl&&lastExpl.当前位置?lastExpl.当前位置.split('·').pop():'');
      c.appendChild(nm);cp.appendChild(c);continue;
    }
    const c=document.createElement('div');
    const dd=document.createElement('span');dd.className='dir';dd.textContent=dir;
    const nm=document.createElement('span');nm.className='nm';
    if(exitMap[dir]){
      c.className='ccell exit';nm.textContent=exitMap[dir];
      c.title='填入移动指令';
      c.onclick=()=>{const inp=document.getElementById('input');
        inp.value='前往'+exitMap[dir];inp.focus();};
    }else{
      c.className='ccell fog';nm.textContent='未知';
    }
    c.appendChild(dd);c.appendChild(nm);
    if(enter)enter(c);
    cp.appendChild(c);
  }
  wrap.appendChild(cp);
  const note=document.createElement('div');note.className='cnote';
  note.innerHTML=`已开启出口 <b>${n}</b> 方；<br>点方位格即可填指令。`;
  wrap.appendChild(note);
  box.appendChild(wrap);
}


/* ================= 本地系统提示（TAB 写操作回执，不入 LLM 上下文） ================= */
const LOG_KEY='wuxia_log';
/* 系统提示：短暂 toast（右下角），不入聊天流、不入日志 */
function _toastWrap(){return document.getElementById('toastWrap');}
function addSysLine(text,opts){
  let w=_toastWrap();
  if(!w){w=document.createElement('div');w.id='toastWrap';document.body.appendChild(w);}
  const o=(typeof opts==='object'&&opts)?opts:{};
  /* o.replace：新提示替换同类旧提示（避免连续 message-ui 时旧 toast 堆叠遮挡新提示） */
  if(o.replace&&o.cls){
    w.querySelectorAll('.toast.'+o.cls).forEach(x=>x.remove());
  }
  const t=el('div','toast'+(o.cls?' '+o.cls:''),text);
  w.appendChild(t);
  requestAnimationFrame(()=>t.classList.add('show'));
  /* o.long：错误/异常类提示留长一些（默认 2.6s 容易漏看） */
  const ms=o.long?7000:2600;
  setTimeout(()=>{t.classList.remove('show');t.classList.add('out');
    setTimeout(()=>t.remove(),300);},ms);
}
/* 本地渲染探索界面到游历流（建号/读档等无 LLM 场景的首屏；持久化进 log） */
function addGmBlockText(text){
  if(!text)return;
  const bub=addRow('assistant','');
  if(!bub._segs)bub._segs=[];
  const seg={kind:'text',text};
  bub._segs.push(seg);pushMd(bub,seg);
  seg._el.innerHTML=render(seg.text);
  try{
    const log=JSON.parse(sessionStorage.getItem(LOG_KEY)||'[]');
    log.push({role:'assistant',segs:[{kind:'text',text}]});
    sessionStorage.setItem(LOG_KEY,JSON.stringify(log));
  }catch(e){}
}
function composeExploration(d){
  const lines=[];
  lines.push((`### 【${(d.当前位置||'').replace('·',' · ')}】 ${d.时段||''} ${d.时间||''}`).trim(),'');
  if(d.剧情描写)lines.push(d.剧情描写,'');
  for(const r of (d.结算||[]))if(r&&r.变更)lines.push('`'+r.变更+'`');
  lines.push('');
  const els=d.场景要素||[],exits=d.相邻出口||[];
  if(els.length||exits.length){
    lines.push('周围情况');
    for(const e of els)lines.push('- '+e);
    for(const e of exits)lines.push(`- ${e.方位}（通往${e.邻场景}）`);
    lines.push('');
  }
  const ms=(d.队伍状态||[]).map(m=>`- \`${m.名称}\` 气血(${m.气血}/${m.气血上限}) 内力(${m.内力}/${m.内力上限})`);
  if(ms.length)lines.push(`当前队伍 体力${d.体力??'—'} 金钱${fmtMoney(d.金钱)}`,...ms);
  return lines.join('\n');
}
function showExploration(d){
  routeUi(d,{showExpl:true});          /* 与全局路由共享一处动作，不重复渲染 */
}

/* ================= 面板操作锁 =================
   写操作飞行中禁用全部面板按钮，防重复点击；refresh 重建出的新按钮同样有
   cardBusy 守卫（重复的 uiOp 直接丢弃）。 */
let cardBusy=false;
function setCardButtons(enabled){
  for(const b of document.querySelectorAll('#panelCard .uibtn'))b.disabled=!enabled;
}

/* 写操作统一出口：结算回执→系统行；exploration-ui→直刷右栏 */
async function uiOp(action,opts){
  opts=opts||{};
  if(cardBusy)return null;
  if(opts.confirm&&!confirm(opts.confirm))return null;
  cardBusy=true;setCardButtons(false);
  try{
    /* 进度/结算变更均不弹 toast——仅保留错误/异常与 message-ui 提示 */
    let d;
    try{d=await engineGo([action],opts.slot);}
    catch(e){addSysLine('调用失败：'+e);return null;}
    const fails=(d.结算||[]).filter(r=>r&&r.ok===false);
    if(d.错误||fails.length){
      const cause=d.错误||fails.map(r=>r.msg).join('；');
      addSysLine('操作未成功：'+cause);
    }
    if(!d.界面&&!d.错误){addSysLine('该动作 go 未返回界面，按规则须走 judge 推演，'
      +'面板不提供此入口——请到游历流用自然语言下达该指令（由 GM 结算）。');}
    const routed=routeUi(d,{from:'tab',showExpl:opts.showExpl});
    /* 未路由的界面（title/save/map 等 TAB 内部渲染）：不调 refreshParty（不发 返回游戏），
       右栏由 SSE state 或下次页面刷新自然同步 */
    if(opts.refresh){try{await opts.refresh();}catch(e){}}
    else if(opts.reload!==false)loadTabView();
    return d;
  }finally{
    cardBusy=false;setCardButtons(true);
  }
}

/* ================= TAB 框架 ================= */
const TABS=[
  {key:'travel',label:'游历'},
  {key:'bag',   label:'物品'},
  {key:'equip', label:'装备'},
  {key:'wuxue', label:'武学'},
  {key:'map',   label:'地图'},
  {key:'clue',  label:'线索'},
  {key:'char',  label:'角色'},
  {key:'save',  label:'存档'},
];
let activeTab='travel';
const $tabs=document.getElementById('tabs');
const $travel=document.getElementById('panelTravel');
const $card=document.getElementById('panelCard');
function renderTabs(){
  $tabs.innerHTML='';
  for(const t of TABS){
    const d=el('div','tab'+(t.key===activeTab?' active':''),t.label);
    d.onclick=()=>{
      if(t.key==='title'){enterGate();return;}   /* 标题=回门厅 */
      activeTab=t.key;showTab();
    };
    $tabs.appendChild(d);
  }
}
function showTab(){
  renderTabs();
  if(activeTab==='travel'){$travel.classList.remove('hide');$card.classList.remove('show');scrollDown();}
  else{$travel.classList.add('hide');$card.classList.add('show');loadTabView();}
}
function loadTabView(){
  const fn=TAB_VIEWS[activeTab];
  $card.innerHTML='';
  if(fn)fn();else $card.appendChild(el('div','ph','该面板尚未实现。'));
}

/* ================= M2 各功能面板 ================= */
function cardShell(title,desc){
  const wrap=el('div');
  if(desc)wrap.appendChild(el('div','cdesc',desc));
  const c=el('div','card');c.appendChild(el('h3',null,title));
  wrap.appendChild(c);$card.appendChild(wrap);
  return c;
}
function dumpJson(c,d){c.appendChild(el('pre','jsonout',JSON.stringify(d,null,2).slice(0,6000)));}

async function fetchUi(action,dflt){
  try{return await engineGo([action]);}catch(e){return {错误:String(e)};}
}

/* ---------- 物品（bag-ui + 战斗携带 item-ui） ---------- */
/* 一级类型→二级子类型映射（取自 assets/data/items；无子类型的类型列空数组）。
   二级留空则仅按一级筛选。 */
const TYPE_SUBS={
  '武器':['刀','剑','奇门','搏击','暗器','长兵'],
  '消耗品':['丹药','食物','心法秘籍','刀法秘籍','剑法秘籍','奇门秘籍','搏击秘籍','暗器秘籍','长兵秘籍','技艺书','道具'],
  '护甲':[],'冠巾':[],'饰品':[]
};
async function loadBag(){
  const c=cardShell('物品','');
  const bar=el('div');bar.style.margin='0 0 8px';
  const sel=el('select','uibtn');
  for(const t of ['','武器','消耗品','护甲','冠巾','饰品']){
    const o=el('option');o.value=t;o.textContent=t||'全部类型';sel.appendChild(o);
  }
  const sub=el('select','uibtn');
  function fillSub(){
    sub.innerHTML='';
    const o=el('option');o.value='';o.textContent='全部子类型';sub.appendChild(o);
    const subs=TYPE_SUBS[sel.value]||[];
    for(const s of subs){const o2=el('option');o2.value=s;o2.textContent=s;sub.appendChild(o2);}
    sub.disabled=!sel.value||subs.length===0;
  }
  sel.onchange=fillSub;
  fillSub();
  bar.appendChild(el('span','muted','类型 '));bar.appendChild(sel);
  bar.appendChild(el('span','muted',' 子类型 '));bar.appendChild(sub);
  const holder1=el('div');
  const h4=el('h4',null,'战斗携带（≤4类，战斗内可用消耗品）');
  const holder2=el('div');
  async function queryBag(){
    const a={"类型":"查看背包"};
    if(sel.value)a.筛选类型=sel.value;
    if(sel.value&&sub.value)a.筛选子类型=sub.value;
    const d=await fetchUi(a);
    holder1.innerHTML='';
    if(d.错误){dumpJson(holder1,d);return;}
    renderBagRows(holder1,d,refresh);
  }
  async function autoQuery(){
    if(cardBusy)return;
    cardBusy=true;setCardButtons(false);
    try{await queryBag();}finally{cardBusy=false;setCardButtons(true);}
  }
  async function queryCarry(){
    renderCarryInto(holder2,await fetchUi({"类型":"配置物品"}),refresh);
  }
  async function refresh(){await queryBag();await queryCarry();}
  const reBtn=uiBtn('查询');
  reBtn.onclick=autoQuery;
  bar.appendChild(document.createTextNode(' '));bar.appendChild(reBtn);
  c.appendChild(bar);c.appendChild(holder1);c.appendChild(h4);c.appendChild(holder2);
  await refresh();
}
function _effText(e){return e==null?'':(typeof e==='string'?e:JSON.stringify(e));}
function renderBagRows(holder,d,refresh){
  const rows=[];
  for(const it of (d.物品列表||[])){
    const usable=/世界|通用/.test(it.适用场合||'');
    const ops=el('span');
    if(usable){const b=uiBtn('使用');
      b.onclick=()=>uiOp({"类型":"使用物品","物品":it.名称},{refresh});
      ops.appendChild(b);}
    rows.push([`<b>${esc(it.名称)}</b>`,'×'+(it.数量??1),it.类型||'',it.子类型||'',
      it.品名||'',`<span class="muted">${esc(_effText(it.使用效果))}</span>`,ops]);
  }
  holder.appendChild(rows.length?uiTable(['名称','数量','类型','子类型','品级','效果','操作'],rows)
    :el('div','ph','（空）'));
}
function renderCarryInto(holder,p,refresh){
  holder.innerHTML='';
  if(!p||p.界面!=='item-ui'){holder.appendChild(el('div','ph','（查询战斗携带失败或为空）'));return;}
  const rows=[];
  for(const it of (p.携带道具||[])){
    const b=uiBtn('卸下');
    b.onclick=()=>uiOp({"类型":"配置物品","操作":"卸","物品":it.名称||it},{refresh});
    rows.push([it.名称||it,'×'+(it.数量??1),b]);
  }
  holder.appendChild(rows.length?uiTable(['携带中','数量',''],rows):el('div','ph','（未携带）'));
  if((p.可换道具||[]).length){
    holder.appendChild(el('h4',null,'物品栏可换消耗品'));
    const rows2=[];
    for(const it of p.可换道具){
      const b=uiBtn('装上');
      b.onclick=()=>uiOp({"类型":"配置物品","操作":"装","物品":it.名称||it},{refresh});
      rows2.push([it.名称||it,'×'+(it.数量??1),b]);
    }
    holder.appendChild(uiTable(['名称','数量',''],rows2));
  }
}

/* ---------- 装备（equip-ui） ---------- */
const EQUIP_SLOTS=['武器1','武器2','护甲','饰品','冠巾'];
const WEAPON_SUBS={'刀':1,'剑':1,'奇门':1,'搏击':1,'暗器':1,'长兵':1};
function slotOfSub(sub){return {护甲:'护甲',饰品:'饰品',冠巾:'冠巾'}[sub]||null;}
async function loadEquip(){
  const c=cardShell('装备','');
  const holder=el('div');c.appendChild(holder);
  async function refresh(){
    const d=await fetchUi({"类型":"配置装备"});
    holder.innerHTML='';
    if(d.错误){dumpJson(holder,d);return;}
    renderEquipInto(holder,d,refresh);
  }
  await refresh();
}
function renderEquipInto(holder,d,refresh){
  const row=el('div','slotrow');
  for(const s of EQUIP_SLOTS){
    const sc=el('div','slotcard');
    sc.appendChild(el('div','sl',s));
    const cur=(d.当前装备||{})[s];
    sc.appendChild(el('div','eq',cur||'（空）'));
    if(cur){const b=uiBtn('卸下');
      b.onclick=()=>uiOp({"类型":"配置装备","操作":"脱","槽位":s},{refresh});
      sc.appendChild(b);}
    row.appendChild(sc);
  }
  holder.appendChild(row);
  holder.appendChild(el('h4',null,'物品栏可换装备'));
  const avail=d.可换装备||[];
  if(!avail.length){holder.appendChild(el('div','ph','（无可换装备）'));return;}
  const rows=[];
  for(const it of avail){
    const ops=el('span');
    const isWeapon=it.类型==='武器'||WEAPON_SUBS[it.子类型];
    if(isWeapon){
      for(const ws of ['武器1','武器2']){
        const b=uiBtn('装到'+ws);
        b.onclick=()=>uiOp({"类型":"配置装备","操作":"穿","槽位":ws,"物品":it.名称},{refresh});
        ops.appendChild(b);ops.appendChild(document.createTextNode(' '));
      }
    }else{
      const sl=it.类型&&EQUIP_SLOTS.includes(it.类型)?it.类型:slotOfSub(it.子类型);
      const b=uiBtn('穿上');
      if(sl)b.onclick=()=>uiOp({"类型":"配置装备","操作":"穿","槽位":sl,"物品":it.名称},{refresh});
      else b.disabled=true;
      ops.appendChild(b);
    }
    rows.push([`<b>${esc(it.名称)}</b>`,(it.类型||'')+(it.子类型?'·'+it.子类型:''),it.品名||'',ops]);
  }
  holder.appendChild(uiTable(['名称','类型','品级','操作'],rows));
}

/* ---------- 武学（wuxue-ui + wuxue-list-ui + mastery-ui） ---------- */
async function loadWuxue(){
  const c=cardShell('武学','');
  const holder=el('div');c.appendChild(holder);
  async function refresh(){
    const d=await fetchUi({"类型":"配置武学"});
    const mainName=(lastExpl&&lastExpl.队伍状态&&lastExpl.队伍状态[0]
      &&lastExpl.队伍状态[0].名称)||null;
    const listD=await fetchUi(mainName?{"类型":"武学列表","角色":mainName}:{"类型":"武学列表"});
    holder.innerHTML='';
    if(d.错误){dumpJson(holder,d);return;}
    renderWuxueInto(holder,d,listD,refresh);
  }
  await refresh();
}
function renderWuxueInto(holder,d,listD,refresh){
  const xh=el('div');
  xh.appendChild(el('span','muted','运转心法：'));
  const xfs=(listD.心法||[]).map(x=>x.名称);
  const sel=el('select','uibtn');
  const optNone=el('option');optNone.value='无';optNone.textContent='（不运转）';sel.appendChild(optNone);
  for(const n of xfs){const o=el('option');o.value=n;o.textContent=n;sel.appendChild(o);}
  sel.value=d.运转心法||'无';
  const setBtn=uiBtn('设定');
  setBtn.onclick=()=>uiOp({"类型":"配置武学","运转心法":sel.value},{refresh});
  xh.appendChild(sel);xh.appendChild(document.createTextNode(' '));xh.appendChild(setBtn);
  if(d.运转心法特效)xh.appendChild(el('div','muted',d.运转心法特效));
  holder.appendChild(xh);
  holder.appendChild(el('h4',null,'携带武学（战斗中可用）'));
  holder.appendChild(skillTable(d.携带武学||[],'carried',listD,refresh,(d.携带武学||[]).length));
  holder.appendChild(el('h4',null,'可用武学（已习得未携带）'));
  holder.appendChild(skillTable(d.可用武学||[],'avail',listD,refresh,(d.携带武学||[]).length));
}
function skillTable(list,kind,listD,refresh,carriedCount){
  if(!list.length)return el('div','ph',kind==='carried'?'（未携带武学）':'（无）');
  const rows=[];
  const masteryOf={};for(const grp of ['主动武学','心法'])for(const e of (listD[grp]||[]))masteryOf[e.名称]=e;
  for(const w of list){
    const ops=el('span');
    if(kind==='carried'){
      const b=uiBtn('卸下');b.onclick=()=>uiOp({"类型":"配置武学","操作":"卸","武学":w.名称},{refresh});
      ops.appendChild(b);
    }else{
      const b=uiBtn('装上');
      if(carriedCount>=4)b.disabled=true;
      b.onclick=()=>uiOp({"类型":"配置武学","操作":"装","武学":w.名称},{refresh});
      ops.appendChild(b);
    }
    ops.appendChild(document.createTextNode(' '));
    const m=uiBtn('精进');
    m.onclick=()=>openMastery(w.名称);
    ops.appendChild(m);
    const meta=masteryOf[w.名称]||{};
    const lv=meta.等级!=null?meta.等级:w.等级;
    rows.push([`<b>${esc(w.名称)}</b>`,lv!=null?`${lv}境`:'',w.品名||meta.品名||'',
      w.威力倍率!=null?('威'+w.威力倍率):'',w.内力消耗!=null?('内'+w.内力消耗):'',
      w.冷却时间!=null?('冷却'+w.冷却时间):'',`<span class="muted">${esc(w.特效||w.描述||'无')}</span>`,ops]);
  }
  return uiTable(['名称','境界','品级','威力','内力','冷却','特效','操作'],rows);
}
async function openMastery(name){
  const c=cardShell('精进 · '+name,'');
  const holder=el('div');c.appendChild(holder);
  async function refresh(){
    const d=await fetchUi({"类型":"武学精进","武学":name});
    holder.innerHTML='';
    if(d.界面!=='mastery-ui'){dumpJson(holder,d);return;}
    holder.appendChild(el('div','ph',`当前 ${d.等级}境 ｜ 经验值 ${d.经验值}`));
    const td=d.十境表数据;
    if(td)holder.appendChild(renderMasteryTable(td));
    else if(d.十境表)holder.appendChild(el('pre','prebox',d.十境表));
    const b=uiBtn('精进一层','primary');
    if(td&&td.可精进===false)b.disabled=true;
    b.onclick=()=>uiOp({"类型":"武学精进","武学":name,"操作":"精进"},{narrate:'消耗经验精进…',refresh});
    holder.appendChild(b);
  }
  await refresh();
}
/* 结构化十境表（engine 十境表数据 字段）→ 表格渲染。 */
function renderMasteryTable(td){
  const wrap=el('div','mastery');
  const head=el('div','m-head');
  const tier=td.品级!=null?('品级'+td.品级):'品级未定';
  head.innerHTML=`<span class="m-name">${esc(td.武学||'')}</span><span class="muted">${esc(tier)} ｜ 精进消耗×${td.品级系数!=null?td.品级系数:'?'}</span>`;
  wrap.appendChild(head);
  const rows=(td.十境||[]).map(r=>{
    const st=el('span','m-st '+(r.已习得?'got':''));
    st.textContent=r.已习得?'✓':'✗';
    const mark=r.当前?'（当前）':(r.下一境?'← 下一境':'');
    const cost=r.境<=1?'—':r.消耗经验;
    return [r.境,st,cost,`<span class="m-eff">${esc(r.增益||'')}</span>${mark?'<span class="m-mark">'+esc(mark)+'</span>':''}`];
  });
  wrap.appendChild(uiTable(['境','状态','消耗经验','增益'],rows));
  const foot=el('div','m-foot');
  if(td.当前境>=10){foot.textContent='已达大成（第 10 境），无可精进之境。';}
  else{
    const need=td.下一境消耗;
    const ok=td.可精进;
    foot.innerHTML=`下一境（第 ${td.下一境} 境）需经验 ${need!=null?need:'?'} ｜ 当前 ${td.经验} ｜ <span class="${ok?'ok':'warn'}">${ok?'可精进':'经验不足，暂无法精进'}</span>`;
  }
  wrap.appendChild(foot);
  return wrap;
}

/* ---------- 地图（map-ui 图形化：用引擎 场景图 自行网格铺设，不再沿用 ASCII 邻接图） ---------- */
const DIR_VEC={'北':[0,-1],'东北':[1,-1],'东':[1,0],'东南':[1,1],'南':[0,1],'西南':[-1,1],'西':[-1,0],'西北':[-1,-1]};
function layoutSceneGraph(adj,cur){
  const pos=new Map(),edges=[];
  if(cur==null||!(cur in adj))cur=Object.keys(adj)[0];
  if(!cur)return {pos,edges};
  const occ=new Set(),key=(x,y)=>x+','+y,parent={};
  pos.set(cur,[0,0]);occ.add(key(0,0));
  const q=[cur];parent[cur]=null;
  while(q.length){
    const a=q.shift();
    const [ax,ay]=pos.get(a);
    for(const dir of Object.keys(DIR_VEC)){
      const b=(adj[a]||{})[dir];
      if(!b)continue;
      if(!pos.has(b)){
        const v=DIR_VEC[dir];let x=ax+v[0],y=ay+v[1],step=0;
        while(occ.has(key(x,y))&&step<40){x+=v[0];y+=v[1];step++;}
        if(step>=40)continue;
        pos.set(b,[x,y]);occ.add(key(x,y));
        parent[b]=a;q.push(b);
        edges.push([a,b]);
      }else if(parent[b]===a){edges.push([a,b]);}
    }
  }
  /* 未连通的已登记孤点：排到最右侧一列陈列 */
  let farX=0;pos.forEach(([x])=>{if(x>=farX)farX=x+2;});
  for(const n in adj)if(!pos.has(n)){pos.set(n,[farX,0]);farX+=2;}
  return {pos,edges};
}
function renderSceneSvg(adj,cur,stationExit){
  const {pos,edges}=layoutSceneGraph(adj,cur);
  if(!pos.size)return null;
  const GW=170,GH=100,NW=130,NH=44;
  let minX=0,minY=0,maxX=0,maxY=0;
  pos.forEach(([x,y])=>{minX=Math.min(minX,x);maxX=Math.max(maxX,x);
    minY=Math.min(minY,y);maxY=Math.max(maxY,y);});
  const W=(maxX-minX+1)*GW,H=(maxY-minY+1)*GH;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  svg.setAttribute('width',W);svg.setAttribute('height',H);
  svg.style.display='block';
  const cx=x=>(x-minX)*GW+GW/2, cy=y=>(y-minY)*GH+GH/2;
  for(const [a,b] of edges){
    const [ax,ay]=pos.get(a),[bx,by]=pos.get(b);
    const ln=document.createElementNS('http://www.w3.org/2000/svg','line');
    ln.setAttribute('x1',cx(ax));ln.setAttribute('y1',cy(ay));
    ln.setAttribute('x2',cx(bx));ln.setAttribute('y2',cy(by));
    ln.setAttribute('stroke','#4a3f2a');ln.setAttribute('stroke-width','1.5');
    if(a===stationExit||b===stationExit)ln.setAttribute('stroke-dasharray','4 4');
    svg.appendChild(ln);
  }
  pos.forEach(([x,y],name)=>{
    const g=document.createElementNS('http://www.w3.org/2000/svg','g');
    const isCur=name===cur,isExit=name===stationExit;
    const r=document.createElementNS('http://www.w3.org/2000/svg','rect');
    r.setAttribute('x',cx(x)-NW/2);r.setAttribute('y',cy(y)-NH/2);
    r.setAttribute('width',NW);r.setAttribute('height',NH);r.setAttribute('rx',8);
    r.setAttribute('fill',isCur?'#2e2310':'#221c16');
    r.setAttribute('stroke',isExit?'#d0a75a':(isCur?'#c8a456':'#4a3f2a'));
    r.setAttribute('stroke-width',isCur?'2':'1');
    if(isExit)r.setAttribute('stroke-dasharray','5 3');
    g.appendChild(r);
    const t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',cx(x));t.setAttribute('y',cy(y)+Math.min(4,NH/2-10));
    t.setAttribute('text-anchor','middle');t.setAttribute('font-size','12.5');
    t.setAttribute('fill',isCur?'#e8d8a8':'#b8a888');
    t.textContent=(isCur?'◈ ':'')+name+(isExit?' ⛟':'');
    g.appendChild(t);
    svg.appendChild(g);
  });
  return svg;
}
async function loadMap(){
  const d=await fetchUi({"类型":"查看地图"});
  const c=cardShell('地图','');
  if(d.界面!=='map-ui'){dumpJson(c,d);return;}
  c.appendChild(el('div','ph',
    `当前区域：${d.当前区域} ｜ 当前场景：${d.当前场景||'—'} ｜ 驿站出口：${d.驿站出口||'—'}`));
  const svg=(d.场景图&&d.当前场景)?renderSceneSvg(d.场景图,d.当前场景,d.驿站出口):null;
  if(svg){
    const wrap=el('div');
    wrap.style.cssText='background:#0c0a07;border:1px solid #3a2f22;border-radius:8px;padding:10px;overflow-x:auto';
    wrap.appendChild(svg);c.appendChild(wrap);
  }else if(d.邻接图){
    c.appendChild(el('h4',null,'邻接图（场景图不可用，退化引擎文本）'));
    c.appendChild(el('pre','prebox',d.邻接图));
  }
  c.appendChild(el('h4',null,'已知地点'));
  const rows=(d.已知地点||[]).map(p=>[p.名称,(p.标记||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join('')]);
  c.appendChild(rows.length?uiTable(['名称','标记'],rows):el('div','ph','（仅当前场景）'));
}

/* ---------- 存档（save-ui，写操作三件套） ---------- */
async function loadSave(){
  const c=cardShell('存档','当前 slot 的存档点。危险操作均有二次确认。');
  const sv=el('div');sv.style.marginBottom='10px';
  const lbl=el('input','uibtn');lbl.placeholder='存档名（必填）';lbl.style.width='180px';
  const doSave=uiBtn('保存进度','primary');
  doSave.onclick=()=>{
    if(!lbl.value.trim()){addSysLine('保存游戏须填写存档名');return;}
    uiOp({"类型":"保存游戏","标签":lbl.value.trim()},{narrate:'存档中…',refresh});
  };
  sv.appendChild(lbl);sv.appendChild(document.createTextNode(' '));sv.appendChild(doSave);
  c.appendChild(sv);
  const holder=el('div');c.appendChild(holder);
  async function refresh(){
    const d=await fetchUi({"类型":"存档列表"});
    holder.innerHTML='';
    const entry=(d.存档列表||[])[0];
    if(!entry){holder.appendChild(el('div','ph','当前 slot 无存档点，或 slot 未创建（去标题TAB读档）。'));return;}
    holder.appendChild(el('div','ph',`slot ${entry.slot} ｜ ${entry.角色名||''} ｜ 共 ${(entry.saves||[]).length} 个存档点`));
    for(const s of (entry.saves||[])){
      const it=el('div','saveitem');
      const nm=el('div','nm');
      nm.appendChild(el('div','lb',s.label||'（未命名）'));
      nm.appendChild(el('div','ts',`#${s.序号} · ${s.时间戳}`));
      it.appendChild(nm);
      const ld=uiBtn('读档');
      ld.onclick=()=>{if(confirm(`读取存档「${s.label||s.时间戳}」？当前未保存进度将被覆盖。`))
        sendLoadArchive(currentSlot,s.时间戳,s.label||s.时间戳);};
      const del=uiBtn('删除','danger');
      del.onclick=()=>uiOp({"类型":"删除存档","目标":s.时间戳},
        {confirm:`删除存档点「${s.label||s.时间戳}」？不可恢复。`,refresh});
      it.appendChild(ld);it.appendChild(del);
      holder.appendChild(it);
    }
    const dz=uiBtn('删除整个角色档','danger');
    dz.onclick=()=>uiOp({"类型":"删除存档"},
      {confirm:`删除 slot ${entry.slot} 整个角色档（${entry.角色名||''}）？不可恢复，请再次确认。`,refresh});
    holder.appendChild(dz);
  }
  await refresh();
}

/* ---------- 线索（clue-ui，只读） ---------- */
async function loadClue(){
  const d=await fetchUi({"类型":"查看线索"});
  const c=cardShell('线索','');
  if(d.界面!=='clue-ui'){dumpJson(c,d);return;}
  // 经历概括（默认收起）
  const sum=typeof d.经历概括==='string'?d.经历概括.trim():'';
  if(sum){
    const det=el('details'); det.style.marginBottom='10px';
    det.appendChild(el('summary',null,'经历概括'));
    const body=el('div','clue-summary'); body.textContent=sum;
    det.appendChild(body); c.appendChild(det);
  }
  for(const [title,arr,open] of [['进行中',d.进行中||[],true],['已关闭',d.已关闭||[],false]]){
    const det=el('details'); if(open)det.open=true; det.style.marginBottom='8px';
    det.appendChild(el('summary',null,title+(arr.length?('（'+arr.length+'）'):'')));
    const wrap=el('div'); wrap.style.marginTop='6px';
    if(!arr.length){wrap.appendChild(el('div','ph','（无）'));}
    for(const cl of arr){
      wrap.appendChild(el('div','tag',cl.名称));
      for(const n of (cl.进展节点||[])){
        const nd=el('div','clue-node');
        nd.appendChild(document.createTextNode(n.描述||''));
        if(n.奖励)nd.appendChild(el('div','rw','奖励：'+n.奖励));
        wrap.appendChild(nd);
      }
    }
    c.appendChild(det);
  }
}

/* ---------- 角色（character-ui，只读） ---------- */
async function loadChar(){
  /* engine 无「主控」代号，须取当前档主控真名——探索态 队伍状态[0] 即玩家（玩家恒居首）。
     selectedMember 为右栏点选的队友名，缺省/已离队则回退主角。 */
  const names=(lastExpl&&lastExpl.队伍状态||[]).map(m=>m.名称);
  if(selectedMember&&!names.includes(selectedMember))selectedMember=null;
  const name=selectedMember||names[0]||null;
  if(!name){
    const c=cardShell('角色','');
    const b=uiBtn('重试');b.onclick=loadChar;c.appendChild(b);return;
  }
  const d=await fetchUi({"类型":"角色信息","角色":name});
  const c=cardShell('角色','');
  const info=d.角色信息;
  if(!info){dumpJson(c,d);return;}
  const base={"名称":info.名称,"性别":info.性别,"年龄":info.年龄,"经验值":info.经验值,
    "气血":`${info.气血}/${info.气血上限}`,"内力":`${info.内力}/${info.内力上限}`,
    "状态":info.死亡?'已死亡':'健在',"运转心法":info.运转心法||'无'};
  c.appendChild(kvGrid(base));
  const sections=[['一级属性',info.一级属性],['极性',info.极性],['武艺',info.武艺],
    ['技艺',info.技艺],['二级属性',info.二级属性]];
  for(const [t,o] of sections){c.appendChild(el('h4',null,t));c.appendChild(kvGrid(o));}
  c.appendChild(el('h4',null,'携带武学'));
  c.appendChild(el('div','ph',(info.携带技能||[]).join('、')||'（无）'));
  c.appendChild(el('h4',null,'战斗携带物品'));
  c.appendChild(el('div','ph',(info.携带物品||[]).map(i=>i.名称||i).join('、')||'（无）'));
  c.appendChild(el('h4',null,'装备'));
  c.appendChild(uiTable(['槽位','装备'],Object.entries(info.装备||{}).map(([k,v])=>[k,v||'（空）'])));
}

/* ---------- 标题（title-ui：全档快读/删） ---------- */
async function loadTitle(){
  const c=cardShell('标题','全部存档。读取 = 把对应 slot 的最新存档恢复并切换当前档。创建新角色请回游历流。');
  const holder=el('div');c.appendChild(holder);
  async function refresh(){
    const d=await fetchUi({"类型":"开始游戏"});
    holder.innerHTML='';
    const saves=d.存档列表||[];
    if(!saves.length){holder.appendChild(el('div','ph','尚无存档。去游历流输入「开始游戏」创建角色。'));return;}
    for(const s of saves){
      const it=el('div','saveitem');
      const nm=el('div','nm');
      nm.appendChild(el('div','lb',`slot ${s.slot} · ${s.角色名||'（无名）'}`));
      nm.appendChild(el('div','ts',`最近存档 ${s.最近存档||'—'}`+(s.进度?` ｜ ${s.进度.slice(0,40)}`:'')));
      it.appendChild(nm);
      if(s.slot===currentSlot)it.appendChild(el('span','tag','当前'));
      const ld=uiBtn('读取最新');
      ld.onclick=()=>{if(confirm(`读取 slot ${s.slot}（${s.角色名||''}）的最新存档并切换为当前档？`))
        sendLoadArchive(s.slot,s.最近存档,s.角色名||s.最近存档);};
      const del=uiBtn('删档','danger');
      del.onclick=()=>uiOp({"类型":"删除存档","槽位":s.slot},
        {confirm:`删除 slot ${s.slot}（${s.角色名||''}）整个角色档？不可恢复！`,refresh});
      it.appendChild(ld);it.appendChild(del);
      holder.appendChild(it);
    }
  }
  await refresh();
}

const TAB_VIEWS={bag:loadBag,equip:loadEquip,wuxue:loadWuxue,map:loadMap,
  save:loadSave,clue:loadClue,char:loadChar,title:loadTitle};

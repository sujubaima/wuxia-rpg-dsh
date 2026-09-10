/* ================= 门厅（建档/读档前的标题页） =================
   无当前档（或点"标题"TAB）时进入门厅：标题画+存档列表+与 GM 对话建角色。
   拿到档（读档/建档经 state 事件带回 槽位）后 enterGame 进入三栏主界面。 */
let gateMode=false;
function enterGate(){
  gateMode=true;activeTab='travel';
  document.body.classList.add('gate');
  document.getElementById('gateTop').style.display='block';
  renderTabs();showTab();
  loadGateSaves();
}
function enterGame(){
  gateMode=false;
  document.body.classList.remove('gate');
  document.getElementById('gateTop').style.display='none';
  refreshParty();
}
async function loadGateSaves(){
  const box=document.getElementById('gateSaves');
  box.innerHTML='<div class="ph" style="text-align:center">…读取存档列表…</div>';
  const d=await fetchUi({"类型":"开始游戏"});
  box.innerHTML='';
  const saves=d.存档列表||[];
  document.getElementById('gateVersion').textContent=d.版本||'0.0.0';
  document.getElementById('gateSaveCnt').textContent=`存档：${saves.length} 个`;
  if(!saves.length){
    const ph=el('div','ph','尚无存档可续，在下方描述你的角色开创新篇。');
    ph.style.textAlign='center';box.appendChild(ph);return;
  }
  for(const s of saves)box.appendChild(gateSaveItem(s));
}
/* 门厅单档卡：▸ 展开该 slot 下全部存档点，逐点读取 */
function gateSaveItem(s){
  const wrap=el('div','savewrap');
  const it=el('div','saveitem');
  const n=(s.saves||[]).length;
  const tog=el('button','uibtn exptoggle',`▸ ${n}点`);
  if(!n){tog.disabled=true;tog.textContent='—';}
  it.appendChild(tog);
  const nm=el('div','nm');
  nm.appendChild(el('div','lb',`slot ${s.slot} · ${s.角色名||'（无名）'}`));
  nm.appendChild(el('div','ts',`最近存档 ${s.最近存档||'—'}`));
  it.appendChild(nm);
  const ld=uiBtn('读取最新');
  ld.onclick=()=>{if(confirm(`读取 slot ${s.slot}（${s.角色名||''}）的最新存档？`))
    sendLoadArchive(s.slot,s.最近存档,s.角色名||s.最近存档);};
  const del=uiBtn('删档','danger');
  del.onclick=()=>uiOp({"类型":"删除存档","槽位":s.slot},
    {confirm:`删除 slot ${s.slot}（${s.角色名||''}）整个角色档？不可恢复！`,
     refresh:loadGateSaves});
  it.appendChild(ld);it.appendChild(del);
  wrap.appendChild(it);
  /* 展开的存档点子列表（数据随 开始游戏 返回，无需再拉） */
  const sub=el('div','savesub');sub.style.display='none';
  for(const sv of (s.saves||[])){
    const row=el('div','savesubitem');
    row.appendChild(el('span','lb2',sv.label||'（未命名）'));
    row.appendChild(el('span','ts2',`#${sv.序号} ${sv.时间戳}`));
    const b=uiBtn('读取');
    b.onclick=()=>{if(confirm(`读取 slot ${s.slot} 的存档「${sv.label||sv.时间戳}」？`))
      sendLoadArchive(s.slot,sv.时间戳,sv.label||sv.时间戳);};
    row.appendChild(b);
    sub.appendChild(row);
  }
  wrap.appendChild(sub);
  let open=false;
  tog.onclick=()=>{
    open=!open;
    sub.style.display=open?'':'none';
    tog.textContent=(open?'▾ ':'▸ ')+n+'点';
  };
  return wrap;
}
async function engineGo(actions,slotOverride){
  const resp=await fetch('/api/engine',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({"槽位":slotOverride!=null?slotOverride:currentSlot,"行为":actions})});
  const d=await resp.json().catch(()=>({"错误":"响应非 JSON"}));
  if(d.error&&!d.错误)d.错误=d.error;   // server 500 用英文 error，统一收口为中文 错误
  syncSlot(d);
  return d;
}
/* judge 直调（战斗-推进/战斗-开始/战后处置打包）——与 go 同通道，顶层多传 method:"judge" */
async function engineJudge(entries,payload_extra){
  const body=Object.assign({"method":"judge","槽位":currentSlot,"行为":entries},payload_extra||{});
  const resp=await fetch('/api/engine',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await resp.json().catch(()=>({"错误":"响应非 JSON"}));
  if(d.error&&!d.错误)d.错误=d.error;
  syncSlot(d);
  return d;
}


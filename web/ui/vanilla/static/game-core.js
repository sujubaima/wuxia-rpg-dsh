/* ================= 基础 ================= */
const $msgs=document.getElementById('msgs');
const $form=document.getElementById('form');
const $input=document.getElementById('input');
const $send=document.getElementById('send');
const $status=document.getElementById('status');
const $new=document.getElementById('newchat');

const SLOT_KEY='wuxia_newui_slot';
let currentSlot=parseInt(sessionStorage.getItem(SLOT_KEY)||'0',10);
/* 右栏队伍成员选中态：点哪个队友，中央角色面板就显示谁；null=主角(队伍状态[0]) */
let selectedMember=null;
function setSlot(v){currentSlot=parseInt(v,10)||0;sessionStorage.setItem(SLOT_KEY,String(currentSlot));}
function syncSlot(d){
  if(!d||typeof d!=='object')return;
  if(d.删除槽位!==undefined&&parseInt(d.删除槽位,10)===currentSlot){
    setSlot(0);enterGate();return;}
  if(d.槽位!==undefined&&parseInt(d.槽位,10)!==currentSlot){
    setSlot(d.槽位);
    if(gateMode&&currentSlot>0)enterGame();
  }
}

/* ================= DOM 助手 ================= */
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;
  if(text!=null)e.textContent=text;return e;}
function uiBtn(label,cls_extra){return el('button','uibtn'+(cls_extra?' '+cls_extra:''),label);}
function uiTable(headers,rows){
  const t=el('table','ui');
  const tr0=el('tr');
  for(const h of headers)tr0.appendChild(el('th',null,h));
  t.appendChild(tr0);
  for(const r of rows){
    const tr=el('tr');
    for(const c of r){
      const td=el('td');
      if(c&&c.nodeType)td.appendChild(c);
      else if(c!=null)td.innerHTML=String(c);
      tr.appendChild(td);
    }
    t.appendChild(tr);
  }
  return t;
}
function kvGrid(obj,emptyHint){
  const g=el('div','kv');
  const es=Object.entries(obj||{});
  if(!es.length){g.appendChild(el('div','muted',emptyHint||'（无）'));return g;}
  for(const [k,v] of es){
    const d=el('div');
    const b=el('b',null,k);d.appendChild(b);d.appendChild(document.createTextNode(String(v)));
    g.appendChild(d);
  }
  return g;
}
function fmtMoney(c){c=c==null?null:parseInt(c,10);if(c==null||isNaN(c))return '—';
  if(c>=1000){const l=Math.floor(c/1000),q=c%1000;return q?l+'两'+q+'钱':l+'两';}return c+'钱';}

/* ================= 右栏（队伍统一渲染；时辰地点已移至中央抬头带） ================= */
function renderPartySlotLine(){
  const c=document.getElementById('pslotChip');
  if(c)c.textContent='slot '+(currentSlot||'—');
}
function refreshParty(){
  if(inBattle)return;                 /* 战斗中途禁止 返回游戏（引擎红线） */
  if(!currentSlot){renderParty(null);return;}
  engineGo([{"类型":"返回游戏"}]).then(d=>{
    if(d&&d.界面==='exploration-ui'&&d.当前位置){
      renderParty(d);applyExplorationState(d);
    }else{
      /* 返回游戏 无效（存档不存在/已删/损坏）：仅清右栏，不急回门厅——
         战后处置期间 explore.json 可能暂未更新，SSE state 到了自然接管 */
      renderParty(null);
    }
  }).catch(()=>{renderParty(null);});
}
function renderParty(d){
  const $pm=document.getElementById('pmembers');
  const sc=document.getElementById('pslotChip');
  if(sc)sc.textContent='slot '+(currentSlot||'—');
  if(!d){
    document.getElementById('resSta').textContent='—';
    document.getElementById('resMoney').textContent='—';
    $pm.innerHTML='';return;
  }
  document.getElementById('resSta').textContent=d.体力==null?'—':d.体力;
  document.getElementById('resMoney').textContent=fmtMoney(d.金钱);
  $pm.innerHTML='';
  const ms=(d.队伍状态||[]);
  const names=ms.map(m=>m.名称);
  /* 选中态随队伍变化校正：已离队的清空，回退到主角(队伍状态[0]) */
  if(selectedMember&&!names.includes(selectedMember))selectedMember=null;
  const selName=selectedMember||(names[0]||null);
  /* 固定 4 槽位：人数不足留空位，不随实际人数缩放 */
  for(let i=0;i<4;i++){
    const m=ms[i];
    if(!m){
      const empty=el('div','pmember empty');
      empty.innerHTML=
        `<div class="top"><span class="nm">（空位）</span></div>`+
        `<div class="bars"><div class="bar hp"></div><div class="bar mp"></div></div>`;
      $pm.appendChild(empty);
      continue;
    }
    const div=el('div','pmember'+(m.名称===selName?' sel':''));
    const hp=Math.max(0,Math.min(100,(m.气血/(m.气血上限||1))*100));
    const mp=Math.max(0,Math.min(100,(m.内力/(m.内力上限||1))*100));
    div.innerHTML=
      `<div class="top"><span class="nm">${esc(m.名称||'')}</span></div>`+
      `<div class="bars">`+
      `<div class="bar hp${hp<35?' low':''}"><i style="width:${hp}%"></i><span>气血 ${m.气血}/${m.气血上限}</span></div>`+
      `<div class="bar mp"><i style="width:${mp}%"></i><span>内力 ${m.内力}/${m.内力上限}</span></div></div>`;
    const nm=m.名称;
    div.onclick=()=>{if(inBattle)return;selectedMember=nm;activeTab='char';showTab();};
    $pm.appendChild(div);
  }
}


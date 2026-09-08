/* ================= 战斗全屏模式 =================
   v1 取舍：按钮拼自然语言指令走聊天通道（LLM 驱动），GM 上下文/
   三层战报润色/战后处置完整保真；界面数据取 state 事件里的 battle-ui，
   解析稳定格式的 玩家界面 文本（状态表/行动预告/可用武学/可用物品）。 */
const $b=id=>document.getElementById(id);
let lastParse=null,lastBattle=null,bPick=null,bEnded=false;
function rosterParse(arr){
  return (arr||[]).map(s=>{const i=String(s).indexOf('：');
    return i>=0?{name:String(s).slice(0,i).trim(),tag:String(s).slice(i+1).trim()}:{name:String(s).trim(),tag:''};});
}
/* ---------- 逐回合回放（AI 回合不跳终态：按 回合详情 时序逐条播，播完落底终态） ---------- */
let replayTimer=null,lastPlayedRound=0,displayState={},lastOrder=[];
function cancelReplay(){if(replayTimer){clearTimeout(replayTimer);replayTimer=null;}
  document.querySelectorAll('.bcard.acting').forEach(c=>c.classList.remove('acting'));
  const cons=document.getElementById('bConsole');if(cons)cons.classList.remove('locked');}
function scrollwait(ms){return new Promise(r=>setTimeout(r,ms));}
function setCardBar(name,which,val){
  const st=displayState[name];const card=document.getElementById('bc_'+name);
  if(!card)return;
  const bar=card.querySelector('.bar.'+which);if(!bar)return;
  const i=bar.querySelector('i'),s=bar.querySelector('span');
  const max=(which==='hp'?(st&&st.maxhp):(st&&st.maxmp))||null;
  if(max){
    const p=Math.max(0,Math.min(100,val/max*100));
    i.style.width=p+'%';
    s.textContent=(which==='hp'?'气血 ':'内力 ')+val+'/'+max;
    if(which==='hp'){if(st)st.hp=val;bar.classList.toggle('low',p<35);}
    else if(st)st.mp=val;
  }
}
function lungeCard(card){
  if(!card)return;
  const cls=card.classList.contains('enemy')?'lunge-down':'lunge-up';
  card.classList.remove('lunge-up','lunge-down');
  void card.offsetWidth;                       // 强制重排，让同类动画可连发
  card.classList.add(cls);
  setTimeout(()=>card.classList.remove(cls),950);
}
function shakeCard(card,critFlash){
  if(!card)return;
  card.classList.remove('shake','hitflash');
  void card.offsetWidth;
  card.classList.add('shake');
  if(critFlash)card.classList.add('hitflash');
  setTimeout(()=>card.classList.remove('shake','hitflash'),1050);
}
function flyProjectile(fromCard,toCard){
  if(!fromCard||!toCard)return null;
  const a=fromCard.getBoundingClientRect(),b=toCard.getBoundingClientRect();
  const x0=a.left+a.width/2,y0=a.top+a.height/2,x1=b.left+b.width/2,y1=b.top+b.height/2;
  const p=document.createElement('div');
  p.className='proj'+(fromCard.classList.contains('enemy')?' foe':'');
  p.style.left=x0+'px';p.style.top=y0+'px';
  document.body.appendChild(p);
  const ang=Math.atan2(y1-y0,x1-x0)*180/Math.PI;
  const dx=x1-x0,dy=y1-y0;
  const anim=p.animate([
    {transform:`translate(0,0) rotate(${ang}deg)`,opacity:.85},
    {transform:`translate(${dx}px,${dy}px) rotate(${ang}deg)`,opacity:1}
  ],{duration:700,easing:'cubic-bezier(.4,.1,.6,1)'});
  anim.onfinish=()=>p.remove();
  return anim;
}
function actionLabel(card,text,cls){
  if(!card||!text)return;
  const tag=document.createElement('div');
  tag.className='actlabel '+(cls||'');
  tag.textContent=text;
  card.appendChild(tag);
  setTimeout(()=>tag.classList.add('out'),1500);
  setTimeout(()=>tag.remove(),1780);
}
function applyReplayEntry(e){
  /* 行动者光环迁到本次行动者（不整屏重渲）+ 向中场冲刺 + 本轮动作气泡 */
  document.querySelectorAll('.bcard.acting').forEach(c=>c.classList.remove('acting'));
  const aCard=document.getElementById('bc_'+e.行动者);
  if(aCard){aCard.classList.add('acting');lungeCard(aCard);
    const foeCls=aCard.classList.contains('enemy');
    let txt=null,cls=foeCls?'foe':'';
    if(e.类型==='武学')txt='【'+(e.技能||'?')+(e.招式?'·'+e.招式:'')+'】'+(e.目标?' → '+e.目标:'');
    else if(e.类型==='物品'){txt='用药【'+(e.物品||'?')+'】'+(e.目标?' → '+e.目标:'');cls='item';}
    else if(e.类型==='休息'){txt='敛气调息';cls='walk';}
    else if(e.类型==='逃跑'){txt='要遁走！';cls='walk';}
    else if(e.类型==='认输'){txt='认输';cls='walk';}
    else if(e.类型==='运功'){txt='运功凝神';cls='walk';}
    actionLabel(aCard,txt,cls);
  }
  const hpchg=(who,v)=>{const ar=v?(Array.isArray(v)?v:[v]):[];
    for(const ch of ar){
      if(ch.原值==null||ch.新值==null)continue;
      const diff=ch.原值-ch.新值;
      const tgt=document.getElementById('bc_'+who);
      setCardBar(who,'hp',ch.新值);
      if(diff>0){floatCard(who,'-'+diff,e.暴击?'crit':'dmg');
        shakeCard(tgt,!!e.暴击);}
      else if(diff<0)floatCard(who,'+'+(-diff),'heal');
    }};
  const mpchg=(who,v)=>{const ar=v?(Array.isArray(v)?v:[v]):[];
    for(const ch of ar){
      if(ch.原值==null||ch.新值==null)continue;
      const diff=ch.原值-ch.新值;
      setCardBar(who,'mp',ch.新值);
      if(diff>0)floatCard(who,'-'+diff,'mpdmg');
      else if(diff<0)floatCard(who,'+'+(-diff),'mpheal');
    }};
  /* 状态增减飘字（侧边）：applied=施加状态列表(每项含 目标/名称)，expired=失效状态列表(每项含 名称)。
     仅飘字提示，不实时增删徽章——徽章文本含层数/剩余回合，回合内会变化（tick 递减、叠加层数），
     实时拼接无法准确还原，故徽章统一交由回合末 renderBattle 全量渲染，避免「实时1层/回合末2层」不一致。 */
  const sfloat=(who,txt,cls)=>{
    const card=document.getElementById('bc_'+who);if(!card)return;
    const f=el('div','float sfloat '+cls,txt);card.appendChild(f);
    setTimeout(()=>f.remove(),2000);
  };
  const statusChg=(applied,expired,actor)=>{
    for(const g of (applied||[]))sfloat(g.目标||actor,'＋'+(g.名称||''),'buff');
    for(const s of (expired||[]))sfloat(actor,'－'+(s.名称||''),'expire');
  };
  /* 用状态快照增量更新角色徽章：snap={角色名:[徽章文本,...]}。
     按状态名(【名】部分，忽略剩余回合后缀)匹配新旧：
     - 新增的徽章淡入(badgeIn)
     - 消失的徽章淡出(badgeOut)后移除
     - 同状态名仍在的：原地更新文本（剩余回合变化不闪烁），不淡入淡出
     可叠加状态按数量增减（多出的淡入、少的淡出）。冷却徽章(.stg.cd)保留不动。 */
  const badgeKey=txt=>{const m=/^(【[^】]+】)/.exec(txt);return m?m[1]:txt;}; // 取【状态名】部分作匹配键
  const applySnapshot=(snap)=>{
    if(!snap)return;
    for(const name in snap){
      const card=document.getElementById('bc_'+name);if(!card)continue;
      let sts=card.querySelector('.sts');if(!sts){sts=document.createElement('div');sts.className='sts';card.appendChild(sts);}
      const olds=[...sts.querySelectorAll('.stg:not(.cd)')];   // 现有状态徽章(排除冷却)
      const news=(snap[name]||[]).slice();
      const usedOld=new Array(olds.length).fill(false);
      // 匹配：新徽章按状态名键找未占用的旧徽章，命中则原地更新文本
      const kept=[];
      for(const txt of news){
        const key=badgeKey(txt);
        const idx=olds.findIndex((g,i)=>!usedOld[i]&&badgeKey(g.textContent)===key);
        if(idx>=0){usedOld[idx]=true;olds[idx].textContent=txt;kept.push(olds[idx]);}
      }
      // 未命中的旧徽章：淡出移除
      olds.forEach((g,i)=>{if(!usedOld[i]){g.style.animation='badgeOut .3s ease-in forwards';setTimeout(()=>g.remove(),300);}});
      // 新增的徽章（未匹配到旧的）：淡入追加
      for(let i=0;i<news.length;i++){
        const txt=news[i];const key=badgeKey(txt);
        if(!kept.some(g=>g.textContent===txt)){
          const g=document.createElement('span');g.className='stg';g.textContent=txt;
          g.style.animation='badgeIn .4s ease-out';
          // 插到冷却徽章之前
          const firstCd=sts.querySelector('.stg.cd');
          if(firstCd)sts.insertBefore(g,firstCd);else sts.appendChild(g);
        }
      }
    }
  };
  if(e.类型==='武学'){
    if(e.闪避){
      /* 闪避：弹道仍飞出，到达后落「闪避」字 */
      const tgt=document.getElementById('bc_'+e.目标);
      if(e.目标结算){
        e.目标结算.forEach((te,i)=>{
          setTimeout(()=>flyProjectile(aCard,document.getElementById('bc_'+te.目标)),600+i*120);
          setTimeout(()=>{if(te.闪避)floatCard(te.目标,'闪避','miss');},1350+i*120);
        });
      }else if(tgt){
        setTimeout(()=>flyProjectile(aCard,tgt),600);
        setTimeout(()=>floatCard(e.目标,'闪避','miss'),1350);
      }else{floatCard(e.目标,'闪避','miss');}
    }
    else{
      const tgt=document.getElementById('bc_'+e.目标);
      if(e.目标结算){
        /* 全体规数：向每个目标各发一道箭蚀（微错峰），命中落结算 */
        e.目标结算.forEach((te,i)=>{
          setTimeout(()=>flyProjectile(aCard,document.getElementById('bc_'+te.目标)),600+i*120);
          setTimeout(()=>hpchg(te.目标,te.目标气血变化),1350+i*120);
          setTimeout(()=>mpchg(te.目标,te.目标内力变化),1350+i*120);
          setTimeout(()=>statusChg(te.施加状态,null,te.目标),1350+i*120);
        });
      }else if(tgt){
        setTimeout(()=>flyProjectile(aCard,tgt),600);
        setTimeout(()=>hpchg(e.目标,e.目标气血变化),1350);
        setTimeout(()=>mpchg(e.目标,e.目标内力变化),1350);
        /* 受击方「施加状态」跟随命中再渲染（与AOE路径一致） */
        setTimeout(()=>statusChg(e.施加状态,null,e.目标),1350);
      }else{hpchg(e.目标,e.目标气血变化);mpchg(e.目标,e.目标内力变化);}
      if(e.击败){setTimeout(()=>{const t=document.getElementById('bc_'+e.目标);if(t)t.classList.add('dead');},1350);}
    }
    if(e.行动者内力变化)setCardBar(e.行动者,'mp',e.行动者内力变化.新值);
    if(e.行动者气血变化)setCardBar(e.行动者,'hp',e.行动者气血变化.新值);
    statusChg(e.施加状态,e.状态失效,e.行动者);
  }else if(e.类型==='物品'){
    hpchg(e.目标,e.目标气血变化);
    mpchg(e.目标,e.目标内力变化);
    statusChg(e.施加状态,e.状态失效,e.行动者);
  }else if(e.类型==='休息'){
    if(e.内力变化){
      const rec=(e.内力变化.新值||0)-(e.内力变化.原值||0);
      setCardBar(e.行动者,'mp',e.内力变化.新值);
      if(rec>0)floatCard(e.行动者,'+'+rec,'mpheal');
    }
    if(e.气血变化){
      const rec=(e.气血变化.新值||0)-(e.气血变化.原值||0);
      setCardBar(e.行动者,'hp',e.气血变化.新值);
      if(rec>0)floatCard(e.行动者,'+'+rec,'heal');
    }
    statusChg(null,e.状态失效,e.行动者);
  }else if(e.类型==='逃跑'){
    if(e.逃跑成功){const c=aCard;if(c)c.classList.add('dead','fled');}
    else floatCard(e.行动者,'未脱身','miss');
  }else if(e.类型==='认输'){
    floatCard(e.行动者,'认输','miss');
  }else if(e.类型==='运功'){
    for(const s of (e.获得状态||[]))floatCard(e.行动者,'运功·'+(s||''),'buff');
  }
  applySnapshot(e.状态快照);
}
function startReplay(entries,d){
  cancelReplay();
  const cons=document.getElementById('bConsole');if(cons)cons.classList.add('locked');
  let i=0;
  return new Promise(res=>{
    const step=()=>{
      if(i>=entries.length){
        replayTimer=null;
        const cc=document.getElementById('bConsole');if(cc)cc.classList.remove('locked');
        renderBattle(d);res();return;
      }
      const e=entries[i++];
      applyReplayEntry(e);
      lastPlayedRound=Math.max(lastPlayedRound,e.回合||0);
      const stc=(lastBattle&&lastBattle.战局状态)||{};
      renderChainSeq(stc,entries.slice(i).map(x=>x.行动者).concat(lastOrder||[]));
      replayTimer=setTimeout(step,2400);
    };
    step();
  });
}
function lockConsoleNow(){
  const cons=document.getElementById('bConsole');if(cons)cons.classList.add('locked');
}
/* 开场：先落终态阵容→据 回合详情 反推初始血蓝（每个名字取首个出现的 原值），停一拍供回放起步 */
function seedOpeningDisplay(d,details){
  renderBattle(d,{skipLog:true});
  const seen={};
  const take=(who,chg,which)=>{
    if(!who||!chg||chg.原值==null)return;
    const k=who+'|'+which;if(seen[k])return;seen[k]=1;
    const st=displayState[who]=displayState[who]||{};
    setCardBar(who,which,chg.原值);
    if(which==='hp')st.hp=chg.原值;else st.mp=chg.原值;
  };
  for(const e of details){
    take(e.行动者,e.行动者内力变化,'mp');
    take(e.行动者,e.行动者气血变化,'hp');
    take(e.行动者,e.气血变化,'hp');
    take(e.行动者,e.内力变化,'mp');
    take(e.目标,e.目标气血变化,'hp');
    take(e.目标,e.目标内力变化,'mp');
    for(const te of (e.目标结算||[])){
      if(te.目标气血变化)take(te.目标,te.目标气血变化,'hp');
      if(te.目标内力变化)take(te.目标,te.目标内力变化,'mp');
    }
  }
  document.querySelectorAll('.bcard.acting').forEach(c=>c.classList.remove('acting'));
}
function enterBattle(d){
  const first=!inBattle;
  setBattleMode(true);
  if(first){bEnded=false;lastParse=null;
    lastPlayedRound=0;displayState={};cancelReplay();
    $b('bEndMask').classList.remove('show');}
  lastBattle=d;
  hidePreFight();
  const details=d.回合详情||[];
  const fresh=details.filter(e2=>(e2.回合||0)>lastPlayedRound);
  const end=()=>{
    if(d.界面==='battle-end-ui'||(d.战局状态&&d.战局状态.状态&&d.战局状态.状态!=='进行中')){
      showBattleEndDialog(d);
    }
  };
  if(fresh.length){
    /* 有未播回合：整场回放（含开场运功/AI 先手），播完再经 renderBattle 落底终态。
       返回 promise 供控制台锁/解锁时序链使用。 */
    if(first){seedOpeningDisplay(d,fresh);
      return scrollwait(700).then(()=>startReplay(fresh,d)).then(end);}
    return startReplay(fresh,d).then(end);
  }
  renderBattle(d);
  if(details.length)lastPlayedRound=Math.max(lastPlayedRound,...details.map(e2=>e2.回合||0));
  end();
  return null;
}
function exitBattle(mode){
  if(!inBattle)return;
  cancelReplay();
  setBattleMode(false);lastParse=null;bPick=null;lastBattle=null;
  $b('bEndMask').classList.remove('show');
  hidePreFight();
  /* 战后不调 refreshParty（那会触发 返回游戏 读旧状态）——直接亮灯等 GM 战后处置的 SSE state 接管 */
  _turnTools=0;setSteps(1);
}
/* 解析 WEB_UI 结构化「行动信息」（engine 行动信息 字段），构建与 parsePlayerUI 同形的 R。
   R = {actor, order, table, skills, items}，供 renderRosters/renderBattleConsole/renderBattleChain 复用。 */
function parseActionInfo(ai){
  const R={actor:null,order:[],table:{},skills:[],items:[]};
  if(!ai||typeof ai!=='object')return R;
  R.actor=ai.行动者||null;
  R.order=Array.isArray(ai.行动顺序)?ai.行动顺序.slice():[];
  /* 状态表 → table[name]：气血/内力拼回 "cur/max" 字符串（兼容 renderRosters 的 split('/')），
     状态/冷却由 list 拼回字符串（兼容 split('、')） */
  for(const c of (ai.状态表||[])){
    const hp=c.气血,mp=c.内力;
    R.table[c.名称]={
      阵营:c.阵营,名称:c.名称,
      气血:(hp&&typeof hp==='object')?`${hp.当前}/${hp.上限}`:'',
      内力:(mp&&typeof mp==='object')?`${mp.当前}/${mp.上限}`:'',
      状态:c.败阵?'败阵':c.逃走?'逃走':(Array.isArray(c.状态)?c.状态.join('、'):'无'),
      冷却:Array.isArray(c.冷却)?c.冷却.join('、'):'无',
      败阵:!!c.败阵,逃走:!!c.逃走,
    };
  }
  /* 可用武学：保留结构化布尔，禁用原因前端据 bool 拼 */
  for(const s of (ai.可用武学||[])){
    R.skills.push({
      名称:s.名称,类型:s.类型,范围:s.范围||'敌方单体',
      威力:s.威力,内力:s.内力,冷却:s.冷却||'无冷却',
      可用:!!s.可用,
      冷却中:!!s.冷却中,冷却剩余:s.冷却剩余||0,
      内力不足:!!s.内力不足,武器不符:!!s.武器不符,
      特效:s.特效||'',
    });
  }
  for(const it of (ai.可用物品||[])){
    R.items.push({名称:it.名称,数量:it.数量,效果:it.效果||'',方向:it.方向||''});
  }
  return R;
}
function parsePlayerUI(txt){
  const R={actor:null,order:[],table:{},skills:[],items:[]};
  if(!txt)return R;
  let mode='';
  for(const ln of String(txt).split('\n')){
    const mAct=ln.match(/行动角色：(.+)$/);
    if(mAct)R.actor=mAct[1].trim();
    if(/^\s*\|.*\|\s*$/.test(ln)){
      if(ln.includes('名称')||/^[\s|:-]+$/.test(ln))continue;
      const cells=ln.split('|').map(s=>s.trim()).filter(s=>s.length);
      if(cells.length>=6){
        const c={阵营:cells[0],名称:cells[1].replace(/`/g,''),气血:cells[2],内力:cells[3],状态:cells[4],冷却:cells[5]};
        R.table[c.名称]=c;
      }else if(cells.length===3){
        const c={阵营:cells[0],名称:cells[1].replace(/`/g,''),状态列:cells[2]};
        R.table[c.名称]=c;
      }
      continue;
    }
    const mOrd=ln.match(/行动预告：【(.+?)】→\s*(.+)$/);
    if(mOrd)R.order=mOrd[2].split('→').map(s=>s.trim()).filter(Boolean);
    if(ln.startsWith('可用武学')){mode='sk';continue;}
    if(ln.startsWith('可用物品')){mode='it';continue;}
    if(ln.startsWith('请输入')){mode='';continue;}
    if(mode==='sk'){
      const m=ln.match(/^- `(.+?)`（(.+?)）\s*——\s*(.+)$/);
      if(m){
        const inner=m[2].split(' / ');
        const flags=m[3].split('，');
        R.skills.push({名称:m[1],类型:inner[0]||'',范围:inner[1]||'敌方单体',
          威力:(inner[2]||'').replace('威力',''),内力:(inner[3]||'').replace('内力',''),
          冷却:(inner[4]||''),flags,可用:flags.length===1&&flags[0]==='可用'});
        continue;
      }
      if(ln.startsWith('　特效')&&R.skills.length){R.skills[R.skills.length-1].特效=ln.replace(/^　/,'');continue;}
    }
    if(mode==='it'){
      const m=ln.match(/^- `(.+?)`\s*×\s*(\d+)/);
      if(m){R.items.push({名称:m[1],数量:+m[2]});continue;}
      const e=ln.match(/^　效果：(.+?)（(对我方|对敌方)）/);
      if(e&&R.items.length){R.items[R.items.length-1].效果=e[1];R.items[R.items.length-1].方向=e[2];continue;}
    }
  }
  return R;
}
function renderBattle(d,opts){
  opts=opts||{};
  const st=d.战局状态||{};
  if(Array.isArray(d.行动预告)&&d.行动预告.length)lastOrder=d.行动预告;
  $b('bRound').textContent=st.回合数!=null?`第 ${st.回合数} 回合`:'';
  $b('bState').textContent=st.状态||'';
  const ended=st.状态&&st.状态!=='进行中';
  $b('bState').style.color=!ended?'var(--ok)':(/我方胜|敌方认输/.test(st.状态)?'var(--accent)':'var(--danger)');
  if(d.行动信息)lastParse=parseActionInfo(d.行动信息);
  else if(d.玩家界面)lastParse=parsePlayerUI(d.玩家界面);
  renderRosters(st);
  renderBattleChain(st);
  renderBattleConsole(st);
  /* 战报栏已下线：不再渲染文字战报 */
  /* 全量渲染后重建 displayState（回放动画的血/蓝基准与上限来源） */
  if(lastParse&&lastParse.table){
    for(const nm in lastParse.table){const t=lastParse.table[nm];
      if(t.气血&&/\//.test(t.气血)){const pr=t.气血.split('/');
        const st=displayState[nm]=displayState[nm]||{};st.hp=+pr[0]||0;st.maxhp=+pr[1]||1;}
      if(t.内力&&/\//.test(t.内力)){const pr=t.内力.split('/');
        const st=displayState[nm]=displayState[nm]||{};st.mp=+pr[0]||0;st.maxmp=+pr[1]||1;}
    }
  }
}
function renderChainSeq(st,seq){
  /* 按给定顺序渲抬头行动预告链（供回放逐帧推进） */
  const ch=$b('bChain');ch.innerHTML='';
  const lab=document.createElement('span');lab.className='clabel';lab.textContent='行 动 预 告';
  ch.appendChild(lab);
  const ally=new Set(rosterParse(st.我方).map(r=>r.name));
  const tags={};
  for(const r of rosterParse(st.我方).concat(rosterParse(st.敌方)))tags[r.name]=r.tag;
  let num=0,marked=false;
  seq.slice(0,7).forEach((nm,i,arr)=>{
    const dead=/败阵|逃走/.test(tags[nm]||'');
    const c=document.createElement('div');
    c.className='node '+(ally.has(nm)?'ally':'enemy');
    if(dead)c.classList.add('dead');
    else{num++;if(!marked){c.classList.add('now');marked=true;}}
    c.innerHTML=dead?`<i>✕</i>${esc(nm)}`:`<i>${num}</i>${esc(nm)}`;
    ch.appendChild(c);
    if(i<arr.length-1){const a=document.createElement('span');a.className='arrow';a.textContent='→';ch.appendChild(a);}
  });
}
function renderBattleChain(st){
  /* 引擎 行动预告 的语义是「当前行动者之后的序」（不含当前人，
     同 battle_engine predict_action_order 契约——CLI 自拼【当前人】在前）；
     前端渲染时须把当前行动者拼回头行，否则次位者冒头。 */
  const cur=(lastParse&&lastParse.actor)||null;
  const tail=(lastOrder&&lastOrder.length)?lastOrder.slice():[];
  let seq=[];
  if(cur)seq.push(cur);
  for(let i=0;i<tail.length;i++){
    if(i===0&&cur&&tail[i]===cur)continue;          // 极少数路径 tail 已含当前人——边界去重
    seq.push(tail[i]);
  }
  if(!seq.length){
    if(cur)seq.push(cur);
    if(lastParse&&lastParse.order)for(const n of lastParse.order)if(!seq.includes(n))seq.push(n);
  }
  if(!seq.length)seq=rosterParse(st.我方).concat(rosterParse(st.敌方)).map(r=>r.name);
  renderChainSeq(st,seq);
}
function renderRosters(st){
  for(const spec of [['bEnemy',st.敌方,'enemy'],['bAlly',st.我方,'ally']]){
    const row=$b(spec[0]);row.innerHTML='';
    for(const r of rosterParse(spec[1])){
      const tbl=lastParse&&lastParse.table?lastParse.table[r.name]:null;
      const dead=/败阵/.test(r.tag)||(tbl&&tbl.状态列==='败阵');
      const fled=/逃走/.test(r.tag)||(tbl&&tbl.状态列==='逃走');
      const acting=lastParse&&lastParse.actor===r.name&&!dead&&!fled;
      const targetable=bPick&&!dead&&!fled&&!(bPick.noSelf&&acting)&&((bPick.dir==='敌方'&&spec[2]==='enemy')||(bPick.dir==='我方'&&spec[2]==='ally'));
      const card=document.createElement('div');
      card.className='bcard '+spec[2]+(dead?' dead':'')+(fled?' dead fled':'')+(acting?' acting':'')+(targetable?' targetable':'');
      card.id='bc_'+r.name;
      let inner=`<div class="bnm"><span>${esc(r.name)}</span><span class="crown">${esc(r.tag&&r.tag!=='战斗中'?r.tag:'')}</span></div><div class="bars">`;
      let hpSet=false;
      if(tbl&&tbl.气血&&/\//.test(tbl.气血)){
        const pts=tbl.气血.split('/');const a=+pts[0]||0,mm=+pts[1]||1;
        const hp=Math.max(0,Math.min(100,a/mm*100));
        inner+=`<div class="bar hp${hp<35?' low':''}"><i style="width:${hp}%"></i><span>气血 ${a}/${mm}</span></div>`;
        hpSet=true;
        if(tbl.内力&&/\//.test(tbl.内力)){
          const q=tbl.内力.split('/');const aa=+q[0]||0,bb=+q[1]||1;
          const mp=Math.max(0,Math.min(100,aa/bb*100));
          inner+=`<div class="bar mp"><i style="width:${mp}%"></i><span>内力 ${aa}/${bb}</span></div>`;
        }
      }
      if(!hpSet)inner+=`<div class="bar hp"><i style="width:${dead||fled?0:100}%"></i><span>${dead?'败阵':fled?'逃走':'气血 —'}</span></div>`;
      inner+='</div>';
      card.innerHTML=inner;
      const sts=document.createElement('div');sts.className='sts';
      if(tbl){
        if(tbl.状态&&tbl.状态!=='无')for(const sn of tbl.状态.split('、')){
          const g=document.createElement('span');g.className='stg';g.textContent=sn;sts.appendChild(g);}
        if(tbl.冷却&&tbl.冷却!=='无')for(const sn of tbl.冷却.split('、')){
          const g=document.createElement('span');g.className='stg cd';g.textContent=sn;sts.appendChild(g);}
      }
      card.appendChild(sts);
      if(targetable)card.onclick=()=>resolveBattleAction(r.name);
      row.appendChild(card);
    }
  }
}
function renderBattleConsole(st){
  const grid=$b('bGrid');grid.innerHTML='';
  const p=lastParse;
  const ended=st.状态&&st.状态!=='进行中';
  const mine=p&&p.actor?rosterParse(st.我方).some(r=>r.name===p.actor):false;
  const usable=!ended&&mine&&!busy;
  const turn=$b('bTurn'),watch=$b('bWatch');
  if(ended){turn.innerHTML='—— 战局已终';watch.textContent='';}
  else if(!p||!p.actor){turn.innerHTML='◌ 战局推演中…';watch.textContent='（纯 AI 回合，或尚未轮到玩家）';}
  else{turn.innerHTML=`▶ 轮到 <b>${esc(p.actor)}</b>`;watch.textContent=busy?'GM 正在结算…':'';}
  $b('bConsole').classList.toggle('locked',!usable);
  if(!p||!p.actor)return;
  const gSk=document.createElement('div');gSk.className='cgroup';
  const lb=document.createElement('span');lb.className='g-label';lb.textContent='武学（战斗携带 ≤4）';gSk.appendChild(lb);
  const cards=document.createElement('div');cards.className='g-cards';
  for(let i=0;i<4;i++){
    const s=(p.skills||[])[i];
    const d1=document.createElement('div');
    if(!s){d1.className='skcard empty';d1.textContent='（空槽）';cards.appendChild(d1);continue;}
    d1.className='skcard'+(!s.可用?' disabled':'')+((bPick&&bPick.kind==='skill'&&bPick.name===s.名称)?' picked':'');
    /* s.冷却：结构化路径为数字（冷却回合数，0=无冷却）；旧文本路径为字符串。
       两种都兼容——非空非「无冷却」即显示。 */
    const cdRaw=s.冷却;
    const cdStr=(cdRaw&&(cdRaw!==0&&cdRaw!=='无冷却'&&cdRaw!=='无'))?(' ｜ 冷却'+cdRaw):' ｜ 无冷却';
    d1.innerHTML=`<div class="sn">◆ ${esc(s.名称)}</div>`+
      `<div class="sp">${esc(s.类型)} ｜ ${esc(s.范围||'敌方单体')}</div>`+
      `<div class="sp">威力${esc(s.威力)} ｜ 内力${esc(s.内力)}${esc(cdStr)}</div>`;
    if(!s.可用){
      const cd=document.createElement('div');cd.className='cdnote';
      /* 禁用原因：结构化行动信息据 bool 拼；旧文本解析路径回退 flags */
      const reasons=s.flags
        ? s.flags.filter(f=>f!=='可用')
        : [s.冷却中&&`冷却中(剩${s.冷却剩余||0}回合)`,s.内力不足&&'内力不足',s.武器不符&&'武器不符'].filter(Boolean);
      cd.textContent=reasons.join('、');
      d1.appendChild(cd);
    }else{d1.onclick=()=>pickBattleTarget('skill',s);}
    cards.appendChild(d1);
  }
  gSk.appendChild(cards);grid.appendChild(gSk);
  if(true){
    const dv=document.createElement('div');dv.className='cdiv';grid.appendChild(dv);
    const gIt=document.createElement('div');gIt.className='cgroup';
    const lb2=document.createElement('span');lb2.className='g-label';lb2.textContent='战斗携带物品';gIt.appendChild(lb2);
    const cards2=document.createElement('div');cards2.className='g-cards';
    for(let i=0;i<4;i++){
      const it=p.items[i];
      const d2=document.createElement('div');
      if(!it){d2.className='skcard empty';d2.textContent='（空槽）';cards2.appendChild(d2);continue;}
      d2.className='skcard'+((bPick&&bPick.kind==='item'&&bPick.name===it.名称)?' picked':'');
      d2.innerHTML=`<div class="sn">▤ ${esc(it.名称)} ×${it.数量}</div>`+
        `<div class="sp">${esc(it.效果||'')}</div><div class="sp">${esc(it.方向||'')}</div>`;
      d2.onclick=()=>pickBattleTarget('item',it);
      cards2.appendChild(d2);
    }
    gIt.appendChild(cards2);grid.appendChild(gIt);
  }
  const dv2=document.createElement('div');dv2.className='cdiv';grid.appendChild(dv2);
  const fb=document.createElement('div');fb.className='fbtns';
  const mk=(label,fn,danger)=>{
    const b=document.createElement('button');b.className='fbtn'+(danger?' danger':'');
    b.textContent=label;b.onclick=fn;fb.appendChild(b);return b;};
  mk('休息（回内力10%）',()=>battleAct({"类型":"战斗-休息"}));
  /* 逃跑：据 battle-ui 的 允许逃跑 字段置灰（战前 GM 据剧情人设判定，不可逃则禁用） */
  const canFlee=lastBattle&&lastBattle.允许逃跑!==false;
  const fleeBtn=mk('逃跑',()=>battleAct({"类型":"战斗-逃跑"}));
  if(!canFlee&&fleeBtn){fleeBtn.disabled=true;fleeBtn.classList.add('disabled');fleeBtn.title='此战不容脱身';}
  mk('认输',()=>{if(confirm('确定认输？我方将判负。'))battleAct({"类型":"战斗-认输"});},true);
  mk('查看人物',()=>{if(busy)return;send('查看人物信息');});
  if(bPick)mk('取消选择',()=>{bPick=null;renderBattle(lastBattle);});
  grid.appendChild(fb);
}
function pickBattleTarget(kind,obj){
  if(busy){addSysLine('正在结算上一回合…');return;}
  if(kind==='skill'&&obj.范围==='敌方全体'){battleAct({"类型":"战斗-使用武学","武学":obj.名称});return;}
  bPick={kind,name:obj.名称,dir:kind==='skill'?(/^我方/.test(obj.范围)?'我方':'敌方'):(obj.方向==='对我方'?'我方':'敌方'),noSelf:kind==='skill'&&obj.范围==='我方单体除自身'};
  renderBattle(lastBattle);
}
function resolveBattleAction(target){
  if(!bPick)return;const p=bPick;bPick=null;
  document.querySelectorAll('.bcard.targetable').forEach(c=>{c.classList.remove('targetable');c.onclick=null;});
  battleAct(p.kind==='skill'
    ?{"类型":"战斗-使用武学","武学":p.name,"目标":target}
    :{"类型":"战斗-使用物品","物品":p.name,"目标":target});
}
/* 控制台直驱：go 结算（无界面）→ judge 战斗-推进 打包 battle-ui。不经 LLM、50ms 级。
   LLM 驱动路径不变：GM 自己判罚/叙事同样产出 battle-ui → 经 SSE state 同入口渲染。
   直驱的 回合详情（引擎结构化回合明细）驱动卡面飘字动画；战报栏照旧收 battle-ui.战报 文本。 */
async function battleAct(action){
  if(busy){addSysLine('正在结算上一回合…');return;}
  busy=true;
  lockConsoleNow();
  let enterRet=null;
  try{
    const d=await engineGo([action]);
    if(d.错误){addSysLine('战斗操控未成功：'+d.错误,{long:true});return;}
    if(d.界面==='battle-end-ui'){
      enterRet=enterBattle(d);
    }else{
      const j=await engineJudge([{ "类型":"战斗-推进", "回合详情": d.回合详情||[] }], {"当前剧情":""});
      if(j.错误){addSysLine('战斗推进打包未成功：'+j.错误,{long:true});return;}
      if(!(j.界面==='battle-ui'||j.界面==='battle-end-ui')){
        addSysLine('战斗推进返回异常（无 battle 界面）——战场保留未动。',{long:true});return;}
      enterRet=enterBattle(j);
      const rep=(j.战报||'').trim();
      if(rep&&/无法执行|未配置|内力不足|冷却|不存在/.test(rep.slice(0,120))){
        addSysLine('本回合未推进：'+rep.split('\n')[0].slice(0,80),{long:true});
      }
    }
  }catch(e){if(typeof e!=='string')addSysLine('战斗调用失败：'+e);}
  const finish=()=>{busy=false;renderBattle(lastBattle||{});};
  if(enterRet&&typeof enterRet.then==='function')enterRet.then(finish);
  else finish();
}
function floatCard(name,txt,cls){
  const card=document.getElementById('bc_'+name);if(!card)return;
  const f=el('div','float '+cls,txt);card.appendChild(f);
  setTimeout(()=>f.remove(),1800);
}
/* ================= 战斗结束统一弹框 =================
   胜利 → 逐人处决选择 → 确认后发 chat
   失败/平局 → 确认战果 → 确认后发 chat
   chat 统一在玩家点确认后才发送（exitBattle + sendHidden） */
function showBattleEndDialog(d){
  bEnded=true;
  const mask=$b('bEndMask'),card=$b('bEndCard');
  const stt=(d.战局状态||{}).状态||'';
  const win=/我方胜|敌方认输/.test(stt);
  const draw=/平局/.test(stt);
  card.className='endcard'+((win||draw)?'':' lose');
  /* ---- 构建战果摘要（两条路共用） ---- */
  const buildSummary=(decisions)=>{
    let s='【战斗已结束';
    if(win&&decisions)s+=' · 玩家处决裁定完成';
    s+='】战局状态='+JSON.stringify(d.战局状态||{})+
       '；战果='+JSON.stringify(d.战果||'')+
       '；经验结算='+JSON.stringify(d.经验结算||'');
    if(decisions)s+='；玩家对败方的逐人处置='+JSON.stringify(decisions);
    if(win&&decisions){
      s+='。请据此进行后续操作：按处决结果叙事终局后果（杀者经 死亡 条目落实、放者保留），'+
         '分发经验，judge 战后处置（战斗-结束 体力-20/时间+8、战利品/关系度等一并），返回 exploration-ui。';
    }else{
      s+='。请按战斗规则：'+(win?'判定处决与战后处置。':
         'GM 代敌方处置我方败方（据敌方立场/动机/关系度裁定生死或掠财/羞辱/俘虏等），')+
         '随后 judge 战后处置（含 战斗-结束 体力-20/时间+8）与后续剧情，返回 exploration-ui。';
    }
    return s;
  };
  /* ---- 确认后统一动作 ---- */
  const confirmAndSend=(decisions)=>{
    mask.classList.remove('show');
    exitBattle('auto');
    sendHidden(buildSummary(decisions));
  };

  if(win){
    /* ---- 胜利：处决选择 ---- */
    const cands=d.处决候选||[];
    card.innerHTML=`<div class="verdict">大 获 全 胜</div>`+
      `<div class="vsub">胜方处置败方，逐人裁定（逃走者不得处决）`+
      (cands.length?'':'——敌方全员已逃走，无可处决对象。')+`</div>`;
    const picks={};
    for(const c of cands){
      const row=document.createElement('div');row.className='exe-row';
      row.appendChild(Object.assign(document.createElement('span'),{className:'en',textContent:c.名称}));
      row.appendChild(Object.assign(document.createElement('span'),{className:'ec',textContent:'倒地不起，气息尚存'}));
      const kill=el('button','ebtn kill','杀'),spare=el('button','ebtn spare','放');
      kill.onclick=()=>{picks[c.名称]='杀';kill.classList.add('on');spare.classList.remove('on');refresh();};
      spare.onclick=()=>{picks[c.名称]='放';spare.classList.add('on');kill.classList.remove('on');refresh();};
      row.appendChild(kill);row.appendChild(spare);
      card.appendChild(row);
    }
    const go=el('button','gobtn',cands.length?'镌 定 裁 决':'继 续 战 后 处 置');
    const refresh=()=>{go.disabled=cands.some(c=>!picks[c.名称]);};
    refresh();
    go.onclick=()=>confirmAndSend(cands.map(c=>({角色:c.名称,决定:picks[c.名称]})));
    card.appendChild(go);
  }else{
    /* ---- 失败/平局：确认战果 ---- */
    card.innerHTML=`<div class="verdict">${draw?'难 分 高 下':'一 败 涂 地'}</div>`+
      `<div class="vsub">战报落定（${esc(stt)}）。GM 将代敌方处置并接续战后剧情。</div>`;
    const go=el('button','gobtn','确 认 战 果 · 静 候 处 置');
    go.onclick=()=>confirmAndSend(null);
    card.appendChild(go);
  }
  mask.classList.add('show');
}
/* 战前：先渲染剧情 card，玩家点击后才弹出操控选择面板 */
function showPreFightNarration(d){
  /* 先按 exploration-ui 的方式渲染剧情到舞台 */
  if(d.剧情描写||d.场景要素){
    applyExplorationState(Object.assign({},d,{界面:'exploration-ui'}));
  }
  /* 在剧情 card 后追加"点击继续"提示，点击后弹出操控选择 */
  const box=document.getElementById('stageIn');
  if(box){
    const hint=document.createElement('div');
    hint.className='expand-hint';
    hint.textContent='短兵相接，点击此处选择应战方式…';
    box.appendChild(hint);
    const stg=document.getElementById('stage');
    stg.classList.add('awaiting-click');
    /* 隐藏聊天框/足迹（和游历两阶段一样） */
    const composer=document.getElementById('composer');
    if(composer)composer.style.display='none';
    const logEl=document.getElementById('travelLog');
    if(logEl)logEl.style.display='none';
    stg.onclick=()=>{
      stg.classList.remove('awaiting-click');
      stg.onclick=null;
      if(hint.parentNode)hint.remove();
      if(composer)composer.style.display='none';  /* 战前不显示聊天框 */
      if(logEl)logEl.style.display='';
      showPreFight(d);
    };
  }else{
    showPreFight(d);
  }
}
function showPreFight(d){
  const pf=$b('preFight');if(!pf)return;
  pf.querySelector('.pf-ally').textContent=(d.我方||[]).join('、')||'—';
  pf.querySelector('.pf-foe').textContent=(d.敌方||[]).join('、')||'—';
  const box=pf.querySelector('.pfbtns');box.innerHTML='';
  const opts=(d.操控选项||[]).length?d.操控选项:['开战'];
  for(const opt of opts){
    const b=document.createElement('button');b.textContent=opt;
    b.onclick=()=>startBattle(d,opt);
    box.appendChild(b);
  }
  pf.classList.add('show');
}
/* 战前选择 → 直接调 engine judge 战斗-开始（不经 LLM）。
   选完即刻切战斗画面（不等 judge 返回），judge 到了再填充阵容 */
async function startBattle(d,ctrl){
  hidePreFight();
  /* showPreFight 从 SSE state 事件弹出，此时 busy 可能仍为 true（send 的 finally 还没跑）。
     startBattle 是玩家主动点按钮触发的新独立操作，不应受上一轮 busy 锁。 */
  busy=true;
  /* 立刻切战斗画面——给一个空骨架（"对阵"字样），让玩家马上看到战场而非干等游历界面 */
  setBattleMode(true);
  $b('bName').textContent='遭遇战';
  $b('bRound').textContent='';
  $b('bState').textContent='布阵中…';
  $b('bChain').innerHTML='<span class="clabel">行 动 预 告</span>';
  $b('bEnemy').innerHTML='';
  $b('bAlly').innerHTML='';
  const bLog=$b('bLog');if(bLog)bLog.innerHTML='';
  $b('bConsole').classList.add('locked');
  $b('bTurn').textContent='布阵中…';
  $b('bGrid').innerHTML='';
  let enterRet=null;
  try{
    const j=await engineJudge(
      [{"类型":"战斗-开始","我方":d.我方,"敌方":d.敌方,
        "允许逃跑":d.允许逃跑,"操控方式":ctrl}],
      {"当前剧情":`${(d.我方||[]).join('、')}与${(d.敌方||[]).join('、')}短兵相接，战局一触即发。`}
    );
    if(j.错误){addSysLine('开战失败：'+j.错误,{long:true});setBattleMode(false);busy=false;return;}
    if(!(j.界面==='battle-ui'||j.界面==='battle-end-ui')){
      addSysLine('开战返回异常（无 battle 界面）——战场保留未动。',{long:true});setBattleMode(false);busy=false;return;
    }
    enterRet=enterBattle(j);
  }catch(e){addSysLine('开战调用失败：'+e);setBattleMode(false);busy=false;return;}
  const finish=()=>{busy=false;renderBattle(lastBattle||{});};
  if(enterRet&&typeof enterRet.then==='function')enterRet.then(finish);
  else finish();
}
function hidePreFight(){const pf=$b('preFight');if(pf)pf.classList.remove('show');}
/* 独立发 hidden 消息给 GM——不经过 send()（不受 busy 拦截），但自带灯链 + 聊天锁，
   SSE 的 tool/delta/state 事件同样驱动节奏灯，done 时熄灯解锁 */
function sendHidden(msg){
  _turnTools=0;setSteps(1);
  $send.disabled=true;
  fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message:msg,session_id:sessionId})}).then(resp=>{
    if(!resp.ok){setSteps(-1);$send.disabled=false;return;}
    const reader=resp.body.getReader();const dec=new TextDecoder();let buf='';
    (function pump(){
      reader.read().then(({done,value})=>{
        if(done){setSteps(-1);$send.disabled=false;$input.focus();return;}
        buf+=dec.decode(value,{stream:true});
        let idx;
        while((idx=buf.indexOf('\n\n'))!==-1){
          const block=buf.slice(0,idx);buf=buf.slice(idx+2);
          let ev='',data='';
          for(const ln of block.split('\n')){
            if(ln.startsWith('event:'))ev=ln.slice(6).trim();
            else if(ln.startsWith('data:'))data+=ln.slice(5).trim();
          }
          if(!data){pump();return;}
          try{const dd=JSON.parse(data);
            if(ev==='session'&&dd.session_id){sessionId=dd.session_id;sessionStorage.setItem('wuxia_sid',sessionId);}
            else if(ev==='tool'){_turnTools++;_waitAppend('推演中：'+dd.name,dd.arguments||'');}
            else if(ev==='state'){syncSlot(dd);handleStateEvent(dd);_waitAppend('state: '+(dd.界面||'?'),JSON.stringify(dd,null,2));}
            else if(ev==='done'){setSteps(-1);$send.disabled=false;$input.focus();}
          }catch(e){}
          pump();
        }
      }).catch(()=>{setSteps(-1);$send.disabled=false;});
    })();
  }).catch(()=>{setSteps(-1);$send.disabled=false;});
}
/* 读档：经 LLM 通道发指令，让 GM 调 engine go 加载存档（LLM 上下文同步到新档）。
   发送后立即切到游历界面 + 启动节奏灯（结算→判盘→运笔），让玩家看到加载进度。 */
function sendLoadArchive(slot,target,label){
  const directive=`用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n`+
    `【读档指令】请以 engine go（槽位 ${slot}）执行 加载存档，目标："${target}"（存档名："${label}"）。\n`+
    `加载成功后 engine 返回 exploration-ui（含当前剧情/场景要素/队伍状态/经历概括），\n`+
    `请据此接续游戏会话——后续玩家输入按该存档状态执行。`;
  /* 立即切游历界面（从门厅/其他 TAB 切回），让玩家看到节奏灯而非干等门厅。
     不调 enterGame()——那会触发 refreshParty → 返回游戏 抢读未加载完的旧状态；
     SSE state 事件到了自然会刷右栏。 */
  setSlot(slot);
  if(gateMode){
    gateMode=false;
    document.body.classList.remove('gate');
    document.getElementById('gateTop').style.display='none';
  }
  activeTab='travel';showTab();
  _turnTools=0;setSteps(1);
  send(directive,{hidden:true});
}
document.getElementById('bExit').onclick=()=>{
  if(inBattle&&!bEnded){addSysLine('战斗进行中——打完方可离场');return;}
  exitBattle('auto');
};


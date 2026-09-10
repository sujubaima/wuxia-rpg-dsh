/* ================= 创建角色向导（UCF：零 LLM，模板生开场白） ================= */
const ATTRS=[
  {k:'内功',desc:'派生攻击力与内力上限'},
  {k:'力道',desc:'派生攻击力与气血上限'},
  {k:'身法',desc:'派生速度与防御力'},
  {k:'根骨',desc:'派生识破与气血上限'},
];
const ARTS=[
  {k:'搏击',desc:'搏击技能攻防'},{k:'剑法',desc:'剑法技能攻防'},{k:'刀法',desc:'刀法技能攻防'},
  {k:'长兵',desc:'长兵技能攻防'},{k:'奇门',desc:'奇门技能攻防'},{k:'暗器',desc:'暗器技能攻防'}];
const TECHS=[
  {k:'音律',desc:'抚琴品艺、以乐动情'},{k:'弈棋',desc:'手谈破局、推演解谜'},
  {k:'诗书',desc:'题诗和答、作文辨伪'},{k:'绘画',desc:'鉴画识真、绘制图章'},
  {k:'医术',desc:'诊脉辨毒、疗伤验尸'},{k:'博物',desc:'感知秘密、采集挖掘'}];
const POLARS=[
  {k:'内功',name:'阴阳',opts:['阴','阳','中'],desc:'阴:内力上限↑攻击力↓ / 阳:攻击力↑内力上限↓ / 中:无修正'},
  {k:'力道',name:'刚柔',opts:['刚','柔','中'],desc:'刚:暴击↑精准↓ / 柔:精准↑暴击↓ / 中:无修正'},
  {k:'身法',name:'动静',opts:['动','静','中'],desc:'动:速度↑防御力↓ / 静:防御力↑速度↓ / 中:无修正'},
  {k:'根骨',name:'巧拙',opts:['巧','拙','中'],desc:'巧:识破↑气血上限↓ / 拙:气血上限↑识破↓ / 中:无修正'},
];
const START_SKILLS=[
  {type:'搏击',name:'百缠手',school:'丐帮基础拳法',weapon:'拳套',desc:'丐帮入门拳掌，绵密缠打。'},
  {type:'剑法',name:'太乙玄门剑',school:'武当派基础剑法',weapon:'长剑',desc:'武当太极入门剑，圆融守中。'},
  {type:'刀法',name:'开阖刀法',school:'锦衣卫基础刀法',weapon:'朴刀',desc:'北镇抚司开合刀式，攻守兼备。'},
  {type:'长兵',name:'夜叉棍法',school:'少林寺基础棍法',weapon:'长棍',desc:'少林入门长棍，横扫直进。'},
  {type:'暗器',name:'蜻蜓点水势',school:'乌衣门基础暗器手法',weapon:'飞刀',desc:'乌衣门轻灵暗器手法，点到即走。'},
  {type:'奇门',name:'分水刺',school:'峨眉派基础奇门兵法',weapon:'峨眉刺',desc:'峨眉奇门短兵，近身分进。'},
];
const wiz={
  step:1,
  name:'',gender:'男',age:18,
  attrs:{内功:6,力道:6,身法:6,根骨:6}, // 24点:剩0（每项预分配6）
  arts:{搏击:6,剑法:6,刀法:6,长兵:6,奇门:6,暗器:6}, // 36点:剩0
  techs:{音律:6,弈棋:6,诗书:6,绘画:6,医术:6,博物:6}, // 36点:剩0
  polar:{内功:'中',力道:'中',身法:'中',根骨:'中'},
  skill:null,
};
const POOLS={attrs:24,arts:36,techs:36};
const PCAP=12;

function wizPoolLeft(group){
  const total=Object.values(wiz[group]).reduce((a,b)=>a+b,0);
  return POOLS[group]-total;
}
function openCreate(){
  document.getElementById('modCreate').classList.add('show');
  wiz.step=1;renderWiz();
}
function closeCreate(){
  document.getElementById('modCreate').classList.remove('show');
  document.getElementById('createErr').textContent='';
}
function renderWiz(){
  document.getElementById('createErr').textContent='';
  document.getElementById('wizStep').textContent=
    wiz.step===1?'—— 第一步 · 立名 ——':wiz.step===2?'—— 第二步 · 分配资质 ——':'—— 第三步 · 选择初始武学 ——';
  document.getElementById('wizPrev').style.display=wiz.step>1?'':'none';
  document.getElementById('wizNext').textContent=wiz.step===3?'完成建号':'下一步';
  const body=document.getElementById('wizBody');body.innerHTML='';
  if(wiz.step===1)renderWiz1(body);
  else if(wiz.step===2)renderWiz2(body);
  else renderWiz3(body);
}

/* —— 第一步 立名 —— */
function renderWiz1(body){
  const r=el('div','wrow');
  // 姓名
  const f1=el('div','wfield');f1.appendChild(el('label',null,'姓名'));
  const n=el('input');n.value=wiz.name;n.maxLength=12;n.placeholder='如 沈听雪';
  n.oninput=()=>{wiz.name=n.value.trim();};f1.appendChild(n);r.appendChild(f1);
  // 性别
  const f2=el('div','wfield');f2.appendChild(el('label',null,'性别'));
  const g=el('select');for(const v of ['男','女']){const o=el('option');o.value=v;o.textContent=v;g.appendChild(o);}
  g.value=wiz.gender;g.onchange=()=>{wiz.gender=g.value;};f2.appendChild(g);r.appendChild(f2);
  // 年龄
  const f3=el('div','wfield');f3.appendChild(el('label',null,'年龄（16~80）'));
  const a=el('input');a.type='number';a.min=16;a.max=80;a.value=wiz.age;
  a.oninput=()=>{wiz.age=parseInt(a.value,10)||16;};f3.appendChild(a);r.appendChild(f3);
  body.appendChild(r);
  body.appendChild(el('div','tips','姓名 1~12 字，不得与江湖已有角色重名；性别男/女；年龄须满十六且不逾八旬。'));
}

/* —— 第二步 分配资质 —— */
function allocGrid(body,title,group,defs,tipText){
  const pts=el('div','pts');
  const left=wizPoolLeft(group);
  pts.innerHTML=`<b>${title}</b>　剩余 <span class="pool" id="pool_${group}">${left}</span> 点　单项 ≤ ${PCAP}`;
  body.appendChild(pts);
  const g=el('div','alloc');
  for(const d of defs){
    const row=el('div','a-item');
    row.appendChild(el('span','nm',d.k));
    const minus=el('button','abtn','−');
    const val=el('span','val',String(wiz[group][d.k]));
    val.id=`val_${group}_${d.k}`;
    const plus=el('button','abtn','＋');
    minus.onclick=()=>{
      if(wiz[group][d.k]>0){wiz[group][d.k]--;renderAllocVal(group,d.k);}
    };
    plus.onclick=()=>{
      if(wiz[group][d.k]<PCAP&&wizPoolLeft(group)>0){wiz[group][d.k]++;renderAllocVal(group,d.k);}
    };
    row.appendChild(minus);row.appendChild(val);row.appendChild(plus);
    row.title=d.desc;
    g.appendChild(row);
  }
  body.appendChild(g);
  if(tipText)body.appendChild(el('div','tips',tipText));
}
function renderAllocVal(group,k){
  document.getElementById(`val_${group}_${k}`).textContent=wiz[group][k];
  document.getElementById(`pool_${group}`).textContent=wizPoolLeft(group);
}
/* 随机分配：归零后逐点随机落位，单项≤PCAP，池子分完为止 */
function randomAlloc(group,defs){
  const keys=defs.map(d=>d.k);
  for(const k of keys)wiz[group][k]=0;
  let left=POOLS[group],guard=left*100+200;
  while(left>0&&guard-->0){
    const k=keys[Math.floor(Math.random()*keys.length)];
    if(wiz[group][k]<PCAP){wiz[group][k]++;left--;}
  }
}
/* 随机极性：四项分别在其可选值中等概率取一（含"中"） */
function randomPolar(){
  for(const d of POLARS){
    wiz.polar[d.k]=d.opts[Math.floor(Math.random()*d.opts.length)];
  }
}
function renderWiz2(body){
  const bar2=el('div','wrow');
  const randBtn=uiBtn('🎲 随机分配','primary');
  randBtn.title='一次性把 基础属性24 / 武艺36 / 技艺36 三池随机分完（单项≤12）并随机四项极性，可再手动微调';
  randBtn.onclick=()=>{
    randomAlloc('attrs',ATTRS);randomAlloc('arts',ARTS);randomAlloc('techs',TECHS);
    randomPolar();
    renderWiz();
  };
  bar2.appendChild(randBtn);
  body.appendChild(bar2);
  allocGrid(body,'基础属性（派生命/攻/速/防/识破）','attrs',ATTRS,'每项预分配6点，合计24点已满，仅可调整单项分布（单项≤12）。');
  allocGrid(body,'武艺（对应武学攻防）','arts',ARTS,'合计36点必须分完。');
  allocGrid(body,'技艺（游历判定）','techs',TECHS,'合计36点必须分完。');
  // 极性
  const ptPolar=el('div','pts');ptPolar.innerHTML='<b>极性</b>　各择其一';body.appendChild(ptPolar);
  const p=el('div','polar');
  for(const d of POLARS){
    const it=el('div','p-item');
    it.appendChild(el('span','nm',d.name));
    const s=el('select');
    for(const v of d.opts){const o=el('option');o.value=v;o.textContent=v;s.appendChild(o);}
    s.value=wiz.polar[d.k];s.onchange=()=>{wiz.polar[d.k]=s.value;};
    it.appendChild(s);it.title=d.desc;
    p.appendChild(it);
  }
  body.appendChild(p);
  body.appendChild(el('div','tips','极性微调同一属性的两个派生方向，中=无修正，可随时参考上方描述。'));
}

/* —— 第三步 选择初始武学 —— */
function renderWiz3(body){
  body.appendChild(el('div','tips','择一门入门武学并配发对应兵器（习武方向不必与武艺加点一致，但相符更顺）。'));
  const gp=el('div','skillpick');
  for(const s of START_SKILLS){
    const card=el('div','sk'+(wiz.skill===s.type?' sel':''));
    card.appendChild(el('div','sn',`《${s.name}》`));
    card.appendChild(el('div','sd',`${s.school} ｜ 配发【${s.weapon}】 ｜ ${s.desc}`));
    card.onclick=()=>{wiz.skill=s.type;renderWiz();};
    gp.appendChild(card);
  }
  body.appendChild(gp);
}

/* —— 向导提交 —— */
function wizNext(){
  const err=document.getElementById('createErr');
  if(wiz.step===1){
    if(!wiz.name){err.textContent='请赐姓名。';return;}
    if(!(wiz.age>=16&&wiz.age<=80)){err.textContent='年龄须年满十六且不逾八旬（16~80）。';return;}
    wiz.step=2;renderWiz();return;
  }
  if(wiz.step===2){
    for(const g of ['attrs','arts','techs']){
      if(wizPoolLeft(g)!==0){err.textContent='点数尚未分完（各池需恰好用完）。';return;}
    }
    wiz.step=3;renderWiz();return;
  }
  // step3: submit
  if(!wiz.skill){err.textContent='请择一门入门武学。';return;}
  submitCreate();
}
async function submitCreate(){
  const err=document.getElementById('createErr');
  const sk=START_SKILLS.find(s=>s.type===wiz.skill);
  /* 跨档重名拦截：引擎只查基线+当前slot写入域，不查其他 slot——前端先核全档 */
  err.textContent='校验姓名与槽位…';
  let nextSlot=0;
  try{
    const all=await fetchUi({"类型":"开始游戏"});
    const clash=(all.存档列表||[]).find(s=>(s.角色名||'')===wiz.name);
    if(clash){err.textContent=`「${wiz.name}」已有人在闯江湖（slot ${clash.slot}），请另起一名。`;return;}
    nextSlot=Number(all.next_slot);
    if(!Number.isInteger(nextSlot)||nextSlot<=0){err.textContent='未取得可用存档槽位，请稍后重试。';return;}
  }catch(e){err.textContent='读取存档槽位失败，请稍后重试。';return;}
  /* 向导只收集机械参数：不代填人设（GM 创作）、不调引擎（建号与开场都是 GM 的事）。
     把"不含人设"的档案原样交给 LLM，由它补人设→创建角色→初入江湖→渲染首屏。 */
  const char={
    "名称":wiz.name,"性别":wiz.gender,"年龄":wiz.age,"阵营":"我方",
    "一级属性":{...wiz.attrs},
    "极性":{...wiz.polar},
    "武艺":{...wiz.arts},
    "技艺":{...wiz.techs},
    "武学":[{"名称":sk.name,"等级":1}],
    "携带技能":[sk.name],
    "携带物品":[],
    "运转心法":null,
    "装备":{"武器1":sk.weapon,"武器2":null,"护甲":null,"饰品":null,"冠巾":null},
    "物品":[]
  };
  const directive=
    `用户正在 wuxia-rpg 游戏中，请加载 skill wuxia-rpg。\n`+
    `【建号委托】玩家已进入 wuxia-rpg 游戏会话（此消息起，玩家输入原则上都是游戏指令，按游戏规则执行）。\n`+
    `玩家经创建向导选定角色参数（档案尚未落盘，人设留空）。\n`+
    `初始可用槽位：${nextSlot}\n`+
    `角色档案：${JSON.stringify(char)}\n`+
    `请按序完成：1) 为该角色撰写「人设」（性格/背景，不得点明具体目的与伏笔、不得有明确门派归属）并入档案；`+
    `2) 携完整档案调用「创建角色」，wuxia_go 顶层槽位首次必须传 ${nextSlot}；若仅返回错误码 slot_occupied，读取响应 next_slot 并以同一完整档案继续重试，其他错误立即停止；`+
    `3) 建号成功后据落点与时辰撰写开场白与初始剧情，以下一条 engine.py judge（顶层 \`当前剧情\`/\`场景要素\`/\`经历概括\`）`+
    `完成首屏渲染（exploration-ui）。`+
  closeCreate();
  enterGame();   /* 先入主界面，再让 GM 开工——用户能看着它一步步调工具 */
  send(directive,{hidden:true});
}

document.getElementById('btnCreate').onclick=openCreate;
document.getElementById('wizCancel').onclick=closeCreate;
document.getElementById('wizPrev').onclick=()=>{wiz.step--;renderWiz();};
document.getElementById('wizNext').onclick=wizNext;


/* ================= 游历聊天 ================= */
let sessionId=sessionStorage.getItem('wuxia_sid')||'';
let busy=false;

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function renderInline(s){
  s=esc(s);
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g,'<em>$1</em>');
  s=s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function render(text){
  if(!text)return '';
  const lines=text.replace(/\r\n/g,'\n').split('\n');
  const out=[];let i=0,para=[];
  const flushPara=()=>{if(para.length){out.push('<p>'+para.map(renderInline).join('<br>')+'</p>');para=[];}};
  while(i<lines.length){
    let ln=lines[i];
    const fence=ln.match(/^```(\w*)/);
    if(fence){flushPara();const lang=fence[1]||'';const code=[];i++;
      while(i<lines.length&&!lines[i].startsWith('```')){code.push(lines[i]);i++;}i++;
      out.push('<pre><code class="lang-'+esc(lang)+'">'+esc(code.join('\n'))+'</code></pre>');continue;}
    if(/^\s*([-*_])\1{2,}\s*$/.test(ln)){flushPara();out.push('<hr>');i++;continue;}
    const h=ln.match(/^(#{1,6})\s+(.*)$/);
    if(h){flushPara();const l=h[1].length;out.push('<h'+l+'>'+renderInline(h[2])+'</h'+l+'>');i++;continue;}
    if(/^>\s?/.test(ln)){flushPara();const q=[];
      while(i<lines.length&&/^>\s?/.test(lines[i])){q.push(lines[i].replace(/^>\s?/,''));i++;}
      out.push('<blockquote>'+renderInline(q.join('\n').replace(/\n/g,'<br>'))+'</blockquote>');continue;}
    if(/^\s*[-*+]\s+/.test(ln)){flushPara();const items=[];
      while(i<lines.length&&/^\s*[-*+]\s+/.test(lines[i])){items.push('<li>'+renderInline(lines[i].replace(/^\s*[-*+]\s+/,''))+'</li>');i++;}
      out.push('<ul>'+items.join('')+'</ul>');continue;}
    if(/^\s*\d+\.\s+/.test(ln)){flushPara();const items=[];
      while(i<lines.length&&/^\s*\d+\.\s+/.test(lines[i])){items.push('<li>'+renderInline(lines[i].replace(/^\s*\d+\.\s+/,''))+'</li>');i++;}
      out.push('<ol>'+items.join('')+'</ol>');continue;}
    if(i+1<lines.length&&/\|/.test(ln)&&/^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1])){
      flushPara();const rows=[];
      const header=ln.split('|').map(c=>c.trim()).slice(ln.startsWith('|')?1:0,ln.endsWith('|')?-1:undefined);
      i+=2;rows.push('<tr>'+header.map(c2=>'<th>'+renderInline(c2)+'</th>').join('')+'</tr>');
      while(i<lines.length&&/\|/.test(lines[i])){
        const cells=lines[i].split('|').slice(ln.startsWith('|')?1:0,ln.endsWith('|')?-1:undefined).map(c2=>c2.trim());
        rows.push('<tr>'+cells.map(c2=>'<td>'+renderInline(c2)+'</td>').join('')+'</tr>');i++;}
      out.push('<table>'+rows.join('')+'</table>');continue;}
    if(!ln.trim()){flushPara();i++;continue;}
    para.push(ln);i++;
  }
  flushPara();return out.join('');
}
function scrollDown(){$msgs.scrollTop=$msgs.scrollHeight;}
function addRow(role,text){
  const row=el('div','row '+role);
  const av=el('div','avatar',role==='user'?'侠':'GM');
  const bub=el('div','bubble');
  if(text!=null)bub.innerHTML=role==='user'?esc(text):render(text);
  row.appendChild(av);row.appendChild(bub);$msgs.appendChild(row);scrollDown();return bub;
}
function setStatus(t){$status.innerHTML=t;}

/* opts.hidden：内部指令（如建号委托），发给 LLM 但不渲染用户气泡、不写入日志 */
async function send(msg,opts){
  opts=opts||{};
  msg=(msg!=null?msg:$input.value).trim();
  if(!msg||busy)return;
  busy=true;$send.disabled=true;$input.value='';$input.style.height='auto';
  if(!opts.hidden)addRow('user',msg);
  const bub=addRow('assistant','');bub._segs=[];bub.classList.add('cursor');
  pendingUser=opts.hidden?null:msg;
  setStatus('<span class="dot">●</span> 正在运笔…');
  /* A1：回合节奏灯进场（结算亮起，事件推进） */
  _turnTools=0;setSteps(1);
  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg,session_id:sessionId})});
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    const reader=resp.body.getReader();const dec=new TextDecoder();let buf='';
    while(true){
      const {done,value}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      let idx;
      while((idx=buf.indexOf('\n\n'))!==-1){const block=buf.slice(0,idx);buf=buf.slice(idx+2);handleEvent(block,bub);}
    }
  }catch(e){bub.innerHTML='<span class="err">连接失败：'+e.message+'</span>';}
  finally{
    bub.classList.remove('cursor');
    if(!bub.innerHTML.trim())bub.innerHTML='<span class="err">（无内容返回）</span>';
    setStatus('');saveLog(pendingUser,bub._segs||[]);pendingUser=null;
    setSteps(-1);
    busy=false;$send.disabled=false;$input.focus();
    /* 不再调 refreshParty()——SSE state 事件已通过 routeUi 刷过右栏（exploration-ui 带 队伍状态/体力/金钱）。
       战斗态右栏由 enterBattle 管理；无 state 事件的纯闲聊回合右栏保持上轮值，可接受。 */
  }
}
function handleEvent(block,bub){
  let evType='',dataLine='';
  for(const ln of block.split('\n')){
    if(ln.startsWith('event:'))evType=ln.slice(6).trim();
    else if(ln.startsWith('data:'))dataLine+=ln.slice(5).trim();
  }
  if(!dataLine)return;
  let data;try{data=JSON.parse(dataLine);}catch{return;}
  if(evType==='session'){sessionId=data.session_id;sessionStorage.setItem('wuxia_sid',sessionId);}
  else if(evType==='delta'){appendDelta(bub,data.text);scrollDown();}
  else if(evType==='tool'){
    if(bub.childNodes.length&&!lastIsTools(bub))bub.appendChild(document.createTextNode('\n'));
    const group=lastIsTools(bub)?bub.lastChild:newToolsGroup(bub);
    group.appendChild(el('span','tool','◆ 运算：'+data.name));
    if(!bub._segs)bub._segs=[];bub._segs.push({kind:'tool',name:data.name});
    _turnTools++;
    _waitAppend('推演中：'+data.name,data.arguments);
    scrollDown();
  }else if(evType==='state'){
    syncSlot(data);
    handleStateEvent(data);
    _waitAppend('state: '+(data.界面||'?'),JSON.stringify(data,null,2));
  }else if(evType==='error'){
    bub.appendChild(el('span','err','[错误] '+data.message));
  }else if(evType==='done'){
    if(data.error&&data.result)bub.appendChild(el('span','err','[未完成] '+data.result));
    setSteps(-1);
  }
}
function lastIsTools(bub){const l=bub.lastChild;return l&&l.nodeType===1&&l.classList&&l.classList.contains('tools');}
function newToolsGroup(bub){const g=el('div','tools');bub.appendChild(g);return g;}
function mdContainer(bub){
  if(lastIsTools(bub)||!bub.lastChild||!bub.lastChild.classList||!bub.lastChild.classList.contains('md'))
    bub.appendChild(el('div','md'));
  return bub.lastChild;
}
let pendingUser=null;
function appendDelta(bub,text){
  if(!text)return;
  if(!bub._segs)bub._segs=[];
  const last=bub._segs[bub._segs.length-1];
  if(last&&last.kind==='text')last.text+=text;
  else{const seg={kind:'text',text};bub._segs.push(seg);pushMd(bub,seg);}
  const seg=bub._segs[bub._segs.length-1];
  seg._el.innerHTML=render(seg.text);
}
function pushMd(bub,seg){if(lastIsTools(bub))bub.appendChild(document.createTextNode('\n'));seg._el=mdContainer(bub);}

function saveLog(userText,segs){
  const clean=segs.map(s=>s.kind==='text'?{kind:'text',text:s.text}:{kind:'tool',name:s.name});
  try{
    const log=JSON.parse(sessionStorage.getItem(LOG_KEY)||'[]');
    if(userText!=null)log.push({role:'user',text:userText});
    log.push({role:'assistant',segs:clean});
    sessionStorage.setItem(LOG_KEY,JSON.stringify(log));
  }catch(e){}
}
function renderSegs(bub,segs){
  if(!bub._segs)bub._segs=[];
  for(const s of segs){
    if(s.kind==='text'){const seg={kind:'text',text:s.text};bub._segs.push(seg);pushMd(bub,seg);seg._el.innerHTML=render(seg.text);}
    else if(s.kind==='tool'){
      if(bub.childNodes.length&&!lastIsTools(bub))bub.appendChild(document.createTextNode('\n'));
      const group=lastIsTools(bub)?bub.lastChild:newToolsGroup(bub);
      group.appendChild(el('span','tool','◆ 运算：'+s.name));
      bub._segs.push({kind:'tool',name:s.name});
    }
  }
}
function loadLog(){
  let log;try{log=JSON.parse(sessionStorage.getItem(LOG_KEY)||'[]');}catch{log=[];}
  for(const m of log){
    if(m.role==='user')addRow('user',m.text);
    else if(m.role==='sys'){/* 历史 sys 条目不再回显，直接跳过 */}
    else{const bub=addRow('assistant','');renderSegs(bub,m.segs||[]);}
  }
}

$form.addEventListener('submit',e=>{e.preventDefault();send();});
$input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
$input.addEventListener('input',()=>{$input.style.height='auto';$input.style.height=Math.min($input.scrollHeight,160)+'px';});
$new.addEventListener('click',()=>{
  if(busy)return;
  if(sessionId&&!confirm('开新一卷？当前对话将不再续接。'))return;
  sessionId='';sessionStorage.removeItem('wuxia_sid');sessionStorage.removeItem(LOG_KEY);
  $msgs.innerHTML='';$input.focus();
});


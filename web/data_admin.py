#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""武侠RPG 数据管理台 —— 本地 Web 页面，经 dao.py 统一读写 assets/data/ 下各类数据。

仅本机调试用：绑定 127.0.0.1，无鉴权。启动后浏览器访问 http://127.0.0.1:PORT/ 。

功能：
  - 五类数据（角色/武学/物品/状态/阵营）浏览、搜索、查看完整 JSON
  - 在线编辑 JSON 并保存（保存前自动备份旧文件到 assets/data/.backups/）
  - 新建条目（按类型给出模板骨架）、删除条目
  - 保存时校验 JSON 合法性，并强制 record["名称"] 与文件名一致

所有读写经 scripts/dao.py，与引擎同源。
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
# 引擎脚本在 ../wuxia-rpg/scripts，加入 sys.path 以便 import dao 等模块
SCRIPTS = os.path.join(HERE, "..", "wuxia-rpg", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import dao as dq  # noqa: E402

# 备份目录跟着 dao 的数据根走，与引擎同源；data_admin 放置位置无关
BACKUP_DIR = os.path.join(dq.DATA_DIR, ".backups")

KINDS = ["角色", "武学", "物品", "状态", "阵营"]
KIND_LABEL = {"角色": "角色", "武学": "武学", "物品": "物品", "状态": "状态", "阵营": "阵营"}

# 新建条目模板骨架（仅放最常见字段，用户自行补全）
TEMPLATES = {
    "角色": {"名称": "新角色", "性别": "男", "年龄": 20, "阵营": "散人",
             "一级属性": {"内功": 5, "力道": 5, "身法": 5, "根骨": 5},
             "极性": {"内功": "中", "力道": "中", "身法": "中", "根骨": "中"},
             "武艺": {}, "技艺": {}, "武学": [], "运转心法": "",
             "携带技能": [], "携带物品": [], "装备": {}, "物品": [],
             "经验值": 0, "关系度": 50, "人设": ""},
    "武学": {"名称": "新武学", "描述": "", "招式": [], "品级": None, "类型": "剑法",
             "威力倍率": 1.0, "内力消耗": 20, "冷却时间": 0, "技能特效": "",
             "等级增益": []},
    "物品": {"名称": "新物品", "类型": "消耗品", "子类型": "丹药", "品级": 0,
             "描述": "", "使用效果": {}, "价格": 0},
    "状态": {"id": "new_buff", "名称": "新状态", "类型": "正向",
             "效果": "", "叠加方式": "不可叠加"},
    "阵营": {"名称": "新阵营", "描述": "", "地理位置": "", "成员": [], "武学": []},
}

# 各类型用于决定分组目录的关键字段
GROUP_FIELD = {"角色": "阵营", "武学": "类型", "物品": "子类型"}


def list_entries(kind):
    """返回 [{name, group}]，group 为二级分组目录名（非分组类型为空串）。"""
    paths = dq._scan_kind(kind)
    out = []
    grouped = kind in dq._GROUPED
    for name, path in paths.items():
        group = os.path.basename(os.path.dirname(path)) if grouped else ""
        out.append({"name": name, "group": group})
    out.sort(key=lambda x: (x["group"], x["name"]))
    return out


def backup_then_save(kind, record):
    """保存前把旧文件备份到 assets/data/.backups/<kind>/<name>.<ts>.json，再 upsert。"""
    name = record.get("名称")
    if not name:
        return False, "记录缺少「名称」字段"
    existing = dq._scan_kind(kind).get(name)
    if existing and os.path.exists(existing):
        os.makedirs(os.path.join(BACKUP_DIR, kind), exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        bak = os.path.join(BACKUP_DIR, kind, f"{name}.{ts}.json")
        try:
            with open(existing, encoding="utf-8") as f:
                old = f.read()
            with open(bak, "w", encoding="utf-8") as f:
                f.write(old)
        except OSError:
            pass
    dq.upsert(kind, record)
    return True, None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默默认日志
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        path = parsed.path
        if path == "/" or path == "/index.html":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/list":
            kind = q.get("kind", [""])[0]
            if kind not in KINDS:
                self._json({"error": "未知类型"}, 400)
                return
            self._json({"entries": list_entries(kind)})
            return
        if path == "/api/get":
            kind = q.get("kind", [""])[0]
            name = q.get("name", [""])[0]
            if kind not in KINDS:
                self._json({"error": "未知类型"}, 400)
                return
            rec = dq.get(kind, name)
            if rec is None:
                self._json({"error": f"未找到{kind}【{name}】"}, 404)
                return
            self._json({"record": rec})
            return
        if path == "/api/template":
            kind = q.get("kind", [""])[0]
            if kind not in KINDS:
                self._json({"error": "未知类型"}, 400)
                return
            self._json({"record": TEMPLATES[kind]})
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            record = json.loads(raw) if raw else None
        except json.JSONDecodeError as e:
            self._json({"error": f"JSON 解析失败：{e}"}, 400)
            return
        if path == "/api/save":
            kind = q.get("kind", [""])[0]
            if kind not in KINDS:
                self._json({"error": "未知类型"}, 400)
                return
            if not isinstance(record, dict):
                self._json({"error": "请求体需为 JSON 对象"}, 400)
                return
            # 关键字段存在性提示（分组类型）
            gf = GROUP_FIELD.get(kind)
            if gf and not record.get(gf):
                self._json({"error": f"缺少分组关键字段「{gf}」（决定落盘子目录）"}, 400)
                return
            ok, err = backup_then_save(kind, record)
            if not ok:
                self._json({"error": err}, 400)
                return
            self._json({"ok": True, "name": record["名称"],
                        "entries": list_entries(kind)})
            return
        if path == "/api/derive":
            # 角色派生预览：基于编辑器当前 JSON 实时派生
            kind = q.get("kind", [""])[0]
            if kind != "角色":
                self._json({"error": "仅角色支持派生预览"}, 400)
                return
            if not isinstance(record, dict):
                self._json({"error": "请求体需为 JSON 对象"}, 400)
                return
            prim = record.get("一级属性")
            pol = record.get("极性")
            if not prim or not pol:
                self._json({"error": "缺少「一级属性」或「极性」字段，无法派生"}, 400)
                return
            try:
                base_sec = dq.derive_secondary(prim, pol)
                base = {
                    "气血上限": base_sec["气血上限"],
                    "内力上限": base_sec["内力上限"],
                    "攻击力": base_sec["攻击力"], "防御力": base_sec["防御力"],
                    "精准": base_sec["精准"], "识破": base_sec["识破"],
                    "速度": base_sec["速度"], "暴击": base_sec["暴击"],
                    "经验加成": base_sec["经验加成"],
                }
                chars_db = dq.load_all("角色")
                skills_db = dq.load_all("武学")
                full = dq.derive_character(record, chars_db, skills_db)
                full_view = {
                    "气血上限": full.get("气血上限"), "内力上限": full.get("内力上限"),
                    "二级属性": full.get("二级属性", {}),
                    "武艺(含反哺与装备)": full.get("武艺", {}),
                    "装备": full.get("装备", {}),
                }
                self._json({"基础派生": base, "完整派生": full_view})
            except Exception as e:
                self._json({"error": f"派生失败：{e}"}, 500)
            return
        if path == "/api/delete":
            kind = q.get("kind", [""])[0]
            name = q.get("name", [""])[0]
            if kind not in KINDS:
                self._json({"error": "未知类型"}, 400)
                return
            existing = dq._scan_kind(kind).get(name)
            if not existing:
                self._json({"error": f"未找到{kind}【{name}】"}, 404)
                return
            # 删前备份
            os.makedirs(os.path.join(BACKUP_DIR, kind), exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            bak = os.path.join(BACKUP_DIR, kind, f"{name}.{ts}.deleted.json")
            try:
                with open(existing, encoding="utf-8") as f:
                    old = f.read()
                with open(bak, "w", encoding="utf-8") as f:
                    f.write(old)
            except OSError:
                pass
            dq.delete(kind, name)
            self._json({"ok": True, "entries": list_entries(kind)})
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>武侠RPG 数据管理台</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background:#1b1f24; color:#d7dde3; height:100vh; display:flex; flex-direction:column; }
  header { padding:10px 16px; background:#0d1117; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:16px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .tabs { display:flex; gap:4px; }
  .tab { padding:6px 14px; border-radius:6px; cursor:pointer; font-size:14px;
         background:#21262d; border:1px solid #30363d; }
  .tab.active { background:#2f81f7; color:#fff; border-color:#2f81f7; }
  main { flex:1; display:flex; min-height:0; }
  .sidebar { width:280px; border-right:1px solid #30363d; display:flex; flex-direction:column; min-height:0; }
  .sidebar .search { padding:8px; border-bottom:1px solid #30363d; }
  .sidebar input { width:100%; padding:6px 8px; background:#0d1117; color:#d7dde3;
                   border:1px solid #30363d; border-radius:5px; font-size:13px; }
  .list { flex:1; overflow:auto; }
  .item { padding:6px 12px; cursor:pointer; border-bottom:1px solid #21262d; font-size:13px; }
  .item:hover { background:#21262d; }
  .item.active { background:#1f2a3a; border-left:3px solid #2f81f7; padding-left:9px; }
  .item .grp { color:#768390; font-size:11px; margin-left:6px; }
  .editor { flex:1; display:flex; flex-direction:column; min-width:0; }
  .toolbar { padding:8px 12px; border-bottom:1px solid #30363d; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .toolbar .title { font-weight:600; margin-right:auto; font-size:14px; }
  button { padding:5px 12px; border-radius:5px; border:1px solid #30363d; background:#21262d;
           color:#d7dde3; cursor:pointer; font-size:13px; }
  button:hover { background:#30363d; }
  button.primary { background:#2f81f7; border-color:#2f81f7; color:#fff; }
  button.primary:hover { background:#1f6feb; }
  button.danger { background:#da3633; border-color:#da3633; color:#fff; }
  .content { flex:1; display:flex; min-height:0; }
  textarea { flex:1; background:#0d1117; color:#c9d1d9; border:none; outline:none;
             padding:12px; font-family:"SF Mono", Consolas, monospace; font-size:13px;
             line-height:1.5; resize:none; tab-size:2; min-width:0; }
  .status { padding:6px 12px; border-top:1px solid #30363d; font-size:12px; color:#768390;
            background:#0d1117; min-height:28px; }
  .status.err { color:#f85149; }
  .status.ok { color:#3fb950; }
  .empty { color:#768390; padding:24px; text-align:center; }
  /* 保存成功提示 */
  .toast { position:fixed; top:20px; left:50%; transform:translateX(-50%) translateY(-20px);
           background:#238636; color:#fff; padding:10px 22px; border-radius:6px; font-size:14px;
           box-shadow:0 4px 12px rgba(0,0,0,.4); opacity:0; pointer-events:none;
           transition:opacity .2s, transform .2s; z-index:100; }
  .toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
  .toast.err { background:#da3633; }
  /* 右侧派生面板 */
  .derive-panel { width:380px; min-width:300px; flex-shrink:0; border-left:1px solid #30363d;
                  background:#0d1117; display:none; flex-direction:column; }
  .derive-panel.show { display:flex; }
  .dp-head { padding:8px 12px; border-bottom:1px solid #30363d; display:flex; align-items:center;
             gap:8px; }
  .dp-title { font-size:13px; font-weight:600; margin-right:auto; }
  .dp-body { flex:1; overflow:auto; padding:4px 0 12px; }
  .derive-panel h3 { font-size:12px; margin:12px 12px 6px; color:#768390; font-weight:600;
                     border-bottom:1px solid #21262d; padding-bottom:4px; }
  .derive-panel table { border-collapse:collapse; width:100%; font-size:12px; }
  .derive-panel td { padding:3px 12px; border-bottom:1px solid #21262d; }
  .derive-panel td.k { color:#768390; width:130px; }
  .derive-panel td.v { color:#c9d1d9; font-family:"SF Mono",Consolas,monospace; word-break:break-all; }
  .derive-panel .note { font-size:11px; color:#768390; margin:12px 12px; line-height:1.5; }
</style>
</head>
<body>
<header>
  <h1>武侠RPG 数据管理台</h1>
  <div class="tabs" id="tabs"></div>
</header>
<main>
  <aside class="sidebar">
    <div class="search"><input id="search" placeholder="搜索名称…"></div>
    <div class="list" id="list"></div>
  </aside>
  <section class="editor">
    <div class="toolbar">
      <span class="title" id="curTitle">—</span>
      <button id="btnNew">新建</button>
      <button id="btnFormat">格式化</button>
      <button id="btnReload">重载</button>
      <button id="btnDerive" style="display:none">派生预览</button>
      <button id="btnDelete" class="danger">删除</button>
      <button id="btnSave" class="primary">保存</button>
    </div>
    <div class="content">
      <textarea id="editor" spellcheck="false" placeholder="选择左侧条目查看 / 编辑…"></textarea>
      <aside class="derive-panel" id="derivePanel">
        <div class="dp-head">
          <span class="dp-title">派生预览 · <span id="deriveName">—</span></span>
          <button id="btnDeriveClose">关闭</button>
        </div>
        <div class="dp-body">
          <h3>基础派生（一级属性 + 极性）</h3>
          <div id="baseTable"></div>
          <h3>完整派生（武学反哺 + 装备加成）</h3>
          <div id="fullTable"></div>
          <div class="note">完整派生与战斗内核同源（dao.derive_character）。编辑器内修改一级属性/极性/武学/装备后点「派生预览」可实时查看，无需保存。</div>
        </div>
      </aside>
    </div>
    <div class="status" id="status">就绪</div>
  </section>
</main>
<div class="toast" id="toast"></div>
<script>
const KINDS = ["角色","武学","物品","状态","阵营"];
let curKind = "角色";
let curName = null;
let entries = [];

const $ = id => document.getElementById(id);
const tabsEl = $("tabs"), listEl = $("list"), editorEl = $("editor"),
      statusEl = $("status"), searchEl = $("search"), titleEl = $("curTitle");

function setStatus(msg, cls){ statusEl.textContent = msg; statusEl.className = "status" + (cls?" "+cls:""); }

let toastTimer = null;
function toast(msg, cls){
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (cls?" "+cls:"");
  if(toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>{ t.className = "toast" + (cls?" "+cls:""); }, 1800);
}

function renderTabs(){
  tabsEl.innerHTML = "";
  KINDS.forEach(k=>{
    const d = document.createElement("div");
    d.className = "tab" + (k===curKind?" active":"");
    d.textContent = k;
    d.onclick = ()=>{ curKind=k; curName=null; renderTabs(); loadList(); editorEl.value=""; titleEl.textContent="—"; };
    tabsEl.appendChild(d);
  });
  $("btnDerive").style.display = (curKind==="角色") ? "" : "none";
}

function renderList(filter=""){
  listEl.innerHTML = "";
  const f = filter.trim().toLowerCase();
  const items = entries.filter(e=> !f || e.name.toLowerCase().includes(f));
  if(!items.length){ listEl.innerHTML = '<div class="empty">（无）</div>'; return; }
  items.forEach(e=>{
    const d = document.createElement("div");
    d.className = "item" + (e.name===curName?" active":"");
    d.innerHTML = `<span>${escapeHtml(e.name)}</span>` + (e.group?`<span class="grp">[${escapeHtml(e.group)}]</span>`:"");
    d.onclick = ()=>loadEntry(e.name);
    listEl.appendChild(d);
  });
}

function escapeHtml(s){ return String(s).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

async function loadList(){
  setStatus("加载列表…");
  const r = await fetch(`/api/list?kind=${encodeURIComponent(curKind)}`);
  const j = await r.json();
  entries = j.entries || [];
  renderList(searchEl.value);
  setStatus(`共 ${entries.length} 项`, "ok");
}

async function loadEntry(name){
  curName = name;
  renderList(searchEl.value);
  setStatus(`加载 ${name}…`);
  const r = await fetch(`/api/get?kind=${encodeURIComponent(curKind)}&name=${encodeURIComponent(name)}`);
  const j = await r.json();
  if(!r.ok){ setStatus(j.error||"加载失败","err"); return; }
  editorEl.value = JSON.stringify(j.record, null, 2);
  titleEl.textContent = `${curKind} · ${name}`;
  setStatus(`已加载 ${name}`, "ok");
}

async function save(){
  let rec;
  try { rec = JSON.parse(editorEl.value); }
  catch(e){ setStatus("JSON 解析失败："+e.message, "err"); return; }
  if(!rec || typeof rec!=="object" || Array.isArray(rec)){ setStatus("需为 JSON 对象","err"); return; }
  if(!rec["名称"]){ setStatus("缺少「名称」字段","err"); return; }
  setStatus("保存中…");
  const r = await fetch(`/api/save?kind=${encodeURIComponent(curKind)}`,{
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(rec)
  });
  const j = await r.json();
  if(!r.ok){ setStatus(j.error||"保存失败","err"); toast(j.error||"保存失败","err"); return; }
  curName = rec["名称"];
  entries = j.entries || [];
  renderList(searchEl.value);
  titleEl.textContent = `${curKind} · ${curName}`;
  setStatus(`已保存 ${curName}（旧文件已备份）`, "ok");
  toast(`✓ 已保存 ${curName}`);
}

async function del(){
  if(!curName){ setStatus("未选中条目","err"); return; }
  if(!confirm(`确认删除 ${curKind}【${curName}】？（删前已备份）`)) return;
  const r = await fetch(`/api/delete?kind=${encodeURIComponent(curKind)}&name=${encodeURIComponent(curName)}`,{method:"POST"});
  const j = await r.json();
  if(!r.ok){ setStatus(j.error||"删除失败","err"); return; }
  entries = j.entries || [];
  curName = null; editorEl.value=""; titleEl.textContent="—";
  renderList(searchEl.value);
  setStatus("已删除（已备份）","ok");
}

async function newEntry(){
  const r = await fetch(`/api/template?kind=${encodeURIComponent(curKind)}`);
  const j = await r.json();
  editorEl.value = JSON.stringify(j.record, null, 2);
  curName = null;
  renderList(searchEl.value);
  titleEl.textContent = `${curKind} · 新建`;
  setStatus("已载入模板，编辑「名称」等字段后保存", "ok");
  editorEl.focus();
}

function format(){
  try { editorEl.value = JSON.stringify(JSON.parse(editorEl.value), null, 2); setStatus("已格式化","ok"); }
  catch(e){ setStatus("JSON 解析失败："+e.message,"err"); }
}

searchEl.oninput = ()=>renderList(searchEl.value);
$("btnSave").onclick = save;
$("btnDelete").onclick = del;
$("btnNew").onclick = newEntry;
$("btnFormat").onclick = format;
$("btnReload").onclick = ()=>{ if(curName) loadEntry(curName); else setStatus("未选中条目","err"); };
editorEl.addEventListener("keydown", e=>{
  if((e.ctrlKey||e.metaKey) && e.key==="s"){ e.preventDefault(); save(); }
});

// 派生预览（右侧面板）
const derivePanel = $("derivePanel");
function kvTable(obj){
  if(!obj || typeof obj!=="object") return "<div class='empty'>（无）</div>";
  const rows = Object.entries(obj).map(([k,v])=>{
    const vs = (typeof v==="object") ? JSON.stringify(v) : String(v);
    return `<tr><td class="k">${escapeHtml(k)}</td><td class="v">${escapeHtml(vs)}</td></tr>`;
  }).join("");
  return `<table>${rows}</table>`;
}
async function derivePreview(){
  let rec;
  try { rec = JSON.parse(editorEl.value); }
  catch(e){ setStatus("JSON 解析失败："+e.message,"err"); return; }
  setStatus("派生中…");
  const r = await fetch(`/api/derive?kind=${encodeURIComponent(curKind)}`,{
    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(rec)
  });
  const j = await r.json();
  if(!r.ok){ setStatus(j.error||"派生失败","err"); return; }
  $("deriveName").textContent = rec["名称"] || "(未命名)";
  $("baseTable").innerHTML = kvTable(j["基础派生"]);
  const full = j["完整派生"];
  const fullRows = [
    ["气血上限", full["气血上限"]], ["内力上限", full["内力上限"]],
  ];
  let html = kvTable(Object.fromEntries(fullRows));
  html += "<h3>二级属性</h3>" + kvTable(full["二级属性"]);
  html += "<h3>武艺（含反哺与装备）</h3>" + kvTable(full["武艺(含反哺与装备)"]);
  html += "<h3>装备</h3>" + kvTable(full["装备"]);
  $("fullTable").innerHTML = html;
  derivePanel.classList.add("show");
  setStatus("派生完成","ok");
}
$("btnDerive").onclick = derivePreview;
$("btnDeriveClose").onclick = ()=>derivePanel.classList.remove("show");

renderTabs();
loadList();
</script>
</body>
</html>
"""


def main():
    port = 8765
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    os.makedirs(BACKUP_DIR, exist_ok=True)
    srv = HTTPServer(("0.0.0.0", port), Handler)
    print(f"数据管理台已启动：http://127.0.0.1:{port}/  （Ctrl+C 退出）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()

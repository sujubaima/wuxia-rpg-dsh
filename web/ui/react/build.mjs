// esbuild 构建 React 前端（替代 vite）：src/main.tsx → dist/。
// React/react-dom 打进 bundle（独立 web app，无运行时注入）。
// CSS 抽出到 dist/assets/index.css；index.html 注入脚本与样式引用。
import { build } from 'esbuild'
import { readFileSync, writeFileSync, mkdirSync, rmSync, renameSync, existsSync, readdirSync, copyFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = join(__dirname, 'src')
const DIST = join(__dirname, 'dist')
const ASSETS = join(DIST, 'assets')
const OUT_JS = 'assets/index.js'
const OUT_CSS = 'assets/index.css'

// 清空旧产物（vite 残留 + 上次构建），再重建
rmSync(DIST, { recursive: true, force: true })
mkdirSync(ASSETS, { recursive: true })

// 打包 JS（CSS 由 import 触发，esbuild 自动抽出到与入口同名的 main.css）
await build({
  entryPoints: [join(SRC, 'main.tsx')],
  bundle: true,
  format: 'esm',
  jsx: 'automatic',
  target: 'es2022',
  minify: true,
  sourcemap: false,
  outfile: join(ASSETS, 'index.js'),
})

// esbuild 把 game.css 抽出到 assets/main.css（与 JS 入口同名），重命名为 index.css
const autoCss = join(ASSETS, 'main.css')
if (existsSync(autoCss) && autoCss !== join(ASSETS, 'index.css')) {
  if (existsSync(join(ASSETS, 'index.css'))) {
    // 罕见同名，直接覆盖
  }
  renameSync(autoCss, join(ASSETS, 'index.css'))
}

// 处理 index.html：注入构建后的脚本与样式引用
const html = readFileSync(join(__dirname, 'index.html'), 'utf8')
const out = html
  .replace('<script type="module" src="/src/main.tsx"></script>',
    `<script type="module" src="/ui/react/${OUT_JS}"></script>`)
  .replace('  </head>', `    <link rel="stylesheet" href="/ui/react/${OUT_CSS}" />\n  </head>`)
writeFileSync(join(DIST, 'index.html'), out, 'utf8')

// 拷贝 public/ 静态资源（若有）
const pub = join(__dirname, 'public')
if (existsSync(pub)) {
  for (const name of readdirSync(pub)) {
    copyFileSync(join(pub, name), join(DIST, name))
  }
}

console.log('React 前端已构建:', DIST)

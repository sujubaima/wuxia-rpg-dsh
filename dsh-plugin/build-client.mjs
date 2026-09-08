// esbuild 把 src/client/index.tsx bundle 成 dsh 要的 client.js 格式：
// window.__ModuleLoader__.load({id, factory: (require) => { ...bundle... }})
// externals（react 等）经 dsh 注入的 require 解析，不打进 bundle。
import { build } from 'esbuild'
import { writeFileSync } from 'node:fs'

const PLUGIN_ID = 'wuxia-rpg-dsh'

// dsh client bundle 的 externals：平台模块 + 运行时 store 豁免
const EXTERNALS = [
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client',
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-web-react',
  '@deepseek-ai/dsh-client-ui-primitives',
  '@deepseek-ai/dsh-client-ui-attachment',
  '@deepseek-ai/dsh-client-schema-form',
  '@deepseek-ai/dsh-client-runtime/client',
  '@deepseek-ai/dsh-client-runtime',
  '@deepseek-ai/dsh-client-locale',
  '@deepseek-ai/dsh-client-ui-conversation',
]

await build({
  entryPoints: ['src/client/index.tsx'],
  bundle: true,
  format: 'cjs',
  jsx: 'automatic',
  external: EXTERNALS,
  target: 'es2022',
  minify: false,
  logLevel: 'info',
  write: false,
}).then((result) => {
  const code = result.outputFiles[0].text
  const wrapped = `// 武侠RPG dsh 插件 client 半（esbuild 生成）
window.__ModuleLoader__.load({
  id: ${JSON.stringify(PLUGIN_ID)},
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
${code}
    return module.exports;
  }
});
`
  writeFileSync('lib/client.js', wrapped, 'utf8')
  console.log('client.js 已生成:', 'lib/client.js')
})

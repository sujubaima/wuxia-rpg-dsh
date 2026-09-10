import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'

import { registerWuxiaCommands } from '../lib/host/commands.js'

function registerCommands(serviceUrl = 'http://127.0.0.1:1') {
  const registered = new Map()
  const ctx = {
    commands: {
      register(command) {
        registered.set(command.name, command)
      },
    },
  }
  registerWuxiaCommands(ctx, serviceUrl, 5000)
  return registered
}

function character(name = '沈听雪') {
  return {
    名称: name,
    性别: '女',
    年岁: 18,
    一级属性: { 内功: 6, 力道: 6, 身法: 6, 根骨: 6 },
    极性: { 内功: 50, 力道: 50, 身法: 50, 根骨: 50 },
  }
}

async function listen(handler) {
  const server = createServer(handler)
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  return {
    server,
    url: `http://127.0.0.1:${address.port}`,
  }
}

async function close(server) {
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
}

test('wuxia-create requires a positive slot', () => {
  const command = registerCommands().get('wuxia-create')
  assert.ok(command)
  let followed = false
  const result = command.handler({
    rawInput: JSON.stringify({ character: character() }),
    agent: { followup() { followed = true } },
  })
  assert.equal(result.kind, 'error')
  assert.match(result.text, /slot/)
  assert.equal(followed, false)
})

test('wuxia-create directive uses the supplied slot and structured conflict retry', () => {
  const command = registerCommands().get('wuxia-create')
  assert.ok(command)
  let followup
  const result = command.handler({
    rawInput: JSON.stringify({ slot: 12, character: character() }),
    agent: { followup(message) { followup = message } },
  })
  assert.equal(result.kind, 'success')
  const payload = JSON.stringify(followup)
  assert.match(payload, /顶层槽位首次必须传 12/)
  assert.match(payload, /错误码 slot_occupied/)
  assert.match(payload, /响应 next_slot/)
  assert.doesNotMatch(payload, /最多\s*3|三次/)
})

test('wuxia-delete returns refreshed next_slot with the title save list', async () => {
  const requests = []
  const { server, url } = await listen(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    requests.push({ url: req.url, body: JSON.parse(body) })
    res.setHeader('Content-Type', 'application/json')
    if (requests.length === 1) {
      res.end(JSON.stringify({ 结算: [{ ok: true, msg: '已删除' }] }))
    } else {
      res.end(JSON.stringify({ next_slot: 4, 存档列表: [{ slot: 2, 角色名: '旧档' }] }))
    }
  })

  try {
    const command = registerCommands(url).get('wuxia-delete')
    assert.ok(command)
    const result = await command.handler({ rawInput: JSON.stringify({ slot: 3 }) })
    assert.equal(result.kind, 'success')
    assert.deepEqual(JSON.parse(result.text), {
      slot: 3,
      next_slot: 4,
      存档列表: [{ slot: 2, 角色名: '旧档' }],
    })
    assert.deepEqual(requests, [
      {
        url: '/api/v1/operations/go',
        body: { 槽位: 3, 行为: [{ 类型: '删除存档' }] },
      },
      {
        url: '/api/v1/operations/go',
        body: { 槽位: 0, 行为: [{ 类型: '开始游戏' }] },
      },
    ])
  } finally {
    await close(server)
  }
})

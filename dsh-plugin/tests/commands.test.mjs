import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'

import { registerWuxiaCommands } from '../lib/host/commands.js'
import { registerWuxiaPanelCommand } from '../lib/host/panel-command.js'

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

function registerPanelCommand(serviceUrl) {
  const registered = new Map()
  registerWuxiaPanelCommand({
    commands: { register(command) { registered.set(command.name, command) } },
  }, serviceUrl, 5000)
  return registered.get('wuxia-panel')
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
  assert.match(payload, /wuxia_plot_writing/)
  assert.match(payload, /仅以新建slot调用 wuxia_judge/)
  assert.doesNotMatch(payload, /最多\s*3|三次/)
})

test('wuxia-panel defers ordinary no-UI go until plot-writing and judge', async () => {
  const requests = []
  const { server, url } = await listen(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    requests.push({ url: req.url, body: JSON.parse(body) })
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ turn_state: 'AWAITING_PLOT', 结算: [{ ok: true }], 金钱: 12, 当前时间: '午时' }))
  })

  try {
    const command = registerPanelCommand(url)
    let followup
    const action = { 类型: '购买', 物品: '烧饼', 数量: 1, 卖家: '小贩' }
    const response = await command.handler({
      rawInput: JSON.stringify({ slot: 3, actions: [action] }),
      agent: { followup(message) { followup = message } },
    })
    assert.equal(response.kind, 'success')
    const parsed = JSON.parse(response.text)
    assert.equal(parsed.followup, true)
    assert.equal(parsed.state, undefined, 'provisional go state must not update the party UI')
    assert.equal(parsed.view, undefined)
    assert.deepEqual(requests, [{
      url: '/api/v1/operations/go',
      body: { 槽位: 3, 行为: [action] },
    }])
    const directive = JSON.stringify(followup)
    assert.match(directive, /尚未落盘/)
    assert.match(directive, /wuxia_plot_writing/)
    assert.match(directive, /wuxia_scene_prepare \/ wuxia_quest_prepare/)
    assert.match(directive, /仅以槽位 3 调用 wuxia_judge/)
    assert.doesNotMatch(directive, /完成机制结算并落盘/)
  } finally {
    await close(server)
  }
})

test('wuxia-panel follows staged no-UI item use without replaying go', async () => {
  const requests = []
  const { server, url } = await listen(async (req, res) => {
    requests.push(req.url)
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ turn_state: 'AWAITING_PLOT', 结算: [{ ok: true }], 体力: 15 }))
  })
  try {
    const command = registerPanelCommand(url)
    let followup
    const response = await command.handler({
      rawInput: JSON.stringify({ slot: 3, actions: [{ 类型: '使用物品', 物品: '药丸' }] }),
      agent: { followup(message) { followup = message } },
    })
    assert.equal(response.kind, 'success')
    assert.equal(JSON.parse(response.text).followup, true)
    assert.equal(JSON.parse(response.text).state, undefined)
    assert.ok(followup)
    assert.deepEqual(requests, ['/api/v1/operations/go'])
  } finally {
    await close(server)
  }
})

test('wuxia-panel rejects trailing actions after a mutation before calling go', async () => {
  const command = registerPanelCommand('http://127.0.0.1:1')
  const response = await command.handler({
    rawInput: JSON.stringify({ slot: 3, actions: [
      { 类型: '休息', 等级: '客栈', 时长: 32 }, { 类型: '查看背包' },
    ] }),
  })
  assert.equal(response.kind, 'error')
  assert.match(response.text, /最后一个行为/)
})

test('wuxia-panel does not replay go on engine errors', async () => {
  const requests = []
  const { server, url } = await listen(async (req, res) => {
    requests.push(req.url)
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ 错误: '操作未完成', turn_state: 'READY' }))
  })
  try {
    const command = registerPanelCommand(url)
    const response = await command.handler({
      rawInput: JSON.stringify({ slot: 3, actions: [{ 类型: '使用物品', 物品: '药丸' }] }),
      agent: { followup() { throw new Error('unexpected followup') } },
    })
    assert.equal(response.kind, 'success')
    assert.deepEqual(requests, ['/api/v1/operations/go'])
  } finally {
    await close(server)
  }
})

test('wuxia-title fetches the title save list without the LLM', async () => {
  const requests = []
  const { server, url } = await listen(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    requests.push({ url: req.url, body: JSON.parse(body) })
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({
      界面: 'title-ui',
      存档列表: [{ slot: 2, 角色名: '旧档' }],
      next_slot: 4,
      版本: '0.9.11',
    }))
  })

  try {
    const command = registerCommands(url).get('wuxia-title')
    assert.ok(command)
    const result = await command.handler({})
    assert.equal(result.kind, 'success')
    assert.deepEqual(JSON.parse(result.text), {
      存档列表: [{ slot: 2, 角色名: '旧档' }],
      next_slot: 4,
      版本: '0.9.11',
    })
    assert.deepEqual(requests, [
      {
        url: '/api/v1/operations/go',
        body: { 槽位: 0, 行为: [{ 类型: '开始游戏' }] },
      },
    ])
  } finally {
    await close(server)
  }
})

test('wuxia-title surfaces engine errors', async () => {
  const { server, url } = await listen(async (req, res) => {
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ 错误: '存档根目录不可用' }))
  })

  try {
    const command = registerCommands(url).get('wuxia-title')
    assert.ok(command)
    const result = await command.handler({})
    assert.equal(result.kind, 'error')
    assert.match(result.text, /存档根目录不可用/)
  } finally {
    await close(server)
  }
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

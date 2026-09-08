import { spawn, type ChildProcess } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import type { Config } from '../config.js'

const READY_PREFIX = '[engine-service-ready] '
const STARTUP_TIMEOUT_MS = 10000

export interface EnginePaths {
  pluginDir: string
  scriptPath: string
  skillDir: string
}

export function resolveEnginePaths(config: Config, moduleUrl = import.meta.url): EnginePaths {
  const pluginDir = resolve(fileURLToPath(new URL('../../', moduleUrl)))
  const skillDir = config.skillDir || resolve(pluginDir, '..', 'wuxia-rpg')
  return {
    pluginDir,
    scriptPath: config.engineServicePath || resolve(skillDir, 'scripts', 'engine_service.py'),
    skillDir,
  }
}

function normalizedUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

async function readHealth(url: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(1000) })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const payload = await response.json()
  if (!payload || typeof payload !== 'object') throw new Error('响应不是 JSON 对象')
  return payload as Record<string, unknown>
}

async function waitForSpawnedService(url: string, instanceId: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastError = '服务尚未响应'
  while (Date.now() < deadline) {
    try {
      const health = await readHealth(url)
      if (health.ok !== true) throw new Error('health.ok 不是 true')
      if (health.engine !== true) throw new Error('engine 未就绪')
      if (health.service !== 'wuxia-rpg-engine') throw new Error('服务标识不匹配')
      if (typeof health.protocol_version !== 'string' || !health.protocol_version) throw new Error('协议版本缺失')
      if (health.instance_id !== instanceId) throw new Error('实例标识不匹配')
      return
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await new Promise(resolvePromise => setTimeout(resolvePromise, 100))
  }
  throw new Error(`健康检查超时：${lastError}`)
}

function stopProcess(proc: ChildProcess): void {
  if (!proc.killed && proc.exitCode === null) proc.kill()
}

export async function startEngineService(ctx: Context, config: Config): Promise<string> {
  const configuredUrl = normalizedUrl(config.serviceUrl ?? '')
  if (configuredUrl) return configuredUrl
  if (config.autoStart === false) {
    throw new Error('wuxia-rpg: autoStart=false 时必须配置 serviceUrl')
  }

  const { scriptPath, skillDir } = resolveEnginePaths(config)
  if (!existsSync(scriptPath)) throw new Error(`wuxia-rpg: engine service 不存在：${scriptPath}`)
  if (!existsSync(skillDir)) throw new Error(`wuxia-rpg: Skill 目录不存在：${skillDir}`)

  const instanceId = randomUUID()
  const pythonCommand = config.pythonCommand || process.env.WUXIA_RPG_PYTHON || 'python3'
  const port = String(config.enginePort ?? 0)
  const renderModule = config.renderModule ?? 'dsh'
  ctx.logger.info(`wuxia-rpg: 启动 engine service ${scriptPath} port=${port}`)

  const engineProc = spawn(pythonCommand, [scriptPath], {
    env: {
      ...process.env,
      HOST: '127.0.0.1',
      PORT: port,
      WUXIA_RPG_ENGINE_INSTANCE_ID: instanceId,
      WUXIA_RPG_RENDER_MODULE: renderModule,
      WUXIA_RPG_SKILL_DIR: skillDir,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  ctx.effect(() => () => {
    stopProcess(engineProc)
    ctx.logger.info('wuxia-rpg: engine service 已停止')
  }, 'wuxia-rpg: engine service')

  let stderrTail = ''
  engineProc.stderr?.on('data', (data) => {
    const text = data.toString().trim()
    if (!text) return
    stderrTail = `${stderrTail}\n${text}`.slice(-4000)
    ctx.logger.warn(`[engine-service] ${text}`)
  })

  try {
    const ready = await new Promise<{ port: number }>((resolveReady, rejectReady) => {
      let settled = false
      let stdoutBuffer = ''
      const finish = (error?: Error, value?: { port: number }) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        if (error) rejectReady(error)
        else resolveReady(value!)
      }
      const timer = setTimeout(() => {
        finish(new Error(`wuxia-rpg: engine service 启动超时${stderrTail ? `：${stderrTail.trim()}` : ''}`))
      }, STARTUP_TIMEOUT_MS)

      engineProc.on('error', (error) => finish(new Error(`wuxia-rpg: 无法启动 ${pythonCommand}：${error.message}`)))
      engineProc.on('exit', (code, signal) => {
        finish(new Error(
          `wuxia-rpg: engine service 在就绪前退出 code=${String(code)} signal=${String(signal)}`
          + (stderrTail ? `：${stderrTail.trim()}` : ''),
        ))
      })
      engineProc.stdout?.on('data', (data) => {
        stdoutBuffer += data.toString()
        let newline = stdoutBuffer.indexOf('\n')
        while (newline !== -1) {
          const line = stdoutBuffer.slice(0, newline).trim()
          stdoutBuffer = stdoutBuffer.slice(newline + 1)
          if (line.startsWith(READY_PREFIX)) {
            try {
              const payload = JSON.parse(line.slice(READY_PREFIX.length)) as Record<string, unknown>
              if (payload.instance_id !== instanceId) throw new Error('实例标识不匹配')
              if (payload.service !== 'wuxia-rpg-engine') throw new Error('服务标识不匹配')
              if (payload.engine !== true) throw new Error('engine 导入失败')
              if (typeof payload.protocol_version !== 'string' || !payload.protocol_version) throw new Error('协议版本缺失')
              if (typeof payload.port !== 'number' || !Number.isInteger(payload.port) || payload.port <= 0) {
                throw new Error('端口无效')
              }
              finish(undefined, { port: payload.port })
            } catch (error) {
              finish(new Error(`wuxia-rpg: engine ready 事件无效：${error instanceof Error ? error.message : String(error)}`))
            }
          } else if (line) {
            ctx.logger.info(`[engine-service] ${line}`)
          }
          newline = stdoutBuffer.indexOf('\n')
        }
      })
    })

    const serviceUrl = `http://127.0.0.1:${ready.port}`
    await waitForSpawnedService(serviceUrl, instanceId, STARTUP_TIMEOUT_MS)
    ctx.logger.info(`wuxia-rpg: engine service 就绪 ${serviceUrl}`)
    return serviceUrl
  } catch (error) {
    stopProcess(engineProc)
    throw error
  }
}

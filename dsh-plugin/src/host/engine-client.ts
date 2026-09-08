import type { JsonValue } from '@deepseek-ai/dsh-tools'
import { parseToolsManifest, type WuxiaToolsManifest } from './tool-schema.js'

async function requestJson(
  serviceUrl: string,
  timeoutMs: number,
  path: string,
  payload?: Record<string, unknown>,
): Promise<{ ok: boolean; status: number; body: Record<string, unknown> }> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const resp = await fetch(`${serviceUrl}${path}`, {
      method: payload === undefined ? 'GET' : 'POST',
      headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      signal: ctrl.signal,
    })
    const text = await resp.text()
    try {
      const body = JSON.parse(text) as unknown
      if (!body || typeof body !== 'object' || Array.isArray(body)) {
        return { ok: false, status: resp.status, body: { error: '输出不是 JSON 对象' } }
      }
      return { ok: resp.ok, status: resp.status, body: body as Record<string, unknown> }
    } catch {
      return { ok: false, status: resp.status, body: { error: `输出非 JSON: ${text.slice(0, 200)}` } }
    }
  } finally {
    clearTimeout(timer)
  }
}

export async function fetchToolsManifest(
  serviceUrl: string,
  timeoutMs: number,
): Promise<WuxiaToolsManifest> {
  let response
  try {
    response = await requestJson(serviceUrl, timeoutMs, '/api/tools')
  } catch (error) {
    throw new Error(`读取 Tools Schema 失败: ${error instanceof Error ? error.message : String(error)}`)
  }
  if (!response.ok) {
    throw new Error(`读取 Tools Schema 失败: ${String(response.body.error ?? `HTTP ${response.status}`)}`)
  }
  return parseToolsManifest(response.body)
}

export async function callOperation(
  serviceUrl: string,
  timeoutMs: number,
  operation: string,
  payload: Record<string, unknown>,
): Promise<Record<string, JsonValue>> {
  try {
    const path = `/api/v1/operations/${encodeURIComponent(operation)}`
    const response = await requestJson(serviceUrl, timeoutMs, path, payload)
    const body = response.body
    if (body.error !== undefined && body.错误 === undefined) body.错误 = body.error
    if (!response.ok && body.错误 === undefined) body.错误 = `engine service HTTP ${response.status}`
    return body as Record<string, JsonValue>
  } catch (error) {
    return { 错误: `engine 调用失败: ${error instanceof Error ? error.message : String(error)}` }
  }
}

export async function callEngine(
  serviceUrl: string,
  timeoutMs: number,
  payload: Record<string, unknown>,
  method: 'go' | 'judge',
): Promise<Record<string, JsonValue>> {
  return callOperation(serviceUrl, timeoutMs, method, payload)
}

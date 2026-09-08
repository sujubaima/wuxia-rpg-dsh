import z from '@deepseek-ai/schemastery'

export interface Config {
  serviceUrl?: string
  enginePort?: number
  engineServicePath?: string
  skillDir?: string
  pythonCommand?: string
  renderModule?: string
  timeoutMs?: number
  autoStart?: boolean
}

export const Config: z<Config> = z.object({
  serviceUrl: z.string().default(''),
  enginePort: z.number().default(0),
  engineServicePath: z.string().default(''),
  skillDir: z.string().default(''),
  pythonCommand: z.string().default(''),
  renderModule: z.string().default('dsh'),
  timeoutMs: z.number().default(120000),
  autoStart: z.boolean().default(true),
})

export const DEFAULT_TIMEOUT = 120000

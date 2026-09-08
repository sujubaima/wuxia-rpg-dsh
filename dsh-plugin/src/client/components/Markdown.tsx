import { render } from '../lib/markdown'

export function Markdown({ text, className }: { text: string; className?: string }) {
  return <div className={className} dangerouslySetInnerHTML={{ __html: render(text) }} />
}

export type Stage =
  | 'queued'
  | 'outlining'
  | 'outline_review'
  | 'trial_queued'
  | 'trial_writing'
  | 'trial_review'
  | 'full_queued'
  | 'full_writing'
  | 'done'
  | 'failed'
  | 'trashed'

export interface Settings {
  max_total: number
  max_outline_backlog: number
  max_trial_backlog: number
  outline_review: boolean
  trial_review: boolean
  trial_chapters: number
  concurrency: number
  drafts: number
  trash_days: number
  dry_run: boolean
}

export interface Status {
  running: boolean
  dry_run: boolean
  counts: Record<Stage, number>
  active: number
  outline_backlog: number
  trial_backlog: number
  busy: number[]
  settings: Settings
  model_key: { env: string; set: boolean }
}

export interface Topic {
  id?: number
  name: string
  genre: string
  core: string
  ideas: string
  count: number
  chapters: number
  enabled: boolean
  produced?: number
}

export interface Book {
  id: number
  topic_id: number | null
  slug: string
  genre: string
  idea: string
  chapters: number
  title: string
  stage: Stage
  prev_stage: string
  written: number
  error: string
  note: string
  created_at: string
  updated_at: string
  trashed_at: string | null
  busy?: boolean
}

export interface Chapter {
  scene_id: string
  title: string
  text: string
  chars: number
}

export interface EventItem {
  id: number
  book_id: number | null
  at: string
  level: string
  message: string
}

export interface BookDetail extends Book {
  canon: Record<string, any> | null
  cards: Record<string, any>[]
  texts: Chapter[]
  events: EventItem[]
}

export interface Genre {
  id: string
  name: string
  default: boolean
}

export type Action = 'approve' | 'reject' | 'trash' | 'restore' | 'retry' | 'delete' | 'redo'

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const data = await response.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* keep statusText */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export const api = {
  status: () => call<Status>('GET', '/api/status'),
  control: (action: 'start' | 'pause') => call<{ running: boolean }>('POST', `/api/control/${action}`),
  genres: () => call<Genre[]>('GET', '/api/genres'),
  settings: () => call<Settings>('GET', '/api/settings'),
  saveSettings: (data: Partial<Settings>) => call<Settings>('PUT', '/api/settings', data),
  topics: () => call<Topic[]>('GET', '/api/topics'),
  saveTopic: (topic: Topic) =>
    topic.id
      ? call<Topic>('PUT', `/api/topics/${topic.id}`, topic)
      : call<Topic>('POST', '/api/topics', topic),
  deleteTopic: (id: number) => call<{ ok: boolean }>('DELETE', `/api/topics/${id}`),
  books: (stages: Stage[] = []) =>
    call<Book[]>('GET', `/api/books?stage=${encodeURIComponent(stages.join(','))}`),
  book: (id: number) => call<BookDetail>('GET', `/api/books/${id}`),
  act: (id: number, action: Action, note = '') =>
    call<Book>('POST', `/api/books/${id}/${action}`, { note }),
  batch: (ids: number[], action: Action, note = '') =>
    call<{ done: number[]; errors: Record<string, string> }>('POST', '/api/batch', {
      ids,
      action,
      note,
    }),
  emptyTrash: () => call<{ removed: number }>('POST', '/api/trash/empty'),
  events: (limit = 50) => call<EventItem[]>('GET', `/api/events?limit=${limit}`),
  manuscriptUrl: (id: number) => `/api/books/${id}/manuscript`,
}

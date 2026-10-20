import { reactive } from 'vue'
import { api, type Genre, type Status } from './api'

export const store = reactive<{
  status: Status | null
  genres: Genre[]
  error: string
  revision: number
}>({
  status: null,
  genres: [],
  error: '',
  revision: 0,
})

export async function refreshStatus(): Promise<void> {
  try {
    store.status = await api.status()
    store.error = ''
    store.revision += 1
  } catch (error) {
    store.error = (error as Error).message || '连不上后端'
  }
}

export async function loadGenres(): Promise<void> {
  store.genres = await api.genres()
}

export function genreName(id: string): string {
  return store.genres.find((genre) => genre.id === id)?.name ?? id
}

let timer: number | undefined

export function startPolling(ms = 3000): void {
  if (timer !== undefined) return
  void refreshStatus()
  timer = window.setInterval(() => void refreshStatus(), ms)
}

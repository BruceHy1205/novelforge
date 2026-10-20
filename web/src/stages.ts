import type { Stage } from './api'

type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export const STAGE_LABEL: Record<Stage, string> = {
  queued: '待写大纲',
  outlining: '大纲生成中',
  outline_review: '大纲待审',
  trial_queued: '待写试读',
  trial_writing: '试读生成中',
  trial_review: '试读待审',
  full_queued: '待续写全书',
  full_writing: '全书续写中',
  done: '已完成',
  failed: '失败',
  trashed: '回收站',
}

export const STAGE_TAG: Record<Stage, TagType> = {
  queued: 'info',
  outlining: 'primary',
  outline_review: 'warning',
  trial_queued: 'info',
  trial_writing: 'primary',
  trial_review: 'warning',
  full_queued: 'info',
  full_writing: 'primary',
  done: 'success',
  failed: 'danger',
  trashed: 'info',
}

export const PIPELINE: { title: string; stages: Stage[] }[] = [
  { title: '大纲', stages: ['queued', 'outlining', 'outline_review'] },
  { title: '试读', stages: ['trial_queued', 'trial_writing', 'trial_review'] },
  { title: '全书', stages: ['full_queued', 'full_writing', 'done'] },
  { title: '异常', stages: ['failed', 'trashed'] },
]

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage as Stage] ?? stage
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

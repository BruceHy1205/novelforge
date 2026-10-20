<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { api, type Action, type BookDetail } from '../api'
import { STAGE_TAG, formatTime, stageLabel } from '../stages'
import { genreName } from '../store'

const props = defineProps<{ bookId: number | null; queueLabel?: string }>()
const emit = defineEmits<{ close: []; changed: []; reviewed: [] }>()

const book = ref<BookDetail | null>(null)
const loading = ref(false)
const loadError = ref('')
const tab = ref('outline')
const chapterIndex = ref(0)

const visible = computed({
  get: () => props.bookId !== null,
  set: (value: boolean) => {
    if (!value) emit('close')
  },
})

const canon = computed(() => book.value?.canon ?? null)
const story = computed(() => canon.value?.story ?? {})
const chapter = computed(() => book.value?.texts[chapterIndex.value] ?? null)
const inReview = computed(
  () => book.value?.stage === 'outline_review' || book.value?.stage === 'trial_review',
)

async function load(): Promise<void> {
  if (props.bookId === null) return
  loading.value = true
  loadError.value = ''
  try {
    book.value = await api.book(props.bookId)
  } catch (error) {
    loadError.value = (error as Error).message
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.bookId,
  async (id) => {
    book.value = null
    loadError.value = ''
    chapterIndex.value = 0
    if (id === null) return
    await load()
    const stage = (book.value as BookDetail | null)?.stage
    tab.value = stage === 'trial_review' || stage === 'done' ? 'chapters' : 'outline'
  },
  { immediate: true },
)

const LABELS: Record<Action, string> = {
  approve: '审核通过',
  reject: '毙掉',
  trash: '移入回收站',
  restore: '恢复',
  retry: '重试',
  redo: '退回重做',
  delete: '永久删除',
}

async function act(action: Action): Promise<void> {
  if (!book.value) return
  let note = ''
  if (action === 'reject' || action === 'trash') {
    try {
      const result = await ElMessageBox.prompt('写一句原因（可不填），书会进回收站，到期自动删除。', LABELS[action], {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputPlaceholder: '比如：开局太慢',
      })
      note = result.value ?? ''
    } catch {
      return
    }
  } else if (action === 'redo' || action === 'delete') {
    const message =
      action === 'delete'
        ? '永久删除后无法恢复，确定？'
        : book.value.stage === 'outline_review'
          ? '丢掉这份大纲，按同一个创意重新生成？'
          : '丢掉已写的试读章节，按现有大纲重写？'
    try {
      await ElMessageBox.confirm(message, LABELS[action], { type: 'warning' })
    } catch {
      return
    }
  }
  try {
    const title = book.value.title || book.value.slug
    await api.act(book.value.id, action, note)
    ElMessage.success(`${LABELS[action]}：${title}`)
    emit('changed')
    const leavesReview = action === 'approve' || action === 'reject' || action === 'redo'
    if (leavesReview && props.queueLabel) {
      emit('reviewed')
    } else if (action === 'delete') {
      emit('close')
    } else {
      await load()
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}
</script>

<template>
  <el-drawer v-model="visible" size="62%" :with-header="false" destroy-on-close>
    <div v-loading="loading" class="detail">
      <template v-if="book">
        <div class="head">
          <div>
            <h3>{{ book.title || book.slug }}</h3>
            <div class="toolbar">
              <el-tag :type="STAGE_TAG[book.stage]">{{ stageLabel(book.stage) }}</el-tag>
              <el-tag type="info">{{ genreName(book.genre) }}</el-tag>
              <span class="muted">{{ book.slug }} · 已写 {{ book.written }} / {{ book.chapters }} 章</span>
              <el-tag v-if="queueLabel" type="warning" effect="plain" round>连续审核</el-tag>
            </div>
          </div>
          <div class="toolbar">
            <template v-if="inReview">
              <el-button type="success" @click="act('approve')">审核通过</el-button>
              <el-button @click="act('redo')">退回重做</el-button>
              <el-button type="danger" plain @click="act('reject')">毙掉</el-button>
            </template>
            <el-button v-else-if="book.stage === 'failed'" type="primary" @click="act('retry')">重试</el-button>
            <template v-if="book.stage === 'trashed'">
              <el-button type="primary" @click="act('restore')">恢复</el-button>
              <el-button type="danger" @click="act('delete')">永久删除</el-button>
            </template>
            <el-button v-else-if="!inReview" type="danger" plain @click="act('trash')">移入回收站</el-button>
            <el-button v-if="book.written" tag="a" :href="api.manuscriptUrl(book.id)">
              下载正文
            </el-button>
          </div>
        </div>

        <el-alert v-if="queueLabel" type="warning" :title="queueLabel" :closable="false" class="gap" />
        <el-alert v-if="book.error" type="error" :title="book.error" :closable="false" show-icon class="gap" />
        <el-alert
          v-if="book.stage === 'trashed' && book.trashed_at"
          type="info"
          :closable="false"
          :title="`${formatTime(book.trashed_at)} 进入回收站${book.note ? '：' + book.note : ''}`"
          class="gap"
        />

        <el-tabs v-model="tab">
          <el-tab-pane label="大纲" name="outline">
            <el-empty v-if="!canon" description="大纲还没生成" />
            <template v-else>
              <section v-if="story.background || story.concept" class="background">
                <template v-if="story.background">
                  <h4>故事背景</h4>
                  <p>{{ story.background }}</p>
                </template>
                <template v-if="story.concept">
                  <h4>核心设定</h4>
                  <p>{{ story.concept }}</p>
                </template>
              </section>
              <el-descriptions :column="1" border size="small" class="gap">
                <el-descriptions-item label="创意">{{ book.idea }}</el-descriptions-item>
                <el-descriptions-item label="前提">{{ canon.premise }}</el-descriptions-item>
                <el-descriptions-item label="钩子">{{ story.hook }}</el-descriptions-item>
                <el-descriptions-item v-if="story.selling_point" label="卖点">{{ story.selling_point }}</el-descriptions-item>
                <el-descriptions-item v-if="story.core" label="核心体验">{{ story.core }}</el-descriptions-item>
                <el-descriptions-item v-if="story.tone" label="基调">{{ story.tone }}</el-descriptions-item>
              </el-descriptions>

              <h4>人物</h4>
              <el-table :data="story.characters ?? []" size="small" border class="gap">
                <el-table-column prop="name" label="名字" width="100" />
                <el-table-column prop="role" label="角色" width="110" />
                <el-table-column prop="public_face" label="表面身份" />
                <el-table-column prop="want" label="想要" />
                <el-table-column prop="edge" label="本事 / 金手指" />
              </el-table>

              <template v-if="(canon.secrets ?? []).length">
                <h4>秘密 <span class="muted">（作者设定，写手和读者模拟器都看不到）</span></h4>
                <el-table :data="canon.secrets" size="small" border class="gap">
                  <el-table-column prop="id" label="ID" width="70" />
                  <el-table-column prop="title" label="名目" width="140" />
                  <el-table-column prop="text" label="真相" />
                  <el-table-column prop="probe_question" label="读者问题" width="180" />
                </el-table>
              </template>

              <h4>章节卡（{{ book.cards.length }}）</h4>
              <el-collapse>
                <el-collapse-item v-for="card in book.cards" :key="card.scene_id" :name="card.scene_id">
                  <template #title>
                    <b>{{ card.scene_id }}</b>&nbsp;{{ card.title }}
                    <span class="muted">&nbsp;· {{ card.pace }} · {{ card.length }} 字</span>
                  </template>
                  <el-descriptions :column="1" size="small" border>
                    <el-descriptions-item label="目的">{{ card.beat_purpose }}</el-descriptions-item>
                    <el-descriptions-item v-if="list(card.beats).length" label="节拍">
                      <div v-for="line in list(card.beats)" :key="line">· {{ line }}</div>
                    </el-descriptions-item>
                    <el-descriptions-item v-if="card.reader_want" label="读者想要">{{ card.reader_want }}</el-descriptions-item>
                    <el-descriptions-item v-if="card.obstacle" label="阻碍">{{ card.obstacle }}</el-descriptions-item>
                    <el-descriptions-item v-if="card.payoff" label="回报">{{ card.payoff }}</el-descriptions-item>
                    <el-descriptions-item v-for="(lines, name) in card.genre_beats ?? {}" :key="name" :label="String(name)">
                      <div v-for="line in list(lines)" :key="line">· {{ line }}</div>
                    </el-descriptions-item>
                    <el-descriptions-item v-if="card.ending_hook" label="结尾钩子">{{ card.ending_hook }}</el-descriptions-item>
                  </el-descriptions>
                </el-collapse-item>
              </el-collapse>
            </template>
          </el-tab-pane>

          <el-tab-pane :label="`正文（${book.texts.length}）`" name="chapters">
            <el-empty v-if="!book.texts.length" description="还没有写好的章节" />
            <div v-else class="reader">
              <el-menu :default-active="String(chapterIndex)" class="chapters" @select="(i: string) => (chapterIndex = Number(i))">
                <el-menu-item v-for="(item, index) in book.texts" :key="item.scene_id" :index="String(index)">
                  {{ item.scene_id }} {{ item.title }}
                </el-menu-item>
              </el-menu>
              <div v-if="chapter" class="page">
                <h3>{{ chapter.scene_id }} {{ chapter.title }}</h3>
                <div class="muted gap">{{ chapter.chars }} 字</div>
                <div class="chapter-text">{{ chapter.text }}</div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="日志" name="events">
            <el-timeline>
              <el-timeline-item
                v-for="event in book.events"
                :key="event.id"
                :timestamp="formatTime(event.at)"
                :type="event.level === 'error' ? 'danger' : 'primary'"
              >
                {{ event.message }}
              </el-timeline-item>
            </el-timeline>
          </el-tab-pane>
        </el-tabs>
      </template>
      <p v-else-if="loadError" class="muted">{{ loadError }}</p>
    </div>
  </el-drawer>
</template>

<style scoped>
.detail {
  min-height: 300px;
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.head h3 {
  margin: 0 0 8px;
}
.gap {
  margin-bottom: 12px;
}
.background {
  margin-bottom: 16px;
  padding: 16px 18px 8px;
  border-radius: 16px;
  background: #fffdf8;
  box-shadow: 0 10px 24px rgba(48, 32, 16, 0.05);
}
.background h4 {
  margin: 0 0 8px;
  font-family: Fraunces, 'Songti SC', Palatino, serif;
}
.background p {
  margin: 0 0 10px;
  line-height: 1.85;
  white-space: pre-wrap;
}
.reader {
  display: flex;
  gap: 16px;
}
.chapters {
  width: 200px;
  flex-shrink: 0;
  max-height: 70vh;
  overflow: auto;
}
.page {
  flex: 1;
  max-height: 70vh;
  overflow: auto;
  padding-right: 8px;
}
</style>

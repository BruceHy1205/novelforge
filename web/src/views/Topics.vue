<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { api, type Topic } from '../api'
import { genreName, refreshStatus, store } from '../store'

const topics = ref<Topic[]>([])
const editing = ref(false)
const saving = ref(false)
const form = reactive<Topic>(blank())

function blank(): Topic {
  return {
    name: '',
    genre: store.genres.find((genre) => genre.default)?.id ?? 'mystery',
    core: '',
    ideas: '',
    count: 10,
    chapters: 20,
    enabled: true,
  }
}

async function load(): Promise<void> {
  topics.value = await api.topics()
}

onMounted(load)

function open(topic?: Topic): void {
  Object.assign(form, blank(), topic ?? {})
  if (!topic) delete form.id
  editing.value = true
}

async function save(): Promise<void> {
  if (!form.name.trim()) {
    ElMessage.warning('题材名称不能为空')
    return
  }
  if (!form.core.trim() && !form.ideas.trim()) {
    ElMessage.warning('核心内容和具体创意至少写一样')
    return
  }
  saving.value = true
  try {
    const { produced: _produced, ...payload } = form
    await api.saveTopic(payload)
    editing.value = false
    ElMessage.success('已保存')
    await load()
    await refreshStatus()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

async function toggle(topic: Topic, enabled: boolean): Promise<void> {
  await api.saveTopic({ ...topic, enabled })
  await load()
}

async function remove(topic: Topic): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除题材「${topic.name}」？已经生产的书不受影响。`, '删除题材', {
      type: 'warning',
    })
  } catch {
    return
  }
  await api.deleteTopic(topic.id!)
  await load()
}

function ideaCount(topic: Topic): number {
  return topic.ideas.split('\n').filter((line) => line.trim()).length
}
</script>

<template>
  <div>
    <div class="page-title">
      <h2>题材批次</h2>
      <el-button type="primary" @click="open()">新建题材</el-button>
    </div>
    <p class="muted">
      每个题材是一批书：同一套题材规则和核心内容，按本数补进生产队列。多个题材同时启用时轮流补书，
      总数不超过设置里的「总体待生产上限」。被毙掉的书不占本数，会自动补一本新的。
    </p>

    <el-table :data="topics" border>
      <el-table-column prop="name" label="题材" min-width="140" />
      <el-table-column label="规则集" width="100">
        <template #default="{ row }">{{ genreName(row.genre) }}</template>
      </el-table-column>
      <el-table-column label="核心内容" min-width="260">
        <template #default="{ row }">
          <div class="clip">{{ row.core }}</div>
          <div v-if="ideaCount(row)" class="muted">另有 {{ ideaCount(row) }} 条具体创意</div>
        </template>
      </el-table-column>
      <el-table-column label="已生产 / 本数" width="150">
        <template #default="{ row }">
          <template v-if="row.count">
            <el-progress :percentage="Math.min(100, Math.round(((row.produced ?? 0) / row.count) * 100))" :format="() => `${row.produced ?? 0}/${row.count}`" />
          </template>
          <span v-else>{{ row.produced ?? 0 }} / 不限</span>
        </template>
      </el-table-column>
      <el-table-column prop="chapters" label="每本章数" width="90" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="(v: string | number | boolean) => toggle(row, Boolean(v))" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button link type="primary" @click="open(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有题材，先新建一个" />
      </template>
    </el-table>

    <el-dialog v-model="editing" :title="form.id ? '编辑题材' : '新建题材'" width="680px">
      <el-form label-width="96px">
        <el-form-item label="题材名称" required>
          <el-input v-model="form.name" placeholder="比如：民国渡口悬疑" maxlength="40" />
        </el-form-item>
        <el-form-item label="规则集">
          <el-radio-group v-model="form.genre">
            <el-radio-button v-for="genre in store.genres" :key="genre.id" :value="genre.id">
              {{ genre.name }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="核心内容">
          <el-input
            v-model="form.core"
            type="textarea"
            :rows="5"
            placeholder="每本都会带上的部分：卖点、主线、主角设定、想要的读感、禁忌……"
          />
        </el-form-item>
        <el-form-item label="具体创意">
          <el-input
            v-model="form.ideas"
            type="textarea"
            :rows="5"
            placeholder="可选。每行一个创意，按顺序轮流分给这一批的书。留空时每本只用核心内容，并要求换一套人物和开局。"
          />
        </el-form-item>
        <el-form-item label="本数">
          <el-input-number v-model="form.count" :min="0" :max="10000" />
          <span class="muted hint">0 表示不限，一直补到总体上限</span>
        </el-form-item>
        <el-form-item label="每本章数">
          <el-input-number v-model="form.chapters" :min="1" :max="500" />
          <span class="muted hint">大纲按这个章数规划；前若干章是试读</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editing = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.clip {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.hint {
  margin-left: 12px;
}
</style>

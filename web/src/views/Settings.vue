<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { api, type Settings } from '../api'
import { refreshStatus, store } from '../store'

const form = reactive<Partial<Settings>>({})
const saving = ref(false)

onMounted(async () => {
  Object.assign(form, await api.settings())
})

async function save(): Promise<void> {
  saving.value = true
  try {
    Object.assign(form, await api.saveSettings(form))
    ElMessage.success('设置已保存，下一轮调度生效')
    await refreshStatus()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-title">
      <h2>设置</h2>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </div>
    <el-form label-width="150px" class="form">
      <el-card shadow="never" class="gap">
        <template #header>数量上限（防止过度生产）</template>
        <el-form-item label="总体待生产上限">
          <el-input-number v-model="form.max_total" :min="0" :max="100000" />
          <span class="muted hint">没写完、没进回收站的书最多这么多本；低于它才从题材里补新书</span>
        </el-form-item>
        <el-form-item label="大纲积压上限">
          <el-input-number v-model="form.max_outline_backlog" :min="1" :max="10000" />
          <span class="muted hint">大纲生成中 + 待审 + 待写试读的总数，满了不开新大纲</span>
        </el-form-item>
        <el-form-item label="试读积压上限">
          <el-input-number v-model="form.max_trial_backlog" :min="1" :max="10000" />
          <span class="muted hint">试读生成中 + 待审 + 待续写全书的总数，满了不开新试读</span>
        </el-form-item>
      </el-card>

      <el-card shadow="never" class="gap">
        <template #header>人工审核</template>
        <el-form-item label="大纲审核">
          <el-switch v-model="form.outline_review" />
          <span class="muted hint">开启后只写大纲，等人审核通过再写试读</span>
        </el-form-item>
        <el-form-item label="试读审核">
          <el-switch v-model="form.trial_review" />
          <span class="muted hint">开启后写完试读就停，等人审核通过再续写全书</span>
        </el-form-item>
        <el-form-item label="试读章数">
          <el-input-number v-model="form.trial_chapters" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="回收站保留天数">
          <el-input-number v-model="form.trash_days" :min="1" :max="365" />
          <span class="muted hint">到期自动永久删除</span>
        </el-form-item>
      </el-card>

      <el-card shadow="never" class="gap">
        <template #header>运行</template>
        <el-form-item label="同时生成本数">
          <el-input-number v-model="form.concurrency" :min="1" :max="16" />
          <span class="muted hint">并发越高越快，也越容易撞模型限流</span>
        </el-form-item>
        <el-form-item label="每章候选稿">
          <el-input-number v-model="form.drafts" :min="1" :max="4" />
          <span class="muted hint">评审从几份候选里挑一份，越多越贵</span>
        </el-form-item>
        <el-form-item label="演练模式">
          <el-switch v-model="form.dry_run" />
          <span class="muted hint">不调模型，用占位内容跑通整条流程，用来试操作</span>
        </el-form-item>
        <el-form-item label="模型密钥">
          <el-tag :type="store.status?.model_key.set ? 'success' : 'danger'">
            {{ store.status?.model_key.env }} {{ store.status?.model_key.set ? '已设置' : '未设置' }}
          </el-tag>
        </el-form-item>
      </el-card>
    </el-form>
  </div>
</template>

<style scoped>
.form {
  max-width: 900px;
}
.gap {
  margin-bottom: 16px;
}
.hint {
  margin-left: 12px;
}
</style>

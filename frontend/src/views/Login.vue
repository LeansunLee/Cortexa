<template>
  <div class="login-page">
    <div class="login-story"><div class="wordmark"><Bot :size="28" /> Cortexa</div><div><p class="eyebrow">YOUR AGENTS. YOUR WORKSPACE.</p><h1>让智能协作<br>从这里开始。</h1><p>在属于你的工作空间，与获授权的 Agent 一起工作。</p></div><span class="story-footer">统一身份 · 空间隔离 · 按需授权</span></div>
    <main class="login-main"><form class="login-card" @submit.prevent="submit">
      <div class="login-icon"><ShieldCheck :size="28" /></div>
      <h2>{{ changing ? '设置你的新密码' : '欢迎回来' }}</h2>
      <p>{{ changing ? '修改后所有旧会话将失效，请使用新密码重新登录。' : '使用管理员分配的账号登录。' }}</p>
      <label v-if="!changing">账号<input v-model.trim="username" autocomplete="username" required autofocus placeholder="请输入账号" /></label>
      <label>{{ changing ? '当前密码' : '密码' }}<input v-model="password" type="password" autocomplete="current-password" required maxlength="128" /></label>
      <template v-if="changing"><label>新密码<input v-model="newPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" required placeholder="至少 8 位" /></label><label>确认新密码<input v-model="confirmPassword" type="password" autocomplete="new-password" required /></label></template>
      <div v-if="error" class="login-error" role="alert">{{ error }}</div>
      <div v-if="notice" class="login-notice">{{ notice }}</div>
      <button class="login-submit" :disabled="busy">{{ busy ? '处理中…' : changing ? '保存新密码' : '登录' }}<ArrowRight :size="18" /></button>
      <button v-if="changing" type="button" class="login-back" @click="logout">退出登录</button>
      <small v-else>如需账号或重置密码，请联系系统管理员。</small>
    </form></main>
  </div>
</template>
<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bot, ShieldCheck, ArrowRight } from 'lucide-vue-next'
import api from '../api'
import { auth, refreshAuth, logout } from '../auth'
const route = useRoute(), router = useRouter()
const changing = computed(() => route.path === '/change-password')
const username = ref(''), password = ref(''), newPassword = ref(''), confirmPassword = ref('')
const error = ref(''), notice = ref(''), busy = ref(false)
async function submit() {
  error.value = ''; busy.value = true
  try {
    if (changing.value) {
      if (newPassword.value !== confirmPassword.value) throw new Error('两次新密码不一致')
      await api.post('/auth/password', { old_password: password.value, new_password: newPassword.value })
      auth.user = null
      password.value = ''; newPassword.value = ''; confirmPassword.value = ''
      notice.value = '密码已修改，请重新登录。'
      await router.replace('/login')
    } else {
      await api.post('/auth/login', { username: username.value, password: password.value }, { skipAuthRedirect: true })
      const user = await refreshAuth()
      await router.replace(user.must_change_password ? '/change-password' : '/')
    }
  } catch (e) { error.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : e.message || '操作失败' }
  finally { busy.value = false }
}
</script>
<style scoped>
.login-page{display:grid;grid-template-columns:1fr 1fr;min-height:100vh;background:var(--bg);width:100%}.login-story{padding:54px 64px;background:#17152c;color:#fff;display:flex;flex-direction:column;justify-content:space-between;background-image:radial-gradient(ellipse at 10% 80%,#423271 0%,transparent 65%)}.wordmark{display:flex;align-items:center;gap:12px;font-size:20px;font-weight:650}.eyebrow{font-size:11px;letter-spacing:3px;color:#b9a5e8}.login-story h1{font-size:clamp(36px,4vw,62px);line-height:1.3;letter-spacing:-2px;margin:24px 0}.login-story p:not(.eyebrow){color:#c9c4db;line-height:1.8;max-width:350px}.story-footer{font-size:12px;color:#a49abb}.login-main{display:flex;align-items:center;justify-content:center;padding:48px}.login-card{width:100%;max-width:380px}.login-icon{width:54px;height:54px;background:var(--primary-light);color:var(--primary);border-radius:16px;display:grid;place-items:center;margin-bottom:28px}.login-card h2{font-size:28px;letter-spacing:-.5px;margin-bottom:12px}.login-card p{font-size:14px;color:var(--text2);line-height:1.7;margin-bottom:32px}.login-card label{display:block;font-size:13px;font-weight:600;margin:18px 0}.login-card input{width:100%;display:block;padding:13px 14px;border:1px solid var(--border);border-radius:9px;margin-top:9px;font-size:14px;outline:none}.login-card input:focus{border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-light)}.login-submit{width:100%;display:flex;justify-content:center;gap:12px;padding:14px;margin:26px 0 20px;border:0;border-radius:9px;background:var(--primary);color:#fff;font-size:15px;font-weight:600;cursor:pointer}.login-submit:disabled{opacity:.6}.login-card small{display:block;text-align:center;color:var(--text3);font-size:12px}.login-error,.login-notice{padding:12px;border-radius:8px;font-size:13px;line-height:1.5;background:var(--danger-bg);color:var(--danger)}.login-notice{background:var(--success-bg);color:var(--success)}.login-back{display:block;margin:auto;border:0;background:none;cursor:pointer;color:var(--text2)}@media(max-width:800px){.login-page{grid-template-columns:1fr}.login-story{display:none}.login-main{padding:28px}}
</style>

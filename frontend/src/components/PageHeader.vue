<template>
  <header v-if="$slots.default" class="app-page-heading" :class="{ 'app-page-heading-compact': compact }">
    <div class="app-page-heading-actions"><slot /></div>
  </header>
</template>

<script setup>
defineProps({ compact: Boolean })
</script>

<style scoped>
.app-page-heading {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  margin: 0 0 24px;
  padding: 0;
}
.app-page-heading-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; flex-wrap: wrap; max-width: 100%; }
.app-page-heading-compact { margin: 0; padding: 16px; gap: 12px; }
</style>

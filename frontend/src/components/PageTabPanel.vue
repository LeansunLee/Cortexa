<template>
  <div v-show="active" class="page-content" role="tabpanel" :aria-labelledby="labelId" :id="panelId" :inert="!active">
    <router-view :route="location" />
  </div>
</template>

<script setup>
import { computed, provide, shallowReactive } from 'vue'
import { routeLocationKey } from 'vue-router'
const emit = defineEmits(['title-change'])
provide('setPageTabTitle', title => emit('title-change', title))
const props = defineProps({ location: Object, active: Boolean, labelId: String, panelId: String })
// Each mounted page sees its own route while other tabs are active.
const localRoute = {}
for (const key of Object.keys(props.location)) {
  Object.defineProperty(localRoute, key, { enumerable: true, get: () => props.location[key] })
}
provide(routeLocationKey, shallowReactive(localRoute))
provide('pageTabActive', computed(() => props.active))
</script>

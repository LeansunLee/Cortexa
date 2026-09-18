import { createApp } from 'vue'
import App from './App.vue'
import AppIcon from './components/AppIcon.vue'
import PageHeader from './components/PageHeader.vue'
import SearchSelect from './components/SearchSelect.vue'
import router from './router'
import './styles/components.css'
import './styles/theme-controls.css'
import { readTheme, applyTheme } from './utils/theme'
import { readAppearance, applyAppearance, watchSystemAppearance } from './utils/appearance'

// Restore color and appearance before rendering to avoid a light-mode flash.
applyTheme(readTheme())
applyAppearance(readAppearance())
watchSystemAppearance()

const app = createApp(App)
app.component('AppIcon', AppIcon)
app.component('PageHeader', PageHeader)
app.component('SearchSelect', SearchSelect)
app.use(router)
app.mount('#app')

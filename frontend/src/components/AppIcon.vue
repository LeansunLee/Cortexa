<template><component :is="icons[name] || Bot" :size="size" :stroke-width="1.8" class="app-icon" aria-hidden="true" /></template>
<script setup>
import { Bot, Building2, RefreshCw, FlaskConical, Zap, Database, Check, X, Info, FileText, Wrench, Crown, Circle, User, Calendar, Target, Lightbulb, AlertTriangle, ChartColumn, Palette, Globe, Megaphone, Wallet, ClipboardList, Settings, Users, Scale, ShoppingCart, MessageSquare, Compass, TrendingUp, Shield, Briefcase, ChevronDown, Layers, Clock, Loader, Plus, Hash } from 'lucide-vue-next'
defineProps({ name: { type: String, default: 'Bot' }, size: { type: Number, default: 16 } })
const icons = { Bot, Building2, RefreshCw, FlaskConical, Zap, Database, Check, X, Info, FileText, Wrench, Crown, Circle, User, Calendar, Target, Lightbulb, AlertTriangle, ChartColumn, Palette, Globe, Megaphone, Wallet, ClipboardList, Settings, Users, Scale, ShoppingCart, MessageSquare, Compass, TrendingUp, Shield, Briefcase, ChevronDown, Layers, Clock, Loader, Plus, Hash }
</script>
<style scoped>
.app-icon { display: inline-block; vertical-align: -0.18em; flex-shrink: 0; }
</style>

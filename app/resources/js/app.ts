import type { DefineComponent } from 'vue'
import { createInertiaApp } from '@inertiajs/vue3'
import { configureEcho } from '@laravel/echo-vue'
import ui from '@nuxt/ui/vue-plugin'
import { resolvePageComponent } from 'laravel-vite-plugin/inertia-helpers'
import { createApp, h } from 'vue'
import '../css/app.css'

const appName = import.meta.env.VITE_APP_NAME || 'Laravel'
const reverbScheme = import.meta.env.VITE_REVERB_SCHEME || 'http'
const reverbHost = import.meta.env.VITE_REVERB_HOST || window.location.hostname || 'localhost'
const reverbPort = Number(import.meta.env.VITE_REVERB_PORT || 8081)
const reverbKey = import.meta.env.VITE_REVERB_APP_KEY || 'ttrmd93dkuczs0aeouur'

configureEcho({
  broadcaster: 'reverb',
  key: reverbKey,
  wsHost: reverbHost,
  wsPort: reverbPort,
  wssPort: reverbPort,
  forceTLS: reverbScheme === 'https',
  enabledTransports: ['ws', 'wss'],
})

createInertiaApp({
  title: title => (title ? `${title} - ${appName}` : appName),
  resolve: name =>
    resolvePageComponent(
      `./pages/${name}.vue`,
      import.meta.glob<DefineComponent>('./pages/**/*.vue'),
    ),
  setup({ el, App, props, plugin }) {
    createApp({ render: () => h(App, props) })
      .use(plugin)
      .use(ui)
      .mount(el)
  },
  progress: {
    color: '#4B5563',
  },
})

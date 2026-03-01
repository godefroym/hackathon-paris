import { wayfinder } from '@laravel/vite-plugin-wayfinder'
import ui from '@nuxt/ui/vite'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import laravel from 'laravel-vite-plugin'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [
    laravel({
      input: ['resources/js/app.ts'],
      ssr: 'resources/js/ssr.ts',
      refresh: true,
    }),
    tailwindcss(),
    vue({
      template: {
        transformAssetUrls: {
          base: null,
          includeAbsolute: false,
        },
      },
    }),
    ui({
      ui: {
        colors: {
          neutral: 'neutral',
        },
      },
      colorMode: false,
      autoImport: {
        dts: 'resources/js/auto-imports.d.ts',
        imports: [
          'vue',
          '@vueuse/core',
          {
            from: "tailwind-variants",
            imports: ["tv"],
          },
        ],
        exclude: ['resources/js/wayfinder/**', 'resources/js/routes/**'],
      },
      components: {
        dts: 'resources/js/components.d.ts',
        dirs: ['resources/js/components'],
      },
      router: 'inertia',
    }),
    wayfinder({
      formVariants: true,
    }),
  ],
})

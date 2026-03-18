<script lang="ts" setup>
import QRCode from 'qrcode'

const qrCodeDataUrl = ref('')

const monitorUrl = computed(() => {
  if (typeof window === 'undefined') {
    return '/overlays/fact-check-monitor'
  }

  const params = new URLSearchParams(window.location.search)
  const explicitTarget = params.get('target')
  if (explicitTarget) {
    return explicitTarget
  }

  return new URL('/overlays/fact-check-monitor', window.location.origin).toString()
})

onMounted(async () => {
  qrCodeDataUrl.value = await QRCode.toDataURL(monitorUrl.value, {
    width: 280,
    margin: 1,
    color: {
      dark: '#111111',
      light: '#ffffffff',
    },
  })
})
</script>

<template>
  <UApp>
    <main class="fc-scene-root">
      <div class="fc-scene-grid" />

      <section class="fc-scene-copy">
        <p class="fc-scene-kicker">
          Fact-check control
        </p>
        <h1 class="fc-scene-title">
          Scan to open the live banner monitor
        </h1>
        <p class="fc-scene-body">
          This page is designed for an OBS scene. The monitor shows the full recent banner history with clickable source links.
        </p>
      </section>

      <aside class="fc-scene-qr">
        <div class="fc-scene-qr-card">
          <img
            v-if="qrCodeDataUrl"
            :src="qrCodeDataUrl"
            alt="QR code for fact-check monitor"
            class="fc-scene-qr-image"
          >
          <div
            v-else
            class="fc-scene-qr-placeholder"
          />

          <div class="fc-scene-qr-copy">
            <p class="fc-scene-qr-label">
              Monitor URL
            </p>
            <a
              :href="monitorUrl"
              target="_blank"
              rel="noreferrer noopener"
              class="fc-scene-qr-link"
            >
              {{ monitorUrl }}
            </a>
          </div>
        </div>
      </aside>
    </main>
  </UApp>
</template>

<style scoped>
.fc-scene-root {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(circle at 15% 20%, rgba(255, 202, 202, 0.3), transparent 24%),
    radial-gradient(circle at 85% 15%, rgba(250, 228, 153, 0.28), transparent 20%),
    linear-gradient(135deg, #20130f 0%, #34211a 45%, #231712 100%);
  color: #fff8ef;
}

.fc-scene-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.8), transparent 85%);
}

.fc-scene-copy {
  position: relative;
  z-index: 1;
  max-width: 50rem;
  padding: 3rem 3rem 12rem;
}

.fc-scene-kicker {
  margin: 0 0 0.5rem;
  font-size: 1rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: #ffcf8e;
}

.fc-scene-title {
  margin: 0;
  font-size: clamp(3rem, 6vw, 6.5rem);
  line-height: 0.92;
  font-weight: 900;
  max-width: 48rem;
}

.fc-scene-body {
  margin: 1.25rem 0 0;
  max-width: 32rem;
  font-size: clamp(1.05rem, 2vw, 1.35rem);
  line-height: 1.5;
  color: rgba(255, 248, 239, 0.82);
}

.fc-scene-qr {
  position: absolute;
  left: 2rem;
  bottom: 2rem;
  z-index: 2;
}

.fc-scene-qr-card {
  display: flex;
  align-items: end;
  gap: 1rem;
  padding: 1rem;
  border-radius: 1.5rem;
  background: rgba(255, 248, 239, 0.96);
  color: #241510;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
}

.fc-scene-qr-image,
.fc-scene-qr-placeholder {
  width: 14rem;
  height: 14rem;
  border-radius: 1rem;
  background: white;
}

.fc-scene-qr-copy {
  max-width: 19rem;
}

.fc-scene-qr-label {
  margin: 0 0 0.4rem;
  font-size: 0.86rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #8a5b42;
}

.fc-scene-qr-link {
  font-size: 1rem;
  line-height: 1.45;
  font-weight: 700;
  color: #241510;
  word-break: break-word;
  text-decoration: none;
}

.fc-scene-qr-link:hover {
  text-decoration: underline;
}

@media (max-width: 900px) {
  .fc-scene-copy {
    padding: 2rem 1rem 18rem;
  }

  .fc-scene-qr {
    left: 1rem;
    right: 1rem;
    bottom: 1rem;
  }

  .fc-scene-qr-card {
    flex-direction: column;
    align-items: start;
  }
}
</style>

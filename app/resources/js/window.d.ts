import type Axios from 'axios'
import type Echo from 'laravel-echo'
import type Pusher from 'pusher-js'

declare global {
  interface Window {
    Pusher: typeof Pusher
    Echo: Echo<'reverb'>
    axios: typeof Axios
  }
}

export {}

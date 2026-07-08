import { onUnmounted } from 'vue'

/**
 * Interval poller that cleans up after itself and pauses while the browser tab
 * is hidden — so a workflow left open in a background tab stops hammering the
 * API, and resumes (with an immediate refresh) when the tab is shown again.
 *
 * Usage:
 *   const poll = usePolling(fetchStatus, { interval: 5000 })
 *   // start when the run goes live, stop when it finishes / on unmount (auto)
 *   watch(isLive, (live) => (live ? poll.start() : poll.stop()))
 *
 * `fn` is invoked on every tick (and once immediately on becoming visible after
 * a hidden stretch, if still running). It may be async; overlapping ticks are
 * skipped while a previous call is still in flight.
 */
export function usePolling(fn, { interval = 5000 } = {}) {
  let timer = null
  let running = false
  let inFlight = false

  const tick = async () => {
    if (inFlight) return
    inFlight = true
    try {
      await fn()
    } finally {
      inFlight = false
    }
  }

  const arm = () => {
    if (timer == null && !document.hidden) {
      timer = setInterval(tick, interval)
    }
  }

  const disarm = () => {
    if (timer != null) {
      clearInterval(timer)
      timer = null
    }
  }

  const onVisibility = () => {
    if (!running) return
    if (document.hidden) {
      disarm()
    } else {
      tick() // catch up immediately on return to the tab
      arm()
    }
  }

  const start = () => {
    if (running) return
    running = true
    document.addEventListener('visibilitychange', onVisibility)
    arm()
  }

  const stop = () => {
    running = false
    disarm()
    document.removeEventListener('visibilitychange', onVisibility)
  }

  onUnmounted(stop)

  return { start, stop, isRunning: () => running }
}

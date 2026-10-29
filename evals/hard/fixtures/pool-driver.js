// Minimal stand-in for the real CDP EngineDriver: the pool only calls launch() and close().
export let launchCount = 0
export class EngineDriver {
  async launch(_opts) { launchCount++ }
  async close() {}
}

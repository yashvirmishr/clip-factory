export {}

declare global {
  interface Window {
    clipFactory?: {
      desktop: boolean
      platform: string
      versions: { electron: string; chrome: string; node: string }
      copyText: (text: string) => Promise<boolean>
      /** Show a folder inside the app data directory; main refuses anything else. */
      openPath: (target: string) => Promise<{ ok: boolean; error: string }>
    }
  }
}

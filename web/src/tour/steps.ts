import type { TourStep } from './types'

/**
 * Seven steps, in the order a first clip actually gets made. Setup is the first
 * two; the rest point at the real controls and wait for the real action, so a
 * person learns by doing rather than by reading.
 */
export const TOUR_STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: 'One long video in, a handful of shorts out.',
    panel: 'welcome',
    action: { label: 'Start setup', id: 'next' },
  },
  {
    id: 'ready',
    title: 'Is this computer ready?',
    body: 'Three checks, and two usually already pass.',
    panel: 'readiness',
  },
  {
    id: 'add',
    anchor: 'ingest',
    title: 'Add a video.',
    body:
      'Drop in a file or paste a link. For the tour, take the demo stream: it is a real video, and it needs no models.',
    action: { label: 'Add the demo video', id: 'demo' },
    doneWhen: 'source',
  },
  {
    id: 'analyze',
    anchor: 'analyze',
    title: 'Let it watch the whole thing.',
    body:
      'Analysis reads the speech, finds the moments worth keeping, then scores them. A four-minute video takes under a minute.',
    action: { label: 'Analyze', id: 'analyze' },
    doneWhen: 'analysis',
  },
  {
    id: 'read',
    anchor: 'clips',
    title: 'Read what it found.',
    body:
      'Each card is one clip: its hook, what it noticed, and its score. Open a card to see the whole picture.',
    action: { label: 'Open the first clip', id: 'select' },
  },
  {
    id: 'decide',
    anchor: 'verdict',
    title: 'You get the last word.',
    body:
      'Approve what you would post, reject what you would not. Every rejection teaches the ranking, so the next batch lands closer to your taste.',
    action: { label: 'Approve this clip', id: 'approve' },
    doneWhen: 'verdict',
  },
  {
    id: 'finish',
    anchor: 'render',
    title: 'Make the file.',
    body:
      'Rendering writes a vertical MP4 with burned-in captions. The export bundle is for taking the edit into another editor.',
    action: { label: 'Render this clip', id: 'render' },
    secondary: { label: 'Finish the tour', id: 'finish' },
  },
]

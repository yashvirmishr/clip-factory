import { Modal } from './Modal'

const GROUPS: Array<{ title: string; rows: Array<[string, string[]]> }> = [
  {
    title: 'Areas',
    rows: [
      ['Command palette', ['Ctrl', 'K']],
      ['Library / Clips / Publish', ['Ctrl', '1', '2', '3']],
      ['Clips / Monitor / Timeline', ['1', '2', '3']],
      ['Toggle inspector', ['Ctrl', 'B']],
      ['Keyboard shortcuts', ['?']],
    ],
  },
  {
    title: 'Review',
    rows: [
      ['Next / previous clip', ['J', 'K']],
      ['Approve selected clip', ['A']],
      ['Reject selected clip', ['X']],
      ['Render selected clip', ['R']],
      ['Dismiss rejection bar', ['Esc']],
    ],
  },
  {
    title: 'Monitor',
    rows: [
      ['Play / pause', ['Space']],
      ['Step one second', ['←', '→']],
      ['Step five seconds', ['Shift', '←/→']],
      ['Step one frame', [',', '.']],
      ['Loop selected clip', ['L']],
    ],
  },
]

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Modal
      title="Keyboard shortcuts"
      eyebrow="Reference"
      onClose={onClose}
      width={760}
      className="shortcuts-modal"
      footer={
        <p className="dialog-note">
          Shortcuts stay out of the way while you type in the hook, trim or search fields.
        </p>
      }
    >
      <div className="shortcut-grid">
        {GROUPS.map((group) => (
          <section className="shortcut-group" key={group.title}>
            <h3>{group.title}</h3>
            <dl>
              {group.rows.map(([label, keys]) => (
                <div className="shortcut-row" key={label}>
                  <dt>{label}</dt>
                  <dd>
                    {keys.map((key) =>
                      key === '/' ? (
                        <span className="shortcut-or" key={key}>/</span>
                      ) : (
                        <kbd className="kbd" key={key}>{key}</kbd>
                      ),
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Modal>
  )
}

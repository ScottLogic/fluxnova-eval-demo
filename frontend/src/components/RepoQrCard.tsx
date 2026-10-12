const REPO_URL = 'https://github.com/ScottLogic/fluxnova-eval-demo'

function RepoQrCard() {
  return (
    <aside className="finos-panel repo-qr-card" aria-label="Project repository">
      <p className="sample-preview-label">Get the code</p>
      <a className="repo-qr-link" href={REPO_URL} target="_blank" rel="noreferrer">
        <img className="repo-qr-image" src="/qr.png" alt="QR code linking to the GitHub repository" />
      </a>
      <p className="finos-panel-lede">
        Scan to open the repo on GitHub, or{' '}
        <a href={REPO_URL} target="_blank" rel="noreferrer">click here</a>.
      </p>
    </aside>
  )
}

export default RepoQrCard

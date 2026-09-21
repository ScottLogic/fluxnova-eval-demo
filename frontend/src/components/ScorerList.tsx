import type { EvalScorer } from '../api'

interface ScorerListProps {
  title: string
  scorers: EvalScorer[]
}

function ScorerList({ title, scorers }: ScorerListProps) {
  return (
    <div>
      <p className="sample-preview-label">{title}</p>
      {scorers.length === 0 ? (
        <p className="hint">No scorers configured.</p>
      ) : (
        <dl className="scorer-list">
          {scorers.map((scorer) => (
            <div key={scorer.name}>
              <dt>{scorer.name}</dt>
              <dd>{scorer.description || 'No description available.'}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

export default ScorerList

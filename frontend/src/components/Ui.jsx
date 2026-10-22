/**
 * Small shared building blocks.
 *
 * Keeping these in one file keeps the four views focused on their data instead
 * of repeating loading/error/heading markup.
 */

export function Loading({ label = "Loading..." }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ message, hint }) {
  return (
    <div className="error" role="alert">
      <strong>Could not load this data</strong>
      {message}
      {hint ? <div className="note" style={{ marginTop: 6 }}>{hint}</div> : null}
    </div>
  );
}

/**
 * The visible "explain it in the viva" line required on every view.
 */
export function Explain({ children }) {
  return (
    <p className="explain">
      <span className="explain-label">Viva</span>
      {children}
    </p>
  );
}

export function StatCard({ label, value, hint, tone = "" }) {
  return (
    <div className={`card stat-card ${tone}`.trim()}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

export function Badge({ children, tone = "info" }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Section({ title, hint, actions, children }) {
  return (
    <section className="section">
      <div className="section-head">
        <div>
          <h3>{title}</h3>
          {hint ? <p className="section-hint">{hint}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

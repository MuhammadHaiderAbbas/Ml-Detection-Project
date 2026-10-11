export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit && offset === 0) return <div className="pagination">{total} {total === 1 ? "record" : "records"}</div>;
  const from = total ? offset + 1 : 0;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="num">{from}–{to} of {total.toLocaleString()}</span>
      <button className="btn small" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</button>
      <button className="btn small" disabled={to >= total} onClick={() => onChange(offset + limit)}>Next</button>
    </nav>
  );
}

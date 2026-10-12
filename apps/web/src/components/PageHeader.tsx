import { useEffect, type ReactNode } from "react";

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  useEffect(() => { document.title = `${title} · Adaptive IDS`; }, [title]);
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {description ? <p className="desc">{description}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}

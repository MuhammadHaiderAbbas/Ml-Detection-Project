import { useEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  /** When set, the user must type a reason; it is passed to onConfirm. */
  reasonLabel?: string;
  reasonRequired?: boolean;
  danger?: boolean;
  onConfirm: (reason: string) => Promise<void> | void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, children, confirmLabel, reasonLabel, reasonRequired, danger, onConfirm, onCancel }: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const first = useRef<HTMLTextAreaElement & HTMLButtonElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const submit = async () => {
    if (reasonRequired && !reason.trim()) { setError("A reason is required."); return; }
    setBusy(true);
    setError(undefined);
    try { await onConfirm(reason.trim()); } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-title">
        <h2 id="dlg-title">{title}</h2>
        {children ? <div className="secondary">{children}</div> : null}
        {reasonLabel ? (
          <label className="field" style={{ marginTop: 12 }}>
            {reasonLabel}{reasonRequired ? " (required)" : ""}
            <textarea ref={first} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
          </label>
        ) : null}
        {error ? <p className="field-error" role="alert">{error}</p> : null}
        <div className="actions">
          <button className="btn" onClick={onCancel} disabled={busy} ref={reasonLabel ? undefined : first}>Cancel</button>
          <button className={`btn ${danger ? "danger" : "primary"}`} onClick={submit} disabled={busy}>{busy ? "Working…" : confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

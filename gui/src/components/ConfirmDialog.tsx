// A modal confirmation on the native <dialog>: the browser handles focus, Esc, the
// top layer and returning focus to the button that opened it.
import { type ReactNode, useEffect, useId, useRef } from "react";

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      // Light dismiss where supported; Esc and the close buttons work everywhere.
      {...({ closedby: "any" } as object)}
      onClose={() => {
        const confirmed = ref.current?.returnValue === "confirm";
        if (ref.current) ref.current.returnValue = "";
        if (confirmed) onConfirm();
        onClose();
      }}
    >
      <form method="dialog">
        <h2 id={titleId}>{title}</h2>
        <div className="stack">{children}</div>
        <div className="actions">
          <button type="submit" value="cancel" className="button" autoFocus>
            Annuler
          </button>
          <button type="submit" value="confirm" className="button danger">
            {confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}

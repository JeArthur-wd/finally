import type { ReactNode } from "react";

type Props = {
  title: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  testId?: string;
};

/** Bordered terminal panel with a compact uppercase title bar. */
export function Panel({ title, right, children, className = "", bodyClassName = "", testId }: Props) {
  return (
    <section
      data-testid={testId}
      className={`flex min-h-0 min-w-0 flex-col rounded-[3px] border border-border bg-panel ${className}`}
    >
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b border-border-soft px-3">
        <h2 className="truncate text-[11px] font-semibold uppercase tracking-[0.09em] text-muted">
          {title}
        </h2>
        {right && <div className="flex shrink-0 items-center gap-2 text-[11px] text-muted">{right}</div>}
      </header>
      <div className={`relative min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

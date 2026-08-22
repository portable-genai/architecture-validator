import type { ReactNode } from "react";

/** A titled panel with the banking-grade neutral surface. */
export function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl bg-white shadow-panel ring-1 ring-inset ring-ink-200">
      <header className="border-b border-ink-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
        {subtitle ? <p className="text-[11px] text-ink-400">{subtitle}</p> : null}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Pill({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${className}`}
    >
      {children}
    </span>
  );
}

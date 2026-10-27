import type { ConnectionStatus } from "@/lib/connection";
import { fmtPct, fmtSignedUsd, fmtUsd, toneClass } from "@/lib/format";

type Props = {
  totalValue: number | null;
  cash: number | null;
  unrealizedPnl: number | null;
  positionsValue: number | null;
  status: ConnectionStatus;
};

const STATUS_STYLE: Record<ConnectionStatus, { dot: string; label: string }> = {
  connected: { dot: "bg-up shadow-[0_0_6px_#26a69a]", label: "Live" },
  reconnecting: { dot: "bg-accent shadow-[0_0_6px_#ecad0a] animate-pulse", label: "Reconnecting" },
  disconnected: { dot: "bg-down shadow-[0_0_6px_#ef5350]", label: "Disconnected" },
};

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col justify-center leading-tight">
      <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-faint">{label}</span>
      {children}
    </div>
  );
}

export function Header({ totalValue, cash, unrealizedPnl, positionsValue, status }: Props) {
  const s = STATUS_STYLE[status];
  const invested = positionsValue ?? 0;
  const pnlPct = unrealizedPnl != null && invested - unrealizedPnl > 0 ? (unrealizedPnl / (invested - unrealizedPnl)) * 100 : null;
  return (
    <header className="flex h-14 shrink-0 items-center gap-6 border-b border-border bg-panel px-4">
      <div className="flex items-baseline gap-2">
        <span className="text-[17px] font-bold tracking-tight">
          Fin<span className="text-accent">Ally</span>
        </span>
        <span className="hidden text-[10px] font-semibold uppercase tracking-[0.14em] text-faint sm:inline">
          AI Trading Workstation
        </span>
      </div>

      <div className="ml-auto flex items-center gap-6 sm:gap-8">
        <Stat label="Total value">
          <span data-testid="total-value" className="num text-[18px] font-semibold text-text">
            {fmtUsd(totalValue)}
          </span>
        </Stat>
        <Stat label="Unrealized P&L">
          <span className={`num text-[13px] font-medium ${toneClass(unrealizedPnl)}`}>
            {unrealizedPnl == null ? "—" : fmtSignedUsd(unrealizedPnl)}
            {pnlPct != null && <span className="ml-1.5 text-[11px] opacity-80">{fmtPct(pnlPct)}</span>}
          </span>
        </Stat>
        <Stat label="Cash">
          <span data-testid="cash-balance" className="num text-[13px] font-medium text-text">
            {fmtUsd(cash)}
          </span>
        </Stat>
        <div
          data-testid="connection-status"
          data-status={status}
          title={`Price stream: ${status}`}
          className="flex items-center gap-2 rounded-full border border-border-soft bg-bg px-2.5 py-1"
        >
          <span className={`h-2 w-2 rounded-full ${s.dot}`} aria-hidden />
          <span className="hidden text-[11px] text-muted md:inline">{s.label}</span>
        </div>
      </div>
    </header>
  );
}

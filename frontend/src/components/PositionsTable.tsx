import { fmtPct, fmtPrice, fmtQty, fmtSignedUsd, fmtUsd, toneClass } from "@/lib/format";
import type { Position } from "@/lib/types";
import { EMPTY_POSITIONS_TEXT } from "./Heatmap";
import { Panel } from "./Panel";

type Props = { positions: Position[]; selected: string | null; onSelect: (ticker: string) => void };

const TH = "px-3 py-1.5 text-right font-semibold first:text-left";
const TD = "num px-3 py-1.5 text-right";

export function PositionsTable({ positions, selected, onSelect }: Props) {
  return (
    <Panel title="Positions" right={<span className="num">{positions.length}</span>} className="h-full" bodyClassName="overflow-auto">
      <table data-testid="positions-table" className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 z-10 bg-panel">
          <tr className="border-b border-border-soft text-[10px] uppercase tracking-[0.08em] text-faint">
            <th className={TH}>Symbol</th>
            <th className={TH}>Qty</th>
            <th className={TH}>Avg cost</th>
            <th className={TH}>Last</th>
            <th className={`${TH} hidden xl:table-cell`}>Mkt value</th>
            <th className={TH}>Unrl P&amp;L</th>
            <th className={TH}>%</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr
              key={p.ticker}
              data-testid={`position-row-${p.ticker}`}
              onClick={() => onSelect(p.ticker)}
              className={`cursor-pointer border-b border-border-soft/60 hover:bg-panel-2 ${selected === p.ticker ? "bg-panel-2" : ""}`}
            >
              <td className="px-3 py-1.5 text-left font-semibold">{p.ticker}</td>
              <td className={TD}>{fmtQty(p.quantity)}</td>
              <td className={TD}>{fmtPrice(p.avg_cost)}</td>
              <td className={TD}>{fmtPrice(p.current_price)}</td>
              <td className={`${TD} hidden xl:table-cell`}>{fmtUsd(p.market_value)}</td>
              <td className={`${TD} ${toneClass(p.unrealized_pnl)}`}>{fmtSignedUsd(p.unrealized_pnl)}</td>
              <td className={`${TD} ${toneClass(p.unrealized_pnl_pct)}`}>{fmtPct(p.unrealized_pnl_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {positions.length === 0 && (
        <p className="px-6 py-8 text-center text-[12px] text-faint">{EMPTY_POSITIONS_TEXT}</p>
      )}
    </Panel>
  );
}

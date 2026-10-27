import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarketStore } from "@/lib/marketStore";
import type { ChatMessage, Position } from "@/lib/types";
import { MessageBubble } from "./ChatPanel";
import { Header } from "./Header";
import { PositionsTable } from "./PositionsTable";
import { Watchlist } from "./Watchlist";

describe("Header", () => {
  it("renders money values and the connection status", () => {
    render(<Header totalValue={10000} cash={10000} unrealizedPnl={0} positionsValue={0} status="connected" />);
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
  });
});

describe("PositionsTable", () => {
  it("shows the empty state", () => {
    render(<PositionsTable positions={[]} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/No positions yet/)).toBeInTheDocument();
  });

  it("renders a row per position with P&L", () => {
    const p: Position = {
      ticker: "AAPL",
      quantity: 10,
      avg_cost: 100,
      current_price: 110,
      market_value: 1100,
      unrealized_pnl: 100,
      unrealized_pnl_pct: 10,
    };
    render(<PositionsTable positions={[p]} selected={null} onSelect={() => {}} />);
    const row = screen.getByTestId("position-row-AAPL");
    expect(row).toHaveTextContent("+$100.00");
    expect(row).toHaveTextContent("+10.00%");
  });
});

describe("Watchlist", () => {
  it("renders rows in order with live prices and wires remove/select", () => {
    const store = new MarketStore();
    store.ingest({
      AAPL: {
        ticker: "AAPL",
        price: 191,
        previous_price: 190,
        open_price: 190,
        timestamp: 5,
        change: 1,
        change_percent: 0.5,
        direction: "up",
      },
    });
    const onSelect = vi.fn();
    const onRemove = vi.fn();
    const items = ["AAPL", "GOOGL"].map((ticker) => ({
      ticker,
      price: 100,
      previous_price: 100,
      open_price: 100,
      change_percent: 0,
      added_at: "",
    }));
    render(
      <Watchlist
        items={items}
        store={store}
        selected="AAPL"
        onSelect={onSelect}
        onAdd={async () => null}
        onRemove={onRemove}
      />,
    );
    const list = screen.getByTestId("watchlist");
    const rows = within(list).getAllByTestId(/^watchlist-row-/);
    expect(rows.map((r) => r.dataset.testid)).toEqual(["watchlist-row-AAPL", "watchlist-row-GOOGL"]);
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("191.00");
    expect(screen.getByTestId("watchlist-price-AAPL").className).toContain("animate-flash-up");
    expect(screen.getByTestId("watchlist-row-AAPL")).toHaveTextContent("+0.53%");
    fireEvent.click(screen.getByTestId("watchlist-row-GOOGL"));
    expect(onSelect).toHaveBeenCalledWith("GOOGL");
    fireEvent.click(screen.getByTestId("watchlist-remove-AAPL"));
    expect(onRemove).toHaveBeenCalledWith("AAPL");
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});

describe("Chat MessageBubble", () => {
  it("renders action chips with ticker and verbatim error", () => {
    const msg: ChatMessage = {
      id: "1",
      role: "assistant",
      content: "Buying 100000 shares of AAPL.",
      created_at: "",
      actions: [
        { type: "trade", ticker: "AAPL", side: "buy", quantity: 100000, price: null, status: "failed", error: "Insufficient cash: need $19,000,000.00, have $10,000.00" },
        { type: "watchlist", ticker: "PYPL", action: "add", status: "executed" },
      ],
    };
    render(<MessageBubble msg={msg} />);
    expect(screen.getByTestId("chat-message")).toHaveAttribute("data-role", "assistant");
    const chips = screen.getAllByTestId("chat-action");
    expect(chips[0]).toHaveAttribute("data-status", "failed");
    expect(chips[0]).toHaveTextContent("AAPL");
    expect(chips[0]).toHaveTextContent("Insufficient cash: need $19,000,000.00, have $10,000.00");
    expect(chips[1]).toHaveAttribute("data-status", "executed");
    expect(chips[1]).toHaveTextContent("PYPL");
  });
});

import { useState, useEffect, useRef, useCallback } from "react";

type View = "overview" | "scanner" | "markets" | "calendar" | "strategies" | "backtests" | "paper-trading" | "journal";

interface CommandPaletteProps {
  onClose: () => void;
  onNavigate: (view: View) => void;
  onSymbolSelect: (symbol: string) => void;
  activeView: View;
  selectedSymbol: string;
}

interface CommandItem {
  id: string;
  label: string;
  description: string;
  category: "navigation" | "action" | "symbol";
  shortcut?: string;
  action: () => void;
}

const NAVIGATION_COMMANDS: Omit<CommandItem, "action">[] = [
  { id: "overview", label: "Overview", description: "Market overview dashboard", category: "navigation", shortcut: "G O" },
  { id: "scanner", label: "Scanner", description: "Search and filter instruments", category: "navigation", shortcut: "G S" },
  { id: "markets", label: "Markets", description: "Market data and charts", category: "navigation", shortcut: "G M" },
  { id: "calendar", label: "Calendar", description: "Economic events calendar", category: "navigation", shortcut: "G C" },
  { id: "strategies", label: "Strategies", description: "Strategy studio", category: "navigation", shortcut: "G T" },
  { id: "backtests", label: "Backtests", description: "Run and analyze backtests", category: "navigation", shortcut: "G B" },
  { id: "paper-trading", label: "Paper Trading", description: "Simulated portfolio", category: "navigation", shortcut: "G P" },
  { id: "journal", label: "Journal", description: "Trade journal", category: "navigation", shortcut: "G J" },
];

const ACTION_COMMANDS: Omit<CommandItem, "action">[] = [
  { id: "new-strategy", label: "New Strategy", description: "Create a new trading strategy", category: "action", shortcut: "⌘N" },
  { id: "run-backtest", label: "Run Backtest", description: "Execute a backtest", category: "action", shortcut: "⌘R" },
  { id: "place-order", label: "Place Order", description: "Submit a paper order", category: "action", shortcut: "⌘O" },
  { id: "toggle-left", label: "Toggle Workspace", description: "Show/hide left sidebar", category: "action", shortcut: "⌘\\" },
  { id: "toggle-right", label: "Toggle Inspector", description: "Show/hide right inspector", category: "action", shortcut: "⌘⇧\\" },
];

const COMMON_SYMBOLS = [
  "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "IWM",
  "JPM", "V", "WMT", "JNJ", "PG", "MA", "UNH", "HD", "BAC", "XOM",
];

export function CommandPalette({
  onClose,
  onNavigate,
  onSymbolSelect,
  activeView,
  selectedSymbol,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const allCommands: CommandItem[] = [
    ...NAVIGATION_COMMANDS.map((cmd) => ({
      ...cmd,
      action: () => {
        onNavigate(cmd.id as View);
        onClose();
      },
    })),
    ...ACTION_COMMANDS.map((cmd) => ({
      ...cmd,
      action: () => {
        onClose();
      },
    })),
    ...COMMON_SYMBOLS.map((symbol) => ({
      id: `symbol-${symbol}`,
      label: symbol,
      description: `Switch to ${symbol}`,
      category: "symbol" as const,
      action: () => {
        onSymbolSelect(symbol);
        onClose();
      },
    })),
  ];

  const filteredCommands = allCommands
    .filter((cmd) => {
      const search = query.toLowerCase();
      return (
        cmd.label.toLowerCase().includes(search) ||
        cmd.description.toLowerCase().includes(search) ||
        cmd.id.toLowerCase().includes(search)
      );
    })
    .sort((a, b) => {
      // Prioritize current view and selected symbol
      if (a.id === `navigation-${activeView}` || a.id === `symbol-${selectedSymbol}`) return -1;
      if (b.id === `navigation-${activeView}` || b.id === `symbol-${selectedSymbol}`) return 1;
      // Prioritize by category order: navigation > action > symbol
      const categoryOrder = { navigation: 0, action: 1, symbol: 2 };
      return categoryOrder[a.category] - categoryOrder[b.category];
    });

  useEffect(() => {
    inputRef.current?.focus();
    setSelectedIndex(0);
  }, [query]);

  useEffect(() => {
    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, filteredCommands.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          filteredCommands[selectedIndex].action();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [filteredCommands, selectedIndex, onClose]);

  const scrollSelectedIntoView = useCallback(() => {
    const item = listRef.current?.querySelector(`[data-index="${selectedIndex}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  useEffect(() => {
    scrollSelectedIntoView();
  }, [selectedIndex, scrollSelectedIntoView]);

  if (filteredCommands.length === 0) {
    return (
      <div className="command-palette-overlay" onClick={onClose}>
        <div className="command-palette" onClick={(e) => e.stopPropagation()}>
          <div className="command-palette-header">
            <label htmlFor="command-input" className="sr-only">Command</label>
            <input
              ref={inputRef}
              id="command-input"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a command or search..."
              className="command-input"
              autoFocus
            />
            <kbd className="command-shortcut">⌘K</kbd>
          </div>
          <div className="command-palette-empty">
            <p>No commands found</p>
            <p className="hint">Try a different search term</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="command-palette-overlay" onClick={onClose}>
      <div className="command-palette" onClick={(e) => e.stopPropagation()}>
        <div className="command-palette-header">
          <label htmlFor="command-input" className="sr-only">Command</label>
          <input
            ref={inputRef}
            id="command-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command or search..."
            className="command-input"
            autoFocus
          />
          <kbd className="command-shortcut">⌘K</kbd>
        </div>
        <ul className="command-list" ref={listRef} role="listbox" aria-label="Commands">
          {filteredCommands.map((cmd, index) => (
            <li
              key={cmd.id}
              data-index={index}
              className={`command-item ${index === selectedIndex ? "selected" : ""} ${cmd.category}`}
              role="option"
              aria-selected={index === selectedIndex}
              onClick={() => cmd.action()}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              <span className="command-label">{cmd.label}</span>
              <span className="command-description">{cmd.description}</span>
              {cmd.shortcut && <kbd className="command-item-shortcut">{cmd.shortcut}</kbd>}
            </li>
          ))}
        </ul>
        <div className="command-palette-footer">
          <kbd>↑↓</kbd> Navigate &nbsp;
          <kbd>Enter</kbd> Select &nbsp;
          <kbd>Esc</kbd> Close
        </div>
      </div>
    </div>
  );
}
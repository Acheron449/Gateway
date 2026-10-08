export type View =
  | "overview"
  | "scanner"
  | "markets"
  | "calendar"
  | "harness"
  | "strategies"
  | "agentic-lab"
  | "backtests"
  | "paper-trading"
  | "live-trading"
  | "ai-trading"
  | "journal"
  | "settings";

export interface ViewDef {
  id: View;
  label: string;
  icon: string;
  group: "workspace" | "myWork" | "settings";
}

export const VIEWS: ViewDef[] = [
  { id: "overview", label: "Overview", icon: "🏠", group: "workspace" },
  { id: "scanner", label: "Scanner", icon: "🔍", group: "workspace" },
  { id: "markets", label: "Markets", icon: "📈", group: "workspace" },
  { id: "calendar", label: "Calendar", icon: "📅", group: "workspace" },
  { id: "harness", label: "AI Chat", icon: "🤖", group: "workspace" },
  { id: "strategies", label: "Strategies", icon: "🎯", group: "myWork" },
  { id: "agentic-lab", label: "Agentic Lab", icon: "🧪", group: "myWork" },
  { id: "backtests", label: "Backtester", icon: "📊", group: "myWork" },
  { id: "paper-trading", label: "Paper Trading", icon: "📝", group: "myWork" },
  { id: "live-trading", label: "Live Trading", icon: "💸", group: "myWork" },
  { id: "ai-trading", label: "AI Trading", icon: "🧠", group: "myWork" },
  { id: "journal", label: "Journal", icon: "📓", group: "myWork" },
  { id: "settings", label: "Providers", icon: "🔧", group: "settings" },
];

export const VIEW_IDS = VIEWS.map((v) => v.id);

export function isView(value: string | undefined | null): value is View {
  return !!value && (VIEW_IDS as string[]).includes(value);
}

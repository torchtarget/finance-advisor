export interface Recommendation {
  rank: number;
  symbol: string;
  direction: string;
  strategy: string;
  confidence: number;
  entry_price: number;
  target_price: number | null;
  expected_return_pct: number | null;
  allocation_pct: number;
  quantity: number;
  cost: number;
  max_loss_pct: number | null;
  rationale: string;
  generated_at: string;
}

export interface ScanResult {
  recommendations: Recommendation[];
  scanned_at: string;
  total_candidates: number;
  total_signals: number;
  capital: number;
}

export interface Position {
  symbol: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  allocation_pct: number;
  strategy: string | null;
  opened_at: string;
}

export interface Portfolio {
  mode: string;
  cash: number;
  positions: Position[];
  total_value: number;
  starting_capital: number;
  total_return_pct: number;
}

export interface PricePoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Quote {
  symbol: string;
  price: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  week_change_pct: number;
  indicators: Record<string, number | boolean>;
  price_history: PricePoint[];
}

export interface NewsArticle {
  title: string;
  publisher: string;
  link: string;
  published: string;
  source: string;
  description?: string;
}

export interface DataSource {
  name: string;
  type: string;
  status: string;
  provides: string[];
  cost: string;
  key_env?: string;
}

export interface Strategy {
  name: string;
  description: string;
}

# CryptoQuant Frontend Knowledge Base

**Module:** React + TypeScript + Vite frontend  
**Purpose:** Web UI for crypto quantitative trading platform  
**Status:** ✅ Operational — connected to FastAPI backend  
**Lines of Code:** 1,269 (TypeScript/TSX: 773, CSS: 377)

## OVERVIEW

React 19 frontend with Vite 8 build system. Uses lightweight-charts for candlestick 
and equity curve visualization. Connects to FastAPI backend at `http://localhost:8000/api`.

Features:
- Data selection panel (pair/timeframe selection, stats display)
- Interactive candlestick chart (lightweight-charts)
- Backtest configuration panel
- Results display with equity curve
- Data download panel with progress tracking

## STRUCTURE

```
frontend/
├── index.html              # Entry HTML (13 lines)
├── package.json            # Dependencies (32 lines)
├── vite.config.ts          # Vite config (7 lines)
├── tsconfig.json           # TS config root (7 lines)
├── tsconfig.app.json       # App TS config
├── tsconfig.node.json      # Node TS config
├── public/
│   ├── favicon.svg         # App favicon
│   └── icons.svg           # Icon assets
├── src/
│   ├── main.tsx            # React entry point (10 lines)
│   ├── App.tsx             # Main app component (107 lines)
│   ├── App.css             # App styles (373 lines)
│   ├── index.css           # Base styles (5 lines)
│   ├── api.ts              # API client + types (129 lines)
│   ├── components/
│   │   ├── index.ts        # Component exports (5 lines)
│   │   ├── Chart.tsx       # Candlestick + Equity charts (163 lines)
│   │   ├── DataPanel.tsx   # Data selection UI (94 lines)
│   │   ├── StrategyPanel.tsx   # Backtest config (135 lines)
│   │   ├── ResultsPanel.tsx    # Results display (123 lines)
│   │   └── DownloadPanel.tsx   # Download UI (131 lines)
│   └── assets/
│       ├── react.svg
│       ├── vite.svg
│       └── hero.png
└── node_modules/           # Dependencies (gitignored)
```

---

## WHERE TO LOOK

### Core Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/main.tsx` | 10 | React root render, StrictMode wrapper |
| `src/App.tsx` | 107 | Main layout, state management, data loading |
| `src/App.css` | 373 | All CSS styles (dark theme, responsive) |
| `src/api.ts` | 129 | Axios client, TypeScript types, API functions |

### Components (src/components/)

| Component | Lines | Purpose |
|-----------|-------|---------|
| `Chart.tsx` | 163 | `CandlestickChart` + `EquityChart` using lightweight-charts |
| `DataPanel.tsx` | 94 | Pair/timeframe selectors, stats display |
| `StrategyPanel.tsx` | 135 | Strategy selector, backtest params, run button |
| `ResultsPanel.tsx` | 123 | Backtest results display, metrics grid, trades table |
| `DownloadPanel.tsx` | 131 | Download form, progress tracking, status polling |
| `index.ts` | 5 | Barrel exports |

---

## COMPONENT DETAILS

### App.tsx (107 lines)

Main application component with state management:

```typescript
function App() {
  const [selectedPair, setSelectedPair] = useState('');
  const [selectedTimeframe, setSelectedTimeframe] = useState('');
  const [candles, setCandles] = useState<Candle[]>([]);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [candleError, setCandleError] = useState<string | null>(null);
  
  // Load candles when pair/timeframe changes
  const loadCandles = useCallback(async () => { ... }, [selectedPair, selectedTimeframe]);
  
  // Layout: sidebar (panels) + content (chart + results)
  return (
    <div className="app">
      <header>...</header>
      <main className="main">
        <div className="sidebar">
          <DataPanel ... />
          <DownloadPanel ... />
          <StrategyPanel ... />
        </div>
        <div className="content">
          <CandlestickChart ... />
          <ResultsPanel ... />
        </div>
      </main>
    </div>
  );
}
```

**Key logic:**
- `loadCandles()` — fetches up to 1000 candles from API on pair/timeframe change
- `handleBacktestComplete()` — stores backtest result from StrategyPanel
- `handleDataUpdated()` — reloads candles after download completes

### Chart.tsx (163 lines)

Two chart components using lightweight-charts:

**CandlestickChart:**
```typescript
interface ChartProps {
  candles: Candle[];
  height?: number;  // default 400
}

export function CandlestickChart({ candles, height = 400 }: ChartProps) {
  // Creates chart with dark theme
  // Maps Candle[] to lightweight-charts format
  // Handles resize events
  // Returns div with chart container
}
```

**EquityChart:**
```typescript
interface EquityChartProps {
  timestamps: number[];
  values: number[];
  height?: number;  // default 200
}

export function EquityChart({ timestamps, values, height = 200 }: EquityChartProps) {
  // Line chart for portfolio value over time
  // Used in ResultsPanel for backtest equity curve
}
```

**Chart styling:**
- Background: `#1a1a2e` (dark)
- Grid: `#2b2b43`
- Up candles: `#26a69a` (green)
- Down candles: `#ef5350` (red)
- Equity line: `#2962ff` (blue)

### DataPanel.tsx (94 lines)

Data selection and stats display:

```typescript
interface DataPanelProps {
  selectedPair: string;
  selectedTimeframe: string;
  onPairChange: (pair: string) => void;
  onTimeframeChange: (tf: string) => void;
}

export function DataPanel({ ... }: DataPanelProps) {
  const [pairs, setPairs] = useState<Record<string, string[]>>({});
  const [stats, setStats] = useState<Stats | null>(null);
  
  // Fetches pairs on mount
  // Fetches stats when pair/timeframe changes
  // Displays: pair select, timeframe select, stats (count, start, end)
}
```

**Stats displayed:**
- Candles count
- Earliest timestamp (ISO)
- Latest timestamp (ISO)

### StrategyPanel.tsx (135 lines)

Backtest configuration and execution:

```typescript
interface StrategyPanelProps {
  selectedPair: string;
  selectedTimeframe: string;
  onBacktestComplete: (result: BacktestResult) => void;
}

export function StrategyPanel({ ... }: StrategyPanelProps) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState('');
  const [days, setDays] = useState(90);
  const [initialCash, setInitialCash] = useState(10000);
  const [commission, setCommission] = useState(0.001);
  const [slippage, setSlippage] = useState(0.0005);
  
  // Fetches strategies on mount
  // handleRunBacktest() — calls API, passes result to parent
}
```

**Inputs:**
- Strategy selector (from `/api/strategies`)
- Days (1-3650)
- Initial cash (min 100)
- Commission rate (0-0.01)
- Slippage rate (0-0.01)

### ResultsPanel.tsx (123 lines)

Backtest results display:

```typescript
interface ResultsPanelProps {
  result: BacktestResult | null;
}

export function ResultsPanel({ result }: ResultsPanelProps) {
  // Shows placeholder if no result
  // Shows error if result.error
  // Displays: metrics grid, equity chart, trades table
}
```

**Metrics displayed:**
- Strategy name
- Pair/Timeframe
- Initial/Final value
- Total return (highlighted, colored by sign)
- Trade count
- Sharpe ratio
- Max drawdown

**Trades table:**
- Side (long/short, colored)
- Entry price
- Exit price
- PnL (colored by sign)
- Shows first 20 trades

### DownloadPanel.tsx (131 lines)

Data download with progress tracking:

```typescript
interface DownloadPanelProps {
  selectedPair: string;
  selectedTimeframe: string;
  onDataUpdated: () => void;
}

export function DownloadPanel({ ... }: DownloadPanelProps) {
  const [days, setDays] = useState(365);
  const [sandbox, setSandbox] = useState(true);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<DownloadStatus | null>(null);
  
  // Polls status every 2s when running
  // Calls onDataUpdated when completed
}
```

**Status states:**
- `pending` — task queued
- `running` — downloading (blue badge)
- `completed` — success (green badge)
- `failed` — error (red badge)

**Features:**
- Progress bar when progress available
- Status polling (2s interval)
- Sandbox mode checkbox

---

## API CLIENT (src/api.ts)

### Axios Configuration

```typescript
const API_BASE = 'http://localhost:8000/api';

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,  // 30s timeout
});
```

### TypeScript Types

```typescript
export interface Candle {
  timestamp: number;
  iso_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Stats {
  pair: string;
  timeframe: string;
  count: number;
  earliest: number | null;
  latest: number | null;
  earliest_iso: string | null;
  latest_iso: string | null;
}

export interface StrategyInfo {
  name: string;
  class_name: string;
  params: Record<string, unknown>;
}

export interface BacktestRequest {
  strategy: string;
  pair: string;
  timeframe: string;
  days?: number;
  start_date?: string;
  end_date?: string;
  initial_cash?: number;
  commission?: number;
  slippage?: number;
}

export interface BacktestResult {
  strategy_name: string;
  pair: string;
  timeframe: string;
  initial_value: number;
  final_value: number;
  total_return: number;
  total_trades: number;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  trades: Trade[];
  equity_curve: number[];
  equity_timestamps: number[];
  error: string | null;
}

export interface Trade {
  entry_time: number;
  exit_time: number;
  entry_price: string;
  exit_price: string;
  side: 'long' | 'short';
  pnl: number;
}

export interface DownloadRequest {
  pair: string;
  timeframe: string;
  days?: number;
  sandbox?: boolean;
}

export interface DownloadStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  message: string;
  progress: number | null;
}
```

### API Functions

| Function | Endpoint | Purpose |
|----------|----------|---------|
| `getPairs()` | `/pairs` | Get all available pairs with timeframes |
| `getStats(pair, tf)` | `/stats/{pair}/{tf}` | Get data statistics |
| `getCandles(pair, tf, ...)` | `/candles/{pair}/{tf}` | Get OHLCV candles |
| `getStrategies()` | `/strategies` | Get available strategies |
| `runBacktest(req)` | `/backtest` | Execute backtest |
| `startDownload(req)` | `/download` | Start data download |
| `getDownloadStatus(id)` | `/download/{id}` | Check download progress |

---

## STYLING (src/App.css)

### CSS Variables

```css
:root {
  --bg-primary: #0d0d1a;      /* Main background */
  --bg-secondary: #1a1a2e;    /* Panel background */
  --bg-tertiary: #2b2b43;     /* Input background */
  --text-primary: #d1d4dc;    /* Main text */
  --text-secondary: #8a8a9a;  /* Secondary text */
  --accent-green: #26a69a;    /* Positive/long */
  --accent-red: #ef5350;      /* Negative/short */
  --accent-blue: #2962ff;     /* Primary button */
  --border: #2b2b43;          /* Border color */
}
```

### Layout

```css
.main {
  display: grid;
  grid-template-columns: 280px 1fr;  /* Sidebar + Content */
  gap: 20px;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
```

### Responsive

```css
@media (max-width: 900px) {
  .main {
    grid-template-columns: 1fr;  /* Single column */
  }
  
  .sidebar { order: 2; }
  .content { order: 1; }
}
```

### Key Classes

| Class | Purpose |
|-------|---------|
| `.panel` | Container with dark background, border |
| `.form-row` | Label + input/select row |
| `.btn-primary` | Blue action button |
| `.btn-secondary` | Border-only button |
| `.stats` | Stats display container |
| `.status` | Download status container |
| `.status-badge` | Status indicator badge |
| `.progress-bar` | Download progress bar |
| `.chart-section` | Chart container |
| `.metrics-grid` | 3-column metrics display |
| `.metric` | Single metric cell |
| `.positive` | Green text (profit) |
| `.negative` | Red text (loss) |
| `.long` | Green text (long trade) |
| `.short` | Red text (short trade) |
| `.loading-overlay` | Loading spinner container |
| `.error-overlay` | Error message container |
| `.placeholder-overlay` | Empty state container |
| `.trades-table` | Trades table container |

---

## DEPENDENCIES (package.json)

### Runtime Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | ^19.2.6 | UI framework |
| `react-dom` | ^19.2.6 | React DOM renderer |
| `axios` | ^1.16.1 | HTTP client for API |
| `lightweight-charts` | ^5.2.0 | Financial charts library |

### Dev Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `vite` | ^8.0.12 | Build tool, dev server |
| `typescript` | ~6.0.2 | TypeScript compiler |
| `@vitejs/plugin-react` | ^6.0.1 | Vite React plugin |
| `eslint` | ^10.3.0 | Linting |
| `@types/react` | ^19.2.14 | React type definitions |
| `@types/react-dom` | ^19.2.3 | React DOM type definitions |
| `@types/node` | ^24.12.3 | Node type definitions |

---

## CONFIGURATION

### vite.config.ts

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
```

### tsconfig.json (root)

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

---

## COMMANDS

```bash
# Development
cd frontend && npm run dev        # Start Vite dev server (http://localhost:5173)

# Build
npm run build                     # TypeScript check + Vite build (dist/)

# Preview production build
npm run preview                   # Preview built app

# Linting
npm run lint                      # Run ESLint

# Install dependencies
npm install                       # Install from package.json
```

---

## USAGE

### Start Development

```bash
# 1. Start backend (from project root)
cd /home/roler/Code/CryptoQuant
source .venv/bin/activate
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 2. Start frontend
cd frontend
npm run dev

# 3. Open browser
# http://localhost:5173
```

### Build for Production

```bash
cd frontend
npm run build    # Creates dist/ directory
npm run preview  # Preview production build
```

---

## DATA FLOW

```
Browser (localhost:5173)
  → User selects pair/timeframe
    → DataPanel calls getPairs() + getStats()
      → App.tsx calls getCandles(pair, tf, limit=1000)
        → Chart.tsx renders CandlestickChart
        
  → User clicks "Run Backtest"
    → StrategyPanel calls runBacktest(request)
      → Backend executes backtest
        → ResultsPanel receives BacktestResult
          → Metrics grid + EquityChart + Trades table rendered

  → User clicks "Start Download"
    → DownloadPanel calls startDownload(request)
      → Backend starts async download
        → DownloadPanel polls getDownloadStatus(taskId) every 2s
          → On completed: App.tsx reloads candles
```

---

## ANTI-PATTERNS

**FORBIDDEN:**
- Hardcoding API URL (should be configurable)
- Using `any` type (TypeScript strict mode)
- Inline styles (use CSS classes)
- Not handling loading/error states

**WARNINGS:**
- Backend must be running at `localhost:8000` before frontend works
- CORS configured for `localhost:5173` and `localhost:3000` only
- Chart requires timestamp in milliseconds (divide by 1000 for lightweight-charts)
- 30s timeout on API calls (backtest may take longer)

---

## NOTES

- **Framework:** React 19 with TypeScript 6
- **Build:** Vite 8 (fast HMR, ESM-first)
- **Charts:** lightweight-charts (TradingView library)
- **HTTP:** Axios with 30s timeout
- **Theme:** Dark mode (CSS variables)
- **Responsive:** Grid layout, mobile-friendly at <900px
- **Backend:** FastAPI at `http://localhost:8000/api`
- **Port:** Frontend runs on `5173` (Vite default)
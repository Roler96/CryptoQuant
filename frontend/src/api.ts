import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

function encodePair(pair: string): string {
  return pair.replace('/', '-');
}

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
});

// Types
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

// API functions
export async function getPairs(): Promise<Record<string, string[]>> {
  const res = await api.get('/pairs');
  return res.data;
}

export async function getStats(pair: string, timeframe: string): Promise<Stats> {
  const res = await api.get(`/stats/${encodePair(pair)}/${timeframe}`);
  return res.data;
}

export async function getCandles(
  pair: string,
  timeframe: string,
  since?: number,
  until?: number,
  limit?: number,
  order?: 'asc' | 'desc',
): Promise<Candle[]> {
  const res = await api.get(`/candles/${encodePair(pair)}/${timeframe}`, {
    params: { since, until, limit, order },
  });
  return res.data;
}

export async function getStrategies(): Promise<StrategyInfo[]> {
  const res = await api.get('/strategies');
  return res.data;
}

export async function runBacktest(req: BacktestRequest): Promise<BacktestResult> {
  const res = await api.post('/backtest', req);
  return res.data;
}

export async function startDownload(req: DownloadRequest): Promise<DownloadStatus> {
  const res = await api.post('/download', req);
  return res.data;
}

export async function getDownloadStatus(taskId: string): Promise<DownloadStatus> {
  const res = await api.get(`/download/${taskId}`);
  return res.data;
}
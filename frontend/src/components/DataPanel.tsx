import { useState, useEffect } from 'react';
import { getStats, getPairs } from '../api';
import type { Stats } from '../api';

type PairsMap = { [key: string]: string[] };

interface DataPanelProps {
  selectedPair: string;
  selectedTimeframe: string;
  onPairChange: (pair: string) => void;
  onTimeframeChange: (tf: string) => void;
}

export function DataPanel({
  selectedPair,
  selectedTimeframe,
  onPairChange,
  onTimeframeChange,
}: DataPanelProps) {
  const [pairs, setPairs] = useState<PairsMap>({});
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPairs()
      .then(setPairs)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedPair || !selectedTimeframe) return;
    
    setLoading(true);
    setError(null);
    getStats(selectedPair, selectedTimeframe)
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedPair, selectedTimeframe]);

  const availablePairs = Object.keys(pairs);
  const availableTimeframes = pairs[selectedPair] || [];

  return (
    <div className="panel">
      <h3>数据</h3>
      
      <div className="form-row">
        <label>交易对:</label>
        <select
          value={selectedPair}
          onChange={(e) => onPairChange(e.target.value)}
          disabled={availablePairs.length === 0}
        >
          <option value="">选择交易对...</option>
          {availablePairs.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="form-row">
        <label>时间周期:</label>
        <select
          value={selectedTimeframe}
          onChange={(e) => onTimeframeChange(e.target.value)}
          disabled={availableTimeframes.length === 0}
        >
          <option value="">选择时间周期...</option>
          {availableTimeframes.map((tf) => (
            <option key={tf} value={tf}>{tf}</option>
          ))}
        </select>
      </div>

      {loading && <p className="loading">加载统计信息...</p>}
      {error && <p className="error">{error}</p>}
      
      {stats && (
        <div className="stats">
          <div className="stat-row">
            <span>数据条数:</span>
            <span>{stats.count}</span>
          </div>
          <div className="stat-row">
            <span>起始时间:</span>
            <span>{stats.earliest_iso || '无'}</span>
          </div>
          <div className="stat-row">
            <span>结束时间:</span>
            <span>{stats.latest_iso || '无'}</span>
          </div>
        </div>
      )}
    </div>
  );
}
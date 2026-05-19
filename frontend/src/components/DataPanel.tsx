import { useState, useEffect } from 'react';
import { getStats, Stats, getPairs } from '../api';

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
  const [pairs, setPairs] = useState<Record<string, string[]>({});
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
      <h3>Data</h3>
      
      <div className="form-row">
        <label>Pair:</label>
        <select
          value={selectedPair}
          onChange={(e) => onPairChange(e.target.value)}
          disabled={availablePairs.length === 0}
        >
          <option value="">Select pair...</option>
          {availablePairs.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="form-row">
        <label>Timeframe:</label>
        <select
          value={selectedTimeframe}
          onChange={(e) => onTimeframeChange(e.target.value)}
          disabled={availableTimeframes.length === 0}
        >
          <option value="">Select timeframe...</option>
          {availableTimeframes.map((tf) => (
            <option key={tf} value={tf}>{tf}</option>
          ))}
        </select>
      </div>

      {loading && <p className="loading">Loading stats...</p>}
      {error && <p className="error">{error}</p>}
      
      {stats && (
        <div className="stats">
          <div className="stat-row">
            <span>Candles:</span>
            <span>{stats.count}</span>
          </div>
          <div className="stat-row">
            <span>Start:</span>
            <span>{stats.earliest_iso || 'N/A'}</span>
          </div>
          <div className="stat-row">
            <span>End:</span>
            <span>{stats.latest_iso || 'N/A'}</span>
          </div>
        </div>
      )}
    </div>
  );
}
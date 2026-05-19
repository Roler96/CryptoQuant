import { useState, useEffect } from 'react';
import { getStrategies, StrategyInfo, runBacktest, BacktestResult } from '../api';

interface StrategyPanelProps {
  selectedPair: string;
  selectedTimeframe: string;
  onBacktestComplete: (result: BacktestResult) => void;
}

export function StrategyPanel({
  selectedPair,
  selectedTimeframe,
  onBacktestComplete,
}: StrategyPanelProps) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState('');
  const [days, setDays] = useState(90);
  const [initialCash, setInitialCash] = useState(10000);
  const [commission, setCommission] = useState(0.001);
  const [slippage, setSlippage] = useState(0.0005);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStrategies()
      .then((s) => {
        setStrategies(s);
        if (s.length > 0) setSelectedStrategy(s[0].name);
      })
      .catch((e) => setError(e.message));
  }, []);

  const handleRunBacktest = async () => {
    if (!selectedPair || !selectedTimeframe || !selectedStrategy) {
      setError('Please select pair, timeframe, and strategy');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await runBacktest({
        strategy: selectedStrategy,
        pair: selectedPair,
        timeframe: selectedTimeframe,
        days,
        initial_cash: initialCash,
        commission,
        slippage,
      });
      onBacktestComplete(result);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel">
      <h3>Backtest</h3>

      <div className="form-row">
        <label>Strategy:</label>
        <select
          value={selectedStrategy}
          onChange={(e) => setSelectedStrategy(e.target.value)}
        >
          {strategies.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name} ({s.class_name})
            </option>
          ))}
        </select>
      </div>

      <div className="form-row">
        <label>Days:</label>
        <input
          type="number"
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value, 10))}
          min={1}
          max={3650}
        />
      </div>

      <div className="form-row">
        <label>Initial Cash:</label>
        <input
          type="number"
          value={initialCash}
          onChange={(e) => setInitialCash(parseFloat(e.target.value))}
          min={100}
          step={100}
        />
      </div>

      <div className="form-row">
        <label>Commission:</label>
        <input
          type="number"
          value={commission}
          onChange={(e) => setCommission(parseFloat(e.target.value))}
          min={0}
          max={0.01}
          step={0.0001}
        />
      </div>

      <div className="form-row">
        <label>Slippage:</label>
        <input
          type="number"
          value={slippage}
          onChange={(e) => setSlippage(parseFloat(e.target.value))}
          min={0}
          max={0.01}
          step={0.0001}
        />
      </div>

      {error && <p className="error">{error}</p>}

      <button
        onClick={handleRunBacktest}
        disabled={loading || !selectedPair || !selectedTimeframe}
        className="btn-primary"
      >
        {loading ? 'Running...' : 'Run Backtest'}
      </button>
    </div>
  );
}
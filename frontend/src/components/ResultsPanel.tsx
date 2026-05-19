import { BacktestResult, Trade } from '../api';
import { EquityChart } from './Chart';

interface ResultsPanelProps {
  result: BacktestResult | null;
}

export function ResultsPanel({ result }: ResultsPanelProps) {
  if (!result) {
    return (
      <div className="panel results-panel">
        <h3>Results</h3>
        <p className="placeholder">Run a backtest to see results</p>
      </div>
    );
  }

  if (result.error) {
    return (
      <div className="panel results-panel">
        <h3>Results</h3>
        <p className="error">{result.error}</p>
      </div>
    );
  }

  const formatPercent = (v: number) => `${(v * 100).toFixed(2)}%`;
  const formatPrice = (v: number) => `$${v.toFixed(2)}`;

  return (
    <div className="panel results-panel">
      <h3>Backtest Results</h3>
      
      <div className="metrics-grid">
        <div className="metric">
          <span className="metric-label">Strategy</span>
          <span className="metric-value">{result.strategy_name}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Pair</span>
          <span className="metric-value">{result.pair}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Timeframe</span>
          <span className="metric-value">{result.timeframe}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Initial</span>
          <span className="metric-value">{formatPrice(result.initial_value)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Final</span>
          <span className="metric-value">{formatPrice(result.final_value)}</span>
        </div>
        <div className="metric highlight">
          <span className="metric-label">Return</span>
          <span className={`metric-value ${result.total_return >= 0 ? 'positive' : 'negative'}`}>
            {formatPercent(result.total_return)}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Trades</span>
          <span className="metric-value">{result.total_trades}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Sharpe</span>
          <span className="metric-value">
            {result.sharpe_ratio?.toFixed(2) ?? 'N/A'}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Max DD</span>
          <span className="metric-value negative">
            {result.max_drawdown ? formatPercent(result.max_drawdown) : 'N/A'}
          </span>
        </div>
      </div>

      {result.equity_curve.length > 0 && (
        <div className="equity-section">
          <h4>Equity Curve</h4>
          <EquityChart
            timestamps={result.equity_timestamps}
            values={result.equity_curve}
            height={200}
          />
        </div>
      )}

      {result.trades.length > 0 && (
        <div className="trades-section">
          <h4>Trades ({result.trades.length})</h4>
          <div className="trades-table">
            <table>
              <thead>
                <tr>
                  <th>Side</th>
                  <th>Entry</th>
                  <th>Exit</th>
                  <th>PnL</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.slice(0, 20).map((trade: Trade, i: number) => (
                  <tr key={i}>
                    <td className={trade.side}>{trade.side}</td>
                    <td>${parseFloat(trade.entry_price).toFixed(2)}</td>
                    <td>${parseFloat(trade.exit_price).toFixed(2)}</td>
                    <td className={trade.pnl >= 0 ? 'positive' : 'negative'}>
                      {formatPercent(trade.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.trades.length > 20 && (
              <p className="table-note">Showing first 20 of {result.trades.length} trades</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
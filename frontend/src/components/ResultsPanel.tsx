import type { BacktestResult, Trade } from '../api';
import { EquityChart } from './Chart';

interface ResultsPanelProps {
  result: BacktestResult | null;
}

export function ResultsPanel({ result }: ResultsPanelProps) {
  if (!result) {
    return (
      <div className="panel results-panel">
        <h3>结果</h3>
        <p className="placeholder">运行回测以查看结果</p>
      </div>
    );
  }

  if (result.error) {
    return (
      <div className="panel results-panel">
        <h3>结果</h3>
        <p className="error">{result.error}</p>
      </div>
    );
  }

  const formatPercent = (v: number) => `${(v * 100).toFixed(2)}%`;
  const formatPrice = (v: number) => `$${v.toFixed(2)}`;

  return (
    <div className="panel results-panel">
      <h3>回测结果</h3>
      
      <div className="metrics-grid">
        <div className="metric">
          <span className="metric-label">策略</span>
          <span className="metric-value">{result.strategy_name}</span>
        </div>
        <div className="metric">
          <span className="metric-label">交易对</span>
          <span className="metric-value">{result.pair}</span>
        </div>
        <div className="metric">
          <span className="metric-label">时间周期</span>
          <span className="metric-value">{result.timeframe}</span>
        </div>
        <div className="metric">
          <span className="metric-label">初始资金</span>
          <span className="metric-value">{formatPrice(result.initial_value)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">最终资金</span>
          <span className="metric-value">{formatPrice(result.final_value)}</span>
        </div>
        <div className="metric highlight">
          <span className="metric-label">收益率</span>
          <span className={`metric-value ${result.total_return >= 0 ? 'positive' : 'negative'}`}>
            {formatPercent(result.total_return)}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">交易次数</span>
          <span className="metric-value">{result.total_trades}</span>
        </div>
        <div className="metric">
          <span className="metric-label">夏普比率</span>
          <span className="metric-value">
            {result.sharpe_ratio?.toFixed(2) ?? '无'}
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">最大回撤</span>
          <span className="metric-value negative">
            {result.max_drawdown ? formatPercent(result.max_drawdown) : '无'}
          </span>
        </div>
      </div>

      {result.equity_curve.length > 0 && (
        <div className="equity-section">
          <h4>资金曲线</h4>
          <EquityChart
            timestamps={result.equity_timestamps}
            values={result.equity_curve}
            height={200}
          />
        </div>
      )}

      {result.trades.length > 0 && (
        <div className="trades-section">
          <h4>交易记录 ({result.trades.length})</h4>
          <div className="trades-table">
            <table>
              <thead>
                <tr>
                  <th>方向</th>
                  <th>入场价</th>
                  <th>出场价</th>
                  <th>盈亏</th>
                </tr>
              </thead>
              <tbody>
                {result.trades.slice(0, 20).map((trade: Trade, i: number) => (
                  <tr key={i}>
                    <td className={trade.side}>{trade.side === 'long' ? '做多' : '做空'}</td>
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
              <p className="table-note">显示前 20 条交易记录，共 {result.trades.length} 条</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
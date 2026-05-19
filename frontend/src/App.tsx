import { useState, useEffect, useCallback } from 'react';
import { getCandles, Candle, BacktestResult } from './api';
import { CandlestickChart } from './components/Chart';
import { DataPanel } from './components/DataPanel';
import { StrategyPanel } from './components/StrategyPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { DownloadPanel } from './components/DownloadPanel';
import './App.css';

function App() {
  const [selectedPair, setSelectedPair] = useState('');
  const [selectedTimeframe, setSelectedTimeframe] = useState('');
  const [candles, setCandles] = useState<Candle[]>([]);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [loadingCandles, setLoadingCandles] = useState(false);
  const [candleError, setCandleError] = useState<string | null>(null);

  // Load candles when pair/timeframe changes
  const loadCandles = useCallback(async () => {
    if (!selectedPair || !selectedTimeframe) {
      setCandles([]);
      return;
    }

    setLoadingCandles(true);
    setCandleError(null);

    try {
      const data = await getCandles(selectedPair, selectedTimeframe, undefined, undefined, 1000);
      setCandles(data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setCandleError(msg);
      setCandles([]);
    } finally {
      setLoadingCandles(false);
    }
  }, [selectedPair, selectedTimeframe]);

  useEffect(() => {
    loadCandles();
  }, [loadCandles]);

  const handleBacktestComplete = (result: BacktestResult) => {
    setBacktestResult(result);
  };

  const handleDataUpdated = () => {
    loadCandles();
  };

  return (
    <div className="app">
      <header className="header">
        <h1>CryptoQuant</h1>
        <p className="subtitle">Quantitative Crypto Trading Platform</p>
      </header>

      <main className="main">
        <div className="sidebar">
          <DataPanel
            selectedPair={selectedPair}
            selectedTimeframe={selectedTimeframe}
            onPairChange={setSelectedPair}
            onTimeframeChange={setSelectedTimeframe}
          />
          <DownloadPanel
            selectedPair={selectedPair}
            selectedTimeframe={selectedTimeframe}
            onDataUpdated={handleDataUpdated}
          />
          <StrategyPanel
            selectedPair={selectedPair}
            selectedTimeframe={selectedTimeframe}
            onBacktestComplete={handleBacktestComplete}
          />
        </div>

        <div className="content">
          <div className="chart-section">
            {loadingCandles && (
              <div className="loading-overlay">
                <p>Loading candles...</p>
              </div>
            )}
            {candleError && (
              <div className="error-overlay">
                <p>{candleError}</p>
              </div>
            )}
            {!loadingCandles && !candleError && candles.length > 0 && (
              <CandlestickChart candles={candles} height={450} />
            )}
            {!loadingCandles && !candleError && candles.length === 0 && (
              <div className="placeholder-overlay">
                <p>Select a pair and timeframe to view chart</p>
              </div>
            )}
          </div>

          <ResultsPanel result={backtestResult} />
        </div>
      </main>
    </div>
  );
}

export default App;
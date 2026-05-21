import { useState, useEffect, useCallback, useRef } from 'react';
import { getCandles } from './api';
import type { Candle, BacktestResult } from './api';
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
  
  const loadedRangeRef = useRef<{ from: number; to: number } | null>(null);
  const debounceTimerRef = useRef<number | null>(null);
  const candlesMapRef = useRef<Map<number, Candle>>(new Map());

  const loadCandlesInRange = useCallback(async (from: number, to: number, forceReload = false) => {
    if (!selectedPair || !selectedTimeframe) return;

    const existingRange = loadedRangeRef.current;
    
    if (!forceReload && existingRange) {
      if (from >= existingRange.from && to <= existingRange.to) {
        return;
      }
    }

    setLoadingCandles(true);
    setCandleError(null);

    try {
      const fetchFrom = forceReload ? from : (existingRange ? Math.min(from, existingRange.from) : from);
      const fetchTo = forceReload ? to : (existingRange ? Math.max(to, existingRange.to) : to);
      
      const data = await getCandles(
        selectedPair, 
        selectedTimeframe, 
        fetchFrom, 
        fetchTo, 
        2000,
        'asc'
      );

      data.forEach((c) => {
        candlesMapRef.current.set(c.timestamp, c);
      });

      const allCandles = Array.from(candlesMapRef.current.values())
        .sort((a, b) => a.timestamp - b.timestamp);

      setCandles(allCandles);
      loadedRangeRef.current = { from: fetchFrom, to: fetchTo };
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setCandleError(msg);
    } finally {
      setLoadingCandles(false);
    }
  }, [selectedPair, selectedTimeframe]);

  const handleVisibleRangeChange = useCallback((range: { from: number; to: number } | null) => {
    if (!range) return;

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    debounceTimerRef.current = window.setTimeout(() => {
      loadCandlesInRange(range.from, range.to);
    }, 300);
  }, [loadCandlesInRange]);

  const loadInitialCandles = useCallback(async () => {
    if (!selectedPair || !selectedTimeframe) {
      setCandles([]);
      candlesMapRef.current.clear();
      loadedRangeRef.current = null;
      return;
    }

    candlesMapRef.current.clear();
    loadedRangeRef.current = null;

    setLoadingCandles(true);
    setCandleError(null);

    try {
      const data = await getCandles(selectedPair, selectedTimeframe, undefined, undefined, 1000, 'desc');
      
      data.forEach((c) => {
        candlesMapRef.current.set(c.timestamp, c);
      });
      
      const sortedData = data.sort((a, b) => a.timestamp - b.timestamp);
      
      setCandles(sortedData);
      
      if (sortedData.length > 0) {
        loadedRangeRef.current = {
          from: sortedData[0].timestamp,
          to: sortedData[sortedData.length - 1].timestamp,
        };
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setCandleError(msg);
      setCandles([]);
    } finally {
      setLoadingCandles(false);
    }
  }, [selectedPair, selectedTimeframe]);

  useEffect(() => {
    loadInitialCandles();
  }, [loadInitialCandles]);

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const handleBacktestComplete = (result: BacktestResult) => {
    setBacktestResult(result);
  };

  const handleDataUpdated = () => {
    candlesMapRef.current.clear();
    loadedRangeRef.current = null;
    loadInitialCandles();
  };

  const initialRange = candles.length > 0 
    ? { from: candles[0].timestamp, to: candles[candles.length - 1].timestamp }
    : undefined;

  return (
    <div className="app">
      <header className="header">
        <h1>CryptoQuant</h1>
        <p className="subtitle">量化加密货币交易平台</p>
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
                <p>加载行情数据...</p>
              </div>
            )}
            {candleError && (
              <div className="error-overlay">
                <p>{candleError}</p>
              </div>
            )}
            {!loadingCandles && !candleError && candles.length > 0 && (
              <CandlestickChart 
                candles={candles} 
                height={450} 
                onVisibleRangeChange={handleVisibleRangeChange}
                initialRange={initialRange}
              />
            )}
            {!loadingCandles && !candleError && candles.length === 0 && (
              <div className="placeholder-overlay">
                <p>选择交易对和时间周期以查看图表</p>
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
import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';
import type { IChartApi, IRange, Time } from 'lightweight-charts';
import type { Candle } from '../api';

interface ChartProps {
  candles: Candle[];
  height?: number;
  onVisibleRangeChange?: (range: { from: number; to: number } | null) => void;
  initialRange?: { from: number; to: number };
}

export function CandlestickChart({ candles, height = 400, onVisibleRangeChange, initialRange }: ChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<any>(null);
  const loadedDataRef = useRef<Map<number, Candle>>(new Map());
  const [isLoading, setIsLoading] = useState(true);

  const handleVisibleRangeChange = useCallback((range: IRange<Time> | null) => {
    if (!range || !onVisibleRangeChange) return;
    const from = typeof range.from === 'number' ? range.from * 1000 : 0;
    const to = typeof range.to === 'number' ? range.to * 1000 : 0;
    if (from > 0 && to > 0) {
      onVisibleRangeChange({ from, to });
    }
  }, [onVisibleRangeChange]);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1a1a2e' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#2b2b43' },
        horzLines: { color: '#2b2b43' },
      },
      width: chartContainerRef.current.clientWidth,
      height: height,
      rightPriceScale: {
        borderColor: '#2b2b43',
      },
      timeScale: {
        borderColor: '#2b2b43',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderDownColor: '#ef5350',
      borderUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      wickUpColor: '#26a69a',
    });

    seriesRef.current = candlestickSeries;

    if (onVisibleRangeChange) {
      chart.timeScale().subscribeVisibleTimeRangeChange(handleVisibleRangeChange);
    }

    setIsLoading(false);

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (onVisibleRangeChange) {
        chart.timeScale().unsubscribeVisibleTimeRangeChange(handleVisibleRangeChange);
      }
      chart.remove();
    };
  }, [height, handleVisibleRangeChange, onVisibleRangeChange]);

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;

    candles.forEach((c) => {
      loadedDataRef.current.set(c.timestamp, c);
    });

    const data = candles.map((c) => ({
      time: Math.floor(c.timestamp / 1000) as unknown as number,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    seriesRef.current.setData(data);

    if (initialRange && chartRef.current) {
      chartRef.current.timeScale().setVisibleRange({
        from: Math.floor(initialRange.from / 1000) as Time,
        to: Math.floor(initialRange.to / 1000) as Time,
      });
    } else {
      chartRef.current?.timeScale().fitContent();
    }
  }, [candles, initialRange]);

  if (isLoading && candles.length === 0) {
    return (
      <div
        style={{
          height: height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#1a1a2e',
          color: '#d1d4dc',
        }}
      >
        加载图表...
      </div>
    );
  }

  return <div ref={chartContainerRef} style={{ height: height }} />;
}

interface EquityChartProps {
  timestamps: number[];
  values: number[];
  height?: number;
}

export function EquityChart({ timestamps, values, height = 200 }: EquityChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current || timestamps.length === 0) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1a1a2e' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#2b2b43' },
        horzLines: { color: '#2b2b43' },
      },
      width: chartContainerRef.current.clientWidth,
      height: height,
      rightPriceScale: {
        borderColor: '#2b2b43',
      },
      timeScale: {
        borderColor: '#2b2b43',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    const lineSeries = chart.addSeries(LineSeries, {
      color: '#2962ff',
      lineWidth: 2,
    });

    const data = timestamps.map((ts, i) => ({
      time: Math.floor(ts / 1000) as unknown as number,
      value: values[i],
    }));

    lineSeries.setData(data);
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [timestamps, values, height]);

  return <div ref={chartContainerRef} style={{ height: height }} />;
}
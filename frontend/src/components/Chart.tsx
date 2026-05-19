import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, IChartApi } from 'lightweight-charts';
import { Candle } from '../api';

interface ChartProps {
  candles: Candle[];
  height?: number;
}

export function CandlestickChart({ candles, height = 400 }: ChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [isLoading, setIsLoading] = useState(true);

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

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderDownColor: '#ef5350',
      borderUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      wickUpColor: '#26a69a',
    });

    const data = candles.map((c) => ({
      time: Math.floor(c.timestamp / 1000) as unknown as number,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    candlestickSeries.setData(data);
    chart.timeScale().fitContent();
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
      chart.remove();
    };
  }, [candles, height]);

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
        Loading chart...
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

    const lineSeries = chart.addLineSeries({
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
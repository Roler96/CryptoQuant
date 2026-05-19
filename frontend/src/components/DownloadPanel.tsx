import { useState, useEffect } from 'react';
import { startDownload, getDownloadStatus, DownloadStatus } from '../api';

interface DownloadPanelProps {
  selectedPair: string;
  selectedTimeframe: string;
  onDataUpdated: () => void;
}

export function DownloadPanel({
  selectedPair,
  selectedTimeframe,
  onDataUpdated,
}: DownloadPanelProps) {
  const [days, setDays] = useState(365);
  const [sandbox, setSandbox] = useState(true);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<DownloadStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll status when task is running
  useEffect(() => {
    if (!taskId || !status) return;
    
    if (status.status === 'running') {
      const timer = setInterval(async () => {
        try {
          const newStatus = await getDownloadStatus(taskId);
          setStatus(newStatus);
          
          if (newStatus.status === 'completed') {
            onDataUpdated();
          }
        } catch {
          clearInterval(timer);
        }
      }, 2000);
      
      return () => clearInterval(timer);
    }
  }, [taskId, status, onDataUpdated]);

  const handleStartDownload = async () => {
    if (!selectedPair || !selectedTimeframe) {
      setError('Please select pair and timeframe');
      return;
    }

    setError(null);

    try {
      const result = await startDownload({
        pair: selectedPair,
        timeframe: selectedTimeframe,
        days,
        sandbox,
      });
      setTaskId(result.task_id);
      setStatus(result);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error';
      setError(msg);
    }
  };

  const isRunning = status?.status === 'running' || status?.status === 'pending';
  const isCompleted = status?.status === 'completed';
  const isFailed = status?.status === 'failed';

  return (
    <div className="panel download-panel">
      <h3>Download Data</h3>

      <div className="form-row">
        <label>Days:</label>
        <input
          type="number"
          value={days}
          onChange={(e) => setDays(parseInt(e.target.value, 10))}
          disabled={isRunning}
          min={1}
          max={3650}
        />
      </div>

      <div className="form-row checkbox">
        <label>
          <input
            type="checkbox"
            checked={sandbox}
            onChange={(e) => setSandbox(e.target.checked)}
            disabled={isRunning}
          />
          Sandbox mode
        </label>
      </div>

      {error && <p className="error">{error}</p>}

      {status && (
        <div className={`status status-${status.status}`}>
          <span className="status-badge">{status.status}</span>
          <span className="status-message">{status.message}</span>
          {status.progress && (
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{ width: `${status.progress}%` }}
              />
            </div>
          )}
        </div>
      )}

      {isCompleted && (
        <button onClick={() => { setTaskId(null); setStatus(null); }} className="btn-secondary">
          Clear
        </button>
      )}

      {!isRunning && !isCompleted && (
        <button
          onClick={handleStartDownload}
          disabled={!selectedPair || !selectedTimeframe}
          className="btn-primary"
        >
          Start Download
        </button>
      )}
    </div>
  );
}
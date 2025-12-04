import { useState, useEffect } from 'react';
import { PlayCircle, RefreshCw, FileText, CheckCircle, XCircle, AlertCircle, Loader2, Download } from 'lucide-react';
import axios from 'axios';
import './App.css';

function App() {
  const [searchDate, setSearchDate] = useState(new Date().toISOString().split('T')[0]); // Today
  const [maxEmails, setMaxEmails] = useState(100000); // Keep as fallback
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('Ready');
  const [results, setResults] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [statusFilter, setStatusFilter] = useState(null); // null = show all
  const [autoMarkPaid, setAutoMarkPaid] = useState(true); // Auto-mark matched invoices as paid
  const [startPage, setStartPage] = useState('');
  const [endPage, setEndPage] = useState('');

  // Poll status while reconciliation is running
  useEffect(() => {
    let interval;
    if (isRunning) {
      interval = setInterval(async () => {
        try {
          const response = await axios.get('/api/status');
          setProgress(response.data.progress);
          setStatusMessage(response.data.status_message);
          setIsRunning(response.data.is_running);

          if (!response.data.is_running && response.data.progress === 100) {
            loadResults();
          }
        } catch (error) {
          console.error('Error polling status:', error);
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isRunning]);

  // Load results on mount
  useEffect(() => {
    loadResults();
  }, []);

  const loadResults = async () => {
    try {
      const response = await axios.get('/api/results');
      setResults(response.data);
    } catch (error) {
      console.error('Error loading results:', error);
    }
  };

  const calculateDaysBack = () => {
    if (!searchDate) return 1;

    const selected = new Date(searchDate);
    const today = new Date();
    const diffTime = Math.abs(today - selected);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    return diffDays;
  };

  const startReconciliation = async () => {
    if (!searchDate) {
      alert('Please select a date');
      return;
    }

    const daysBack = calculateDaysBack();

    try {
      await axios.post('/api/reconcile', {
        max_emails: maxEmails,
        days_back: daysBack,
        auto_mark_paid: autoMarkPaid,
        start_page: parseInt(startPage) || 1,
        end_page: parseInt(endPage) || 100
      });
      setIsRunning(true);
      setProgress(0);
      setActiveTab('dashboard');
    } catch (error) {
      alert('Error starting reconciliation: ' + error.message);
    }
  };

  const clearData = async () => {
    if (!confirm('Are you sure you want to clear all data?')) return;

    try {
      await axios.delete('/api/clear');
      setResults(null);
      alert('Data cleared successfully');
    } catch (error) {
      alert('Error clearing data: ' + error.message);
    }
  };

  const downloadExcel = async () => {
    try {
      const response = await axios.get('/api/download-excel', {
        responseType: 'blob'
      });

      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `reconciliation_report_${new Date().getTime()}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      alert('Error downloading Excel: ' + error.message);
    }
  };

  const handleFilterClick = (filterType) => {
    setStatusFilter(filterType);
    setActiveTab('results');
  };

  const getFilteredResults = () => {
    if (!results?.results) return [];

    if (!statusFilter) return results.results;

    return results.results.filter(r => {
      switch (statusFilter) {
        case 'MATCHED':
          return r.status === 'MATCHED';
        case 'NOT_FOUND':
          return r.status === 'NOT_FOUND' || r.status === 'NOT_FOUND_IN_WARSOFT';
        case 'MISMATCH':
          return r.status === 'AMOUNT_MISMATCH' || r.status === 'UNMATCHED' || r.status === 'PARTIAL_MATCH';
        default:
          return true;
      }
    });
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'MATCHED': return '#10b981';
      case 'NOT_FOUND_IN_WARSOFT': return '#f59e0b';
      case 'AMOUNT_MISMATCH': return '#ef4444';
      default: return '#6b7280';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'MATCHED': return <CheckCircle size={16} />;
      case 'NOT_FOUND_IN_WARSOFT': return <AlertCircle size={16} />;
      case 'AMOUNT_MISMATCH': return <XCircle size={16} />;
      default: return <FileText size={16} />;
    }
  };

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-content">
          <div className="header-title">
            <FileText size={32} />
            <h1>Payment Reconciliation System</h1>
          </div>
          <div className="header-actions">
            <button onClick={downloadExcel} className="btn btn-success" disabled={!results?.results?.length}>
              <Download size={18} />
              Download Excel
            </button>
            <button onClick={clearData} className="btn btn-secondary">
              <RefreshCw size={18} />
              Clear Data
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="main-content">
        {/* Control Panel */}
        <div className="control-panel">
          <div className="control-section-grid">
            {/* Warsoft Page Range - LEFT SIDE */}
            <div className="page-range-container">
              <label>Matching invoice data from Warsoft Page {startPage}-{endPage}</label>
              <div className="page-range-inputs">
                <div className="input-group">
                  <label htmlFor="startPage">From:</label>
                  <input
                    id="startPage"
                    type="number"
                    value={startPage}
                    onChange={(e) => setStartPage(e.target.value)}
                    min="1"
                    disabled={isRunning}
                    className="page-input"
                    placeholder="Start page"
                  />
                </div>
                <div className="input-group">
                  <label htmlFor="endPage">To:</label>
                  <input
                    id="endPage"
                    type="number"
                    value={endPage}
                    onChange={(e) => setEndPage(e.target.value)}
                    min="1"
                    disabled={isRunning}
                    className="page-input"
                    placeholder="End page"
                  />
                </div>
              </div>
            </div>

            {/* Email Date Range - RIGHT SIDE */}
            <div className="date-range-container">
              <label htmlFor="searchDate">Email Date Range:</label>
              <div className="date-search-container">
                <input
                  id="searchDate"
                  type="date"
                  value={searchDate}
                  onChange={(e) => setSearchDate(e.target.value)}
                  max={new Date().toISOString().split('T')[0]}
                  disabled={isRunning}
                  className="date-input"
                />
                {searchDate && (
                  <span className="date-info-text">
                    Will search emails from {new Date(searchDate).toLocaleDateString()} to today ({calculateDaysBack()} day{calculateDaysBack() !== 1 ? 's' : ''})
                  </span>
                )}
              </div>
            </div>

          </div>

          {/* Auto-Mark Paid Toggle */}
          <div className="toggle-container">
            <label className="toggle-label">
              <input
                type="checkbox"
                checked={autoMarkPaid}
                onChange={(e) => setAutoMarkPaid(e.target.checked)}
                disabled={isRunning}
                className="toggle-checkbox"
              />
              <span className="toggle-text">
                Write matched invoices to Warsoft
              </span>
            </label>
          </div>

          <button
            onClick={startReconciliation}
            disabled={isRunning || !searchDate}
            className="btn btn-primary"
          >
            {isRunning ? (
              <>
                <Loader2 size={18} className="spinner" />
                Processing...
              </>
            ) : (
              <>
                <PlayCircle size={18} />
                Start Reconciliation
              </>
            )}
          </button>
        </div>

        {/* Progress Bar */}
        {isRunning && (
          <div className="progress-container">
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progress}%` }}></div>
            </div>
            <p className="progress-text">{statusMessage} ({progress}%)</p>
          </div>
        )}

        {/* Tabs */}
        <div className="tabs">
          <button
            className={`tab ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            Dashboard
          </button>
          <button
            className={`tab ${activeTab === 'results' ? 'active' : ''}`}
            onClick={() => setActiveTab('results')}
          >
            All Results
          </button>
        </div>

        {/* Tab Content */}
        <div className="tab-content">
          {/* Dashboard Tab */}
          {activeTab === 'dashboard' && (
            <div className="dashboard">
              {results?.summary ? (
                <>
                  <div className="stats-grid">
                    <div className="stat-card total" onClick={() => { setStatusFilter(null); setActiveTab('results'); }}>
                      <h3>Total Invoices</h3>
                      <p className="stat-number">{results.summary.total}</p>
                    </div>
                    <div className="stat-card matched" onClick={() => handleFilterClick('MATCHED')}>
                      <CheckCircle size={24} />
                      <h3>Matched</h3>
                      <p className="stat-number">{results.summary.matched}</p>
                    </div>
                    <div className="stat-card not-found" onClick={() => handleFilterClick('NOT_FOUND')}>
                      <AlertCircle size={24} />
                      <h3>Not Found in Warsoft</h3>
                      <p className="stat-number">{results.summary.not_found}</p>
                    </div>
                    <div className="stat-card mismatch" onClick={() => handleFilterClick('MISMATCH')}>
                      <XCircle size={24} />
                      <h3>Amount Mismatch</h3>
                      <p className="stat-number">{results.summary.amount_mismatch}</p>
                    </div>
                  </div>

                  <div className="recent-results">
                    <h2>Recent Results</h2>
                    <div className="table-container">
                      <table>
                        <thead>
                          <tr>
                            <th>Invoice Number</th>
                            <th>Gross Amount</th>
                            <th>TDS</th>
                            <th>Bank Reference</th>
                            <th>Status</th>
                            <th>Notes</th>
                          </tr>
                        </thead>
                        <tbody>
                          {results.results.slice(0, 10).map((result) => (
                            <tr key={result.id}>
                              <td className="invoice-number">{result.invoice_number}</td>
                              <td className="amount">₹{parseFloat(result.gross_amount || 0).toFixed(2)}</td>
                              <td className="amount">₹{parseFloat(result.tds || 0).toFixed(2)}</td>
                              <td>{result.bank_reference || '-'}</td>
                              <td>
                                <span
                                  className="status-badge"
                                  style={{ backgroundColor: getStatusColor(result.status) }}
                                >
                                  {getStatusIcon(result.status)}
                                  {result.status.replace(/_/g, ' ')}
                                </span>
                              </td>
                              <td className="notes">{result.notes || '-'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : (
                <div className="empty-state">
                  <FileText size={64} />
                  <h2>No Results Yet</h2>
                  <p>Start a reconciliation to see results here</p>
                </div>
              )}
            </div>
          )}

          {/* All Results Tab */}
          {activeTab === 'results' && (
            <div className="all-results">
              {statusFilter && (
                <div className="filter-banner">
                  <span>
                    Showing: <strong>{statusFilter.replace('_', ' ')}</strong>
                  </span>
                  <button onClick={() => setStatusFilter(null)} className="btn-clear-filter">
                    Clear Filter
                  </button>
                </div>
              )}
              {getFilteredResults().length > 0 ? (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Invoice Number</th>
                        <th>Gross Amount</th>
                        <th>TDS</th>
                        <th>Bank Reference</th>
                        <th>Status</th>
                        <th>Notes</th>
                        <th>Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getFilteredResults().map((result) => (
                        <tr key={result.id}>
                          <td className="invoice-number">{result.invoice_number}</td>
                          <td className="amount">₹{parseFloat(result.gross_amount || 0).toFixed(2)}</td>
                          <td className="amount">₹{parseFloat(result.tds || 0).toFixed(2)}</td>
                          <td>{result.bank_reference || '-'}</td>
                          <td>
                            <span
                              className="status-badge"
                              style={{ backgroundColor: getStatusColor(result.status) }}
                            >
                              {getStatusIcon(result.status)}
                              {result.status.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className="notes">{result.notes || '-'}</td>
                          <td>{result.reconciliation_date ? new Date(result.reconciliation_date).toLocaleDateString() : '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty-state">
                  <FileText size={64} />
                  <h2>No Results Available</h2>
                  <p>Run a reconciliation first</p>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
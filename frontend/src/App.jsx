import { useState, useEffect } from 'react';
import { PlayCircle, RefreshCw, FileText, CheckCircle, XCircle, AlertCircle, Loader2, Download } from 'lucide-react';
import axios from 'axios';
import './App.css';

function App() {
  const [searchDate, setSearchDate] = useState(new Date().toISOString().split('T')[0]); // Today
  const [maxEmails, setMaxEmails] = useState(100); // Keep as fallback
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState('Ready');
  const [results, setResults] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [statusFilter, setStatusFilter] = useState(null); // null = show all
  const [autoMarkPaid, setAutoMarkPaid] = useState(true); // Auto-mark matched invoices as paid

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
        auto_mark_paid: autoMarkPaid
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
          return r.status === 'NOT_FOUND' || r.status === 'NOT_FOUND_IN_ZOHO';
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
      case 'NOT_FOUND_IN_ZOHO': return '#f59e0b';
      case 'AMOUNT_MISMATCH': return '#ef4444';
      default: return '#6b7280';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'MATCHED': return <CheckCircle size={16} />;
      case 'NOT_FOUND_IN_ZOHO': return <AlertCircle size={16} />;
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
          <div className="control-section">
            <label htmlFor="searchDate">Select Date to Search Emails:</label>
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
                  Auto-mark matched invoices as PAID in Zoho
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
                      <h3>Not Found in Zoho</h3>
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
                            <th>Payment Amount</th>
                            <th>Bank Name</th>
                            <th>Status</th>
                            <th>Zoho Invoice</th>
                            <th>Notes</th>
                          </tr>
                        </thead>
                        <tbody>
                          {results.results.slice(0, 10).map((result) => (
                            <tr key={result.id}>
                              <td className="invoice-number">{result.invoice_number}</td>
                              <td className="amount">₹{parseFloat(result.payment_amount || 0).toFixed(2)}</td>
                              <td>{result.bank_name || '-'}</td>
                              <td>
                                <span
                                  className="status-badge"
                                  style={{ backgroundColor: getStatusColor(result.status) }}
                                >
                                  {getStatusIcon(result.status)}
                                  {result.status.replace(/_/g, ' ')}
                                </span>
                              </td>
                              <td>{result.zoho_invoice_number || '-'}</td>
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
                        <th>Payment Amount</th>
                        <th>Bank Name</th>
                        <th>Status</th>
                        <th>Zoho Invoice</th>
                        <th>Zoho Total</th>
                        <th>Difference</th>
                        <th>Notes</th>
                        <th>Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getFilteredResults().map((result) => (
                        <tr key={result.id}>
                          <td className="invoice-number">{result.invoice_number}</td>
                          <td className="amount">₹{parseFloat(result.payment_amount || 0).toFixed(2)}</td>
                          <td>{result.bank_name || '-'}</td>
                          <td>
                            <span
                              className="status-badge"
                              style={{ backgroundColor: getStatusColor(result.status) }}
                            >
                              {getStatusIcon(result.status)}
                              {result.status.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td>{result.zoho_invoice_number || '-'}</td>
                          <td className="amount">
                            {result.zoho_total ? `₹${parseFloat(result.zoho_total).toFixed(2)}` : '-'}
                          </td>
                          <td className="amount">
                            {result.amount_difference ? `₹${Math.abs(parseFloat(result.amount_difference)).toFixed(2)}` : '-'}
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
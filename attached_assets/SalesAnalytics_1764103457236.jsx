import { useState, useEffect } from 'react';

function SalesAnalytics() {
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(false);
  
  // Pending filters (not applied yet)
  const [pendingStores, setPendingStores] = useState([]);
  const [pendingDateRange, setPendingDateRange] = useState('single');
  const [pendingFilters, setPendingFilters] = useState({
    startDate: '2025-11-23',
    endDate: '2025-11-23'
  });
  const [pendingAggregate, setPendingAggregate] = useState(false);
  
  // Applied filters (active)
  const [selectedStores, setSelectedStores] = useState([]);
  const [dateRange, setDateRange] = useState('single');
  const [filters, setFilters] = useState({
    startDate: '2025-11-23',
    endDate: '2025-11-23'
  });
  const [aggregateData, setAggregateData] = useState(false);
  
  // UI state
  const [storesExpanded, setStoresExpanded] = useState(false);
  const [selectedReport, setSelectedReport] = useState('dailyTotalSales');
  const [selectedTransaction, setSelectedTransaction] = useState(null);
  const [transactionDetails, setTransactionDetails] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const [reports, setReports] = useState({
    storeSummary: null,
    fuelDispensers: [],
    loyaltyDetails: [],
    loyaltyOverview: null,
    transactionLineItems: [],
    fuelByGrade: [],
    aggregatedItems: [],
    dailyFuelSales: null,
    dailyTotalSales: null,
    departmentSales: [],
    transactionsOverview: [],
    unknownItems: []
  });

  useEffect(() => {
    loadLocations();
  }, []);

  // Load report when filters change or report selection changes
  useEffect(() => {
    if (!loading && filters.startDate) {
      loadCurrentReport();
    }
  }, [loading, filters.startDate, filters.endDate, dateRange, aggregateData, selectedReport, selectedStores.length]);

  const loadLocations = async () => {
    try {
      const response = await fetch('/api/admin/locations');
      const data = await response.json();
      setLocations(data);
    } catch (error) {
      console.log('Error loading locations:', error);
    } finally {
      setLoading(false);
    }
  };

  const setDateRangeShortcut = (type) => {
    const today = new Date();
    let startDate, endDate;

    switch (type) {
      case 'today':
        startDate = endDate = today.toISOString().split('T')[0];
        setPendingDateRange('single');
        break;
      case 'last7':
        endDate = today.toISOString().split('T')[0];
        const last7 = new Date(today);
        last7.setDate(last7.getDate() - 6);
        startDate = last7.toISOString().split('T')[0];
        setPendingDateRange('range');
        break;
      case 'last30':
        endDate = today.toISOString().split('T')[0];
        const last30 = new Date(today);
        last30.setDate(last30.getDate() - 29);
        startDate = last30.toISOString().split('T')[0];
        setPendingDateRange('range');
        break;
      default:
        return;
    }

    setPendingFilters({ startDate, endDate });
  };

  const applyFilters = () => {
    setDateRange(pendingDateRange);
    setFilters(pendingFilters);
    setSelectedStores(pendingStores);
    setAggregateData(pendingAggregate);
  };

  const loadCurrentReport = async () => {
    setDataLoading(true);
    
    const queryParams = new URLSearchParams();
    if (selectedStores.length > 0) {
      queryParams.append('pdiStoreNumber', selectedStores.join(','));
    }
    
    if (dateRange === 'single') {
      queryParams.append('businessDate', filters.startDate);
    } else {
      queryParams.append('startDate', filters.startDate);
      if (filters.endDate) {
        queryParams.append('endDate', filters.endDate);
      }
    }
    
    queryParams.append('aggregate', aggregateData ? 'true' : 'false');
    
    const queryString = queryParams.toString();

    try {
      let data = null;
      
      // Only load the currently selected report
      switch (selectedReport) {
        case 'dailyTotalSales':
          data = await fetch(`/api/sales/reports/daily-total-sales?${queryString}`).then(r => r.ok ? r.json() : null);
          setReports(prev => ({ ...prev, dailyTotalSales: data }));
          break;
        case 'dailyFuelSales':
          data = await fetch(`/api/sales/reports/daily-fuel-sales?${queryString}`).then(r => r.ok ? r.json() : null);
          setReports(prev => ({ ...prev, dailyFuelSales: data }));
          break;
        case 'fuelByGrade':
          data = await fetch(`/api/sales/reports/fuel-by-grade?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, fuelByGrade: data }));
          break;
        case 'departmentSales':
          data = await fetch(`/api/sales/reports/department-sales?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, departmentSales: data }));
          break;
        case 'aggregatedItems':
          data = await fetch(`/api/sales/reports/aggregated-items?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, aggregatedItems: data }));
          break;
        case 'unknownItems':
          data = await fetch(`/api/sales/reports/unknown-items?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, unknownItems: data }));
          break;
        case 'storeSummary':
          data = await fetch(`/api/sales/reports/store-summary?${queryString}`).then(r => r.ok ? r.json() : null);
          setReports(prev => ({ ...prev, storeSummary: data }));
          break;
        case 'fuelDispensers':
          data = await fetch(`/api/sales/reports/fuel-dispensers?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, fuelDispensers: data }));
          break;
        case 'transactionsOverview':
          data = await fetch(`/api/sales/transactions?${queryString}&limit=100`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, transactionsOverview: data }));
          break;
        case 'transactionLineItems':
          data = await fetch(`/api/sales/reports/transaction-line-items?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, transactionLineItems: data }));
          break;
        case 'loyaltyDetails':
          data = await fetch(`/api/sales/reports/loyalty-details?${queryString}`).then(r => r.ok ? r.json() : []);
          setReports(prev => ({ ...prev, loyaltyDetails: data }));
          break;
        case 'loyaltyOverview':
          data = await fetch(`/api/sales/reports/loyalty-overview?${queryString}`).then(r => r.ok ? r.json() : null);
          setReports(prev => ({ ...prev, loyaltyOverview: data }));
          break;
      }
    } catch (error) {
      console.log('Error loading report:', error);
    } finally {
      setDataLoading(false);
    }
  };

  const toggleStore = (pdiStoreNumber) => {
    setPendingStores(prev => 
      prev.includes(pdiStoreNumber)
        ? prev.filter(s => s !== pdiStoreNumber)
        : [...prev, pdiStoreNumber]
    );
  };

  const loadTransactionDetails = async (transaction) => {
    setSelectedTransaction(transaction);
    setDetailsLoading(true);
    setTransactionDetails(null);
    
    try {
      const queryParams = new URLSearchParams({
        transactionId: transaction.transactionId,
        businessDate: transaction.businessDate
      });
      
      const response = await fetch(`/api/sales/transaction-details?${queryParams}`);
      if (response.ok) {
        const data = await response.json();
        setTransactionDetails(data);
      }
    } catch (error) {
      console.log('Error loading transaction details:', error);
    } finally {
      setDetailsLoading(false);
    }
  };

  const closeTransactionModal = () => {
    setSelectedTransaction(null);
    setTransactionDetails(null);
  };

  if (loading) {
    return (
      <div className="section-header">
        <h2>Sales Analytics</h2>
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <>
      <div className="section-header">
        <h2>Sales Analytics</h2>
        <p>Comprehensive sales reporting and analytics dashboard</p>
      </div>

      {/* Filters Card */}
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        marginBottom: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Filters</h3>
        
        {/* Report Selection Dropdown */}
        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: '500' }}>
            Select Report
          </label>
          <select
            value={selectedReport}
            onChange={(e) => setSelectedReport(e.target.value)}
            style={{
              width: '100%',
              padding: '10px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              background: 'var(--background)',
              color: 'var(--text-primary)',
              fontSize: '0.9rem',
              cursor: 'pointer'
            }}
          >
            <option value="dailyTotalSales">Daily Total Sales</option>
            <option value="dailyFuelSales">Daily Fuel Sales</option>
            <option value="fuelByGrade">Fuel by Grade</option>
            <option value="departmentSales">Department Sales</option>
            <option value="aggregatedItems">Aggregated Items</option>
            <option value="unknownItems">Unknown Items</option>
            <option value="storeSummary">Store Summary</option>
            <option value="fuelDispensers">Fuel Dispensers</option>
            <option value="transactionsOverview">Transactions Overview</option>
            <option value="transactionLineItems">Transaction Line Items</option>
            <option value="loyaltyDetails">Loyalty Details</option>
            <option value="loyaltyOverview">Loyalty Overview</option>
          </select>
        </div>

        {/* Date Range Shortcuts */}
        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: '500' }}>
            Date Range
          </label>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '15px' }}>
            <button
              onClick={() => setDateRangeShortcut('today')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--background)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.2s'
              }}
            >
              Today
            </button>
            <button
              onClick={() => setDateRangeShortcut('last7')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--background)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.2s'
              }}
            >
              Last 7 Days
            </button>
            <button
              onClick={() => setDateRangeShortcut('last30')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--background)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.2s'
              }}
            >
              Last 30 Days
            </button>
            <button
              onClick={() => setPendingDateRange('custom')}
              style={{
                padding: '8px 16px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--background)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
                transition: 'all 0.2s'
              }}
            >
              Custom Range
            </button>
          </div>

          {/* Date Inputs */}
          <div style={{ display: 'grid', gridTemplateColumns: pendingDateRange === 'custom' || pendingDateRange === 'range' ? '1fr 1fr' : '1fr', gap: '15px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '0.85rem' }}>
                {pendingDateRange === 'custom' || pendingDateRange === 'range' ? 'Start Date' : 'Date'}
              </label>
              <input
                type="date"
                value={pendingFilters.startDate}
                onChange={(e) => setPendingFilters(prev => ({ ...prev, startDate: e.target.value }))}
                style={{
                  width: '100%',
                  padding: '8px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  background: 'var(--background)',
                  color: 'var(--text-primary)'
                }}
              />
            </div>
            {(pendingDateRange === 'custom' || pendingDateRange === 'range') && (
              <div>
                <label style={{ display: 'block', marginBottom: '5px', fontSize: '0.85rem' }}>End Date</label>
                <input
                  type="date"
                  value={pendingFilters.endDate}
                  onChange={(e) => setPendingFilters(prev => ({ ...prev, endDate: e.target.value }))}
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '6px',
                    border: '1px solid var(--border)',
                    background: 'var(--background)',
                    color: 'var(--text-primary)'
                  }}
                />
              </div>
            )}
          </div>
        </div>

        {/* Collapsible Store Selection */}
        <div>
          <button
            onClick={() => setStoresExpanded(!storesExpanded)}
            style={{
              width: '100%',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '10px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              background: 'var(--background)',
              color: 'var(--text-primary)',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: '500',
              marginBottom: '10px'
            }}
          >
            <span>Stores ({pendingStores.length > 0 ? `${pendingStores.length} selected` : 'All'})</span>
            <span style={{ transform: storesExpanded ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>▼</span>
          </button>
          
          {storesExpanded && (
            <>
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', 
                gap: '8px',
                maxHeight: '300px',
                overflowY: 'auto',
                padding: '10px',
                background: 'var(--background)',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                marginBottom: '10px'
              }}>
                {locations.map(loc => (
                  <label
                    key={loc.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '6px',
                      cursor: 'pointer',
                      fontSize: '0.85rem',
                      borderRadius: '4px',
                      transition: 'background 0.2s'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.background = 'var(--surface)'}
                    onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                  >
                    <input
                      type="checkbox"
                      checked={pendingStores.includes(loc.pdiStoreNumber)}
                      onChange={() => toggleStore(loc.pdiStoreNumber)}
                      style={{ cursor: 'pointer' }}
                    />
                    <span>{loc.locationName} ({loc.pdiStoreNumber})</span>
                  </label>
                ))}
              </div>
              {pendingStores.length > 0 && (
                <button
                  onClick={() => setPendingStores([])}
                  style={{
                    marginBottom: '10px',
                    padding: '6px 12px',
                    borderRadius: '6px',
                    border: '1px solid var(--border)',
                    background: 'var(--background)',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    fontSize: '0.85rem'
                  }}
                >
                  Clear Selection
                </button>
              )}
            </>
          )}
        </div>

        {/* Aggregation Toggle - only show for date ranges */}
        {(pendingDateRange === 'range' || pendingDateRange === 'custom') && (
          <div style={{ marginTop: '20px' }}>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px',
                cursor: 'pointer',
                fontSize: '0.9rem',
                background: 'var(--background)',
                borderRadius: '6px',
                border: '1px solid var(--border)'
              }}
            >
              <input
                type="checkbox"
                checked={pendingAggregate}
                onChange={(e) => setPendingAggregate(e.target.checked)}
                style={{ cursor: 'pointer' }}
              />
              <span>Aggregate data across dates</span>
              <span
                title="Checked: Combine all dates into one summary total&#10;Unchecked: Show separate data for each date&#10;&#10;Example with 3-day range:&#10;• Aggregated: One row with total across all 3 days&#10;• Daily: Three rows, one for each day"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: '16px',
                  height: '16px',
                  borderRadius: '50%',
                  background: 'var(--primary)',
                  color: 'white',
                  fontSize: '0.7rem',
                  fontWeight: 'bold',
                  cursor: 'help',
                  marginLeft: 'auto'
                }}
              >
                ℹ
              </span>
            </label>
          </div>
        )}

        {/* Apply Filters Button */}
        <button
          onClick={applyFilters}
          disabled={dataLoading}
          style={{
            width: '100%',
            padding: '12px',
            borderRadius: '6px',
            border: 'none',
            background: dataLoading ? 'var(--border)' : 'var(--primary)',
            color: 'white',
            cursor: dataLoading ? 'not-allowed' : 'pointer',
            fontSize: '1rem',
            fontWeight: '600',
            marginTop: '15px',
            transition: 'all 0.2s'
          }}
        >
          {dataLoading ? 'Loading...' : 'Apply Filters'}
        </button>
      </div>

      {dataLoading && (
        <div style={{
          background: 'var(--surface)',
          borderRadius: '12px',
          padding: '40px',
          textAlign: 'center',
          border: '1px solid var(--border)',
          marginBottom: '20px'
        }}>
          <p style={{ fontSize: '1.1rem', color: 'var(--text-secondary)' }}>Loading all reports...</p>
        </div>
      )}

      {/* Reports Container */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {/* Daily Total Sales */}
        {selectedReport === 'dailyTotalSales' && reports.dailyTotalSales && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Daily Total Sales</h3>
            {Array.isArray(reports.dailyTotalSales) && reports.dailyTotalSales[0]?.businessDate ? (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                      <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Fuel Sales</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Merch Sales</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Total Sales</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.dailyTotalSales.map((row, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '12px' }}>{new Date(row.businessDate).toLocaleDateString()}</td>
                        <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(row.fuelAmount).toFixed(2)}</td>
                        <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(row.merchAmount).toFixed(2)}</td>
                        <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: 'var(--primary)' }}>${parseFloat(row.totalAmount).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '15px' }}>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Fuel Sales</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>${reports.dailyTotalSales.fuelAmount.toFixed(2)}</div>
                </div>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Merchandise Sales</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>${reports.dailyTotalSales.merchAmount.toFixed(2)}</div>
                </div>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Total Sales</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600', color: 'var(--primary)' }}>${reports.dailyTotalSales.totalAmount.toFixed(2)}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Daily Fuel Sales */}
        {selectedReport === 'dailyFuelSales' && reports.dailyFuelSales && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Daily Fuel Sales</h3>
            {Array.isArray(reports.dailyFuelSales) && reports.dailyFuelSales[0]?.businessDate ? (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                      <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Volume (gal)</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Amount</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Discount</th>
                      <th style={{ padding: '12px', textAlign: 'right' }}>Net Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.dailyFuelSales.map((row, idx) => (
                      <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '12px' }}>{new Date(row.businessDate).toLocaleDateString()}</td>
                        <td style={{ padding: '12px', textAlign: 'right' }}>{parseFloat(row.totalVolume).toFixed(2)}</td>
                        <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(row.totalAmount).toFixed(2)}</td>
                        <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(row.totalDiscount).toFixed(2)}</td>
                        <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: 'var(--primary)' }}>${parseFloat(row.netAmount).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '15px' }}>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Total Volume</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>{reports.dailyFuelSales.totalVolume.toFixed(2)} gal</div>
                </div>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Total Amount</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>${reports.dailyFuelSales.totalAmount.toFixed(2)}</div>
                </div>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Total Discount</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>${reports.dailyFuelSales.totalDiscount.toFixed(2)}</div>
                </div>
                <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Net Amount</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: '600', color: 'var(--primary)' }}>${reports.dailyFuelSales.netAmount.toFixed(2)}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Fuel by Grade */}
        {selectedReport === 'fuelByGrade' && reports.fuelByGrade.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Fuel by Grade ({reports.fuelByGrade.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    {reports.fuelByGrade[0]?.businessDate && (
                      <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                    )}
                    <th style={{ padding: '12px', textAlign: 'left' }}>Grade ID</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Grade Name</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Volume (gal)</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Amount</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Discount</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.fuelByGrade.map((grade, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                      {grade.businessDate && (
                        <td style={{ padding: '12px' }}>{new Date(grade.businessDate).toLocaleDateString()}</td>
                      )}
                      <td style={{ padding: '12px' }}>{grade.gradeId}</td>
                      <td style={{ padding: '12px' }}>{grade.gradeName}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{parseFloat(grade.volume).toFixed(3)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(grade.amount).toFixed(2)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(grade.discountAmount).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Department Sales */}
        {selectedReport === 'departmentSales' && reports.departmentSales.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Department Sales ({reports.departmentSales.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    {reports.departmentSales[0]?.businessDate && (
                      <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                    )}
                    <th style={{ padding: '12px', textAlign: 'left' }}>Dept Code</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Department Name</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Quantity</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Sales Amount</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Transactions</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.departmentSales.map((dept, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                      {dept.businessDate && (
                        <td style={{ padding: '12px' }}>{new Date(dept.businessDate).toLocaleDateString()}</td>
                      )}
                      <td style={{ padding: '12px' }}>{dept.departmentCode}</td>
                      <td style={{ padding: '12px' }}>{dept.departmentName}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{dept.quantity.toFixed(2)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${dept.salesAmount.toFixed(2)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{dept.transactionCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Aggregated Items */}
        {selectedReport === 'aggregatedItems' && reports.aggregatedItems.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Top Items Sold ({reports.aggregatedItems.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    {reports.aggregatedItems[0]?.businessDate && (
                      <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                    )}
                    <th style={{ padding: '12px', textAlign: 'left' }}>UPC</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Description</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Quantity</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Sales Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.aggregatedItems.slice(0, 50).map((item, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                      {item.businessDate && (
                        <td style={{ padding: '12px' }}>{new Date(item.businessDate).toLocaleDateString()}</td>
                      )}
                      <td style={{ padding: '12px' }}>{item.upc}</td>
                      <td style={{ padding: '12px' }}>{item.description}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{parseFloat(item.quantity).toFixed(2)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(item.salesAmount).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Unknown Items */}
        {selectedReport === 'unknownItems' && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>
              Unknown Items ({reports.unknownItems.length})
            </h3>
            {reports.unknownItems.length === 0 ? (
              <div style={{
                background: 'var(--background)',
                borderRadius: '8px',
                padding: '30px',
                textAlign: 'center',
                color: 'var(--text-secondary)'
              }}>
                <p style={{ fontSize: '1.1rem', marginBottom: '10px' }}>✓ All scanned items are in the pricebook!</p>
                <p style={{ fontSize: '0.9rem' }}>No unknown or missing items found for the selected date range.</p>
              </div>
            ) : (
              <>
                <div style={{
                  background: '#fff3cd',
                  color: '#856404',
                  border: '1px solid #ffeeba',
                  borderRadius: '8px',
                  padding: '15px',
                  marginBottom: '20px',
                  fontSize: '0.95rem'
                }}>
                  <strong>⚠️ Warning:</strong> The following items were scanned and sold but are NOT in your pricebook database. 
                  This may indicate data entry issues, new products, or pricing inconsistencies.
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                        <th style={{ padding: '12px', textAlign: 'left' }}>Store</th>
                        <th style={{ padding: '12px', textAlign: 'left' }}>UPC</th>
                        <th style={{ padding: '12px', textAlign: 'left' }}>Description</th>
                        <th style={{ padding: '12px', textAlign: 'right' }}>Times Sold</th>
                        <th style={{ padding: '12px', textAlign: 'right' }}>Total Qty</th>
                        <th style={{ padding: '12px', textAlign: 'right' }}>Total Revenue</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reports.unknownItems.map((item, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '12px' }}>
                            <div style={{ fontWeight: '500' }}>{item.storeName}</div>
                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>#{item.pdiStoreNumber}</div>
                          </td>
                          <td style={{ padding: '12px', fontFamily: 'monospace' }}>{item.upc}</td>
                          <td style={{ padding: '12px' }}>{item.description}</td>
                          <td style={{ padding: '12px', textAlign: 'right' }}>{item.timesSold}</td>
                          <td style={{ padding: '12px', textAlign: 'right' }}>{item.totalQuantity.toFixed(2)}</td>
                          <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600' }}>
                            ${item.totalRevenue.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{
                  marginTop: '20px',
                  padding: '15px',
                  background: 'var(--background)',
                  borderRadius: '8px',
                  fontSize: '0.9rem',
                  color: 'var(--text-secondary)'
                }}>
                  <strong>💡 Next Steps:</strong> Review these items and add them to your pricebook to ensure accurate pricing, 
                  inventory tracking, and loyalty points calculation.
                </div>
              </>
            )}
          </div>
        )}

        {/* Store Summary */}
        {selectedReport === 'storeSummary' && reports.storeSummary && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Store Summary</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '15px' }}>
              <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Voids</div>
                <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>{reports.storeSummary.voidCount}</div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '5px' }}>
                  ${(reports.storeSummary.voidAmount || 0).toFixed(2)}
                </div>
              </div>
              <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>No Sales</div>
                <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>{reports.storeSummary.noSaleCount}</div>
              </div>
              <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Error Corrects</div>
                <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>{reports.storeSummary.errorCorrectCount}</div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '5px' }}>
                  ${(reports.storeSummary.errorCorrectAmount || 0).toFixed(2)}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Fuel Dispensers */}
        {selectedReport === 'fuelDispensers' && reports.fuelDispensers.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Fuel Dispensers ({reports.fuelDispensers.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Pump #</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Count</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Volume (gal)</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.fuelDispensers.map((disp, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '12px' }}>{disp.pumpNumber}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{disp.count}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{disp.volume.toFixed(3)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${disp.amount.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Transactions Overview */}
        {selectedReport === 'transactionsOverview' && reports.transactionsOverview.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Transactions Overview ({reports.transactionsOverview.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Transaction ID</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Date/Time</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Fuel</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Merch</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.transactionsOverview.slice(0, 50).map((tx, idx) => (
                    <tr 
                      key={idx} 
                      onClick={() => loadTransactionDetails(tx)}
                      style={{ 
                        borderBottom: '1px solid var(--border)',
                        cursor: 'pointer',
                        transition: 'background 0.2s'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.background = 'var(--background)'}
                      onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '12px' }}>{tx.transactionId}</td>
                      <td style={{ padding: '12px' }}>{new Date(tx.transactionDateTime).toLocaleString()}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(tx.fuelAmount).toFixed(2)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(tx.merchAmount).toFixed(2)}</td>
                      <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600' }}>${parseFloat(tx.totalAmount).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Transaction Line Items */}
        {selectedReport === 'transactionLineItems' && reports.transactionLineItems.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Transaction Line Items ({reports.transactionLineItems.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Transaction ID</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Type</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>UPC/Pump</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Description</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Quantity</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.transactionLineItems.slice(0, 100).map((item, idx) => (
                    <tr 
                      key={idx} 
                      onClick={() => {
                        // Find the transaction for this line item
                        const tx = reports.transactionsOverview.find(t => t.transactionId === item.posTransactionId);
                        if (tx) {
                          loadTransactionDetails(tx);
                        }
                      }}
                      style={{ 
                        borderBottom: '1px solid var(--border)',
                        cursor: 'pointer',
                        transition: 'background 0.2s'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.background = 'var(--background)'}
                      onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                    >
                      <td style={{ padding: '12px' }}>{item.posTransactionId}</td>
                      <td style={{ padding: '12px' }}>{item.itemType}</td>
                      <td style={{ padding: '12px' }}>{item.upc || item.pumpNumber || '-'}</td>
                      <td style={{ padding: '12px' }}>{item.description}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>{parseFloat(item.quantity).toFixed(3)}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(item.amount).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Loyalty Details */}
        {selectedReport === 'loyaltyDetails' && reports.loyaltyDetails.length > 0 && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Loyalty Details ({reports.loyaltyDetails.length})</h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Transaction ID</th>
                    <th style={{ padding: '12px', textAlign: 'left' }}>Promotion ID</th>
                    <th style={{ padding: '12px', textAlign: 'right' }}>Promotion Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.loyaltyDetails.map((loy, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '12px' }}>{loy.posTransactionId}</td>
                      <td style={{ padding: '12px' }}>{loy.promotionId || 'N/A'}</td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>${parseFloat(loy.promotionAmount).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Loyalty Overview */}
        {selectedReport === 'loyaltyOverview' && reports.loyaltyOverview && (
          <div style={{
            background: 'var(--surface)',
            borderRadius: '12px',
            padding: '20px',
            border: '1px solid var(--border)'
          }}>
            <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Loyalty Overview</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '15px' }}>
              <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Total Promotions</div>
                <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>{reports.loyaltyOverview.totalPromotions}</div>
              </div>
              <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Total Promo Amount</div>
                <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>${reports.loyaltyOverview.totalPromotionAmount.toFixed(2)}</div>
              </div>
              <div style={{ background: 'var(--background)', padding: '15px', borderRadius: '8px' }}>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '5px' }}>Average Promo Amount</div>
                <div style={{ fontSize: '1.5rem', fontWeight: '600' }}>${reports.loyaltyOverview.averagePromotionAmount.toFixed(2)}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Transaction Details Modal */}
      {selectedTransaction && (
        <div 
          onClick={closeTransactionModal}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.5)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000
          }}
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'white',
              color: '#000',
              borderRadius: '4px',
              padding: '0',
              maxWidth: '420px',
              width: '90%',
              maxHeight: '85vh',
              overflow: 'auto',
              boxShadow: '0 10px 40px rgba(0, 0, 0, 0.3)',
              fontFamily: 'Courier New, monospace',
              fontSize: '13px'
            }}
          >
            {/* Receipt Paper Effect */}
            <div style={{ padding: '30px 25px' }}>
              {/* Store Header */}
              <div style={{ textAlign: 'center', marginBottom: '20px' }}>
                <div style={{ fontSize: '20px', fontWeight: 'bold', marginBottom: '8px' }}>BIRDIES GAS STATION</div>
                <div style={{ fontSize: '11px', lineHeight: '1.4' }}>
                  12345 Main Street<br/>
                  Hollywood, MD 20636<br/>
                  (301) 555-0100
                </div>
              </div>

              {/* Transaction Info */}
              <div style={{ borderTop: '1px dashed #000', borderBottom: '1px dashed #000', padding: '10px 0', margin: '15px 0', fontSize: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                  <span>DATE:</span>
                  <span>{new Date(selectedTransaction.transactionDateTime).toLocaleDateString()}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                  <span>TIME:</span>
                  <span>{new Date(selectedTransaction.transactionDateTime).toLocaleTimeString()}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                  <span>TRANS#:</span>
                  <span>{selectedTransaction.transactionId}</span>
                </div>
                {selectedTransaction.cashierId && (
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>CASHIER:</span>
                    <span>{selectedTransaction.cashierId}</span>
                  </div>
                )}
              </div>

              {/* Loading State */}
              {detailsLoading && (
                <div style={{ textAlign: 'center', padding: '30px', color: '#666' }}>
                  Loading receipt...
                </div>
              )}

              {/* Line Items */}
              {!detailsLoading && transactionDetails && transactionDetails.lineItems && transactionDetails.lineItems.length > 0 && (
                <>
                  <div style={{ marginBottom: '15px' }}>
                    {transactionDetails.lineItems.map((item, idx) => {
                      const isFuel = item.itemType === 'fuel';
                      const pricePerGallon = isFuel && item.quantity > 0 ? item.amount / item.quantity : 0;
                      
                      return (
                        <div key={idx} style={{ marginBottom: '12px', paddingBottom: '8px', borderBottom: '1px dotted #ccc' }}>
                          {/* Item Description */}
                          <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>
                            {item.description || (isFuel ? 'FUEL' : 'MERCHANDISE')}
                          </div>
                          
                          {/* Fuel Details */}
                          {isFuel ? (
                            <>
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                                <span>  Pump {item.pumpNumber || 'N/A'}</span>
                              </div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                                <span>  Gallons:</span>
                                <span>{parseFloat(item.quantity).toFixed(3)}</span>
                              </div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '2px' }}>
                                <span>  Price/Gal:</span>
                                <span>${pricePerGallon.toFixed(3)}</span>
                              </div>
                            </>
                          ) : (
                            <>
                              {/* Merchandise Details */}
                              {item.upc && (
                                <div style={{ fontSize: '11px', marginBottom: '2px' }}>
                                  UPC: {item.upc}
                                </div>
                              )}
                              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                                <span>  Qty: {parseFloat(item.quantity).toFixed(0)}</span>
                              </div>
                            </>
                          )}
                          
                          {/* Item Total */}
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', marginTop: '4px' }}>
                            <span>  TOTAL:</span>
                            <span>${parseFloat(item.amount).toFixed(2)}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Subtotals */}
                  <div style={{ borderTop: '1px solid #000', paddingTop: '10px', marginBottom: '10px' }}>
                    {parseFloat(selectedTransaction.fuelAmount) > 0 && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                        <span>FUEL SUBTOTAL:</span>
                        <span>${parseFloat(selectedTransaction.fuelAmount).toFixed(2)}</span>
                      </div>
                    )}
                    {parseFloat(selectedTransaction.merchAmount) > 0 && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                        <span>MERCHANDISE SUBTOTAL:</span>
                        <span>${parseFloat(selectedTransaction.merchAmount).toFixed(2)}</span>
                      </div>
                    )}
                  </div>

                  {/* Tax */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px', fontSize: '12px' }}>
                    <span>TAX:</span>
                    <span>$0.00</span>
                  </div>

                  {/* Total */}
                  <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    fontSize: '16px',
                    fontWeight: 'bold',
                    marginTop: '10px',
                    paddingTop: '10px',
                    borderTop: '2px solid #000'
                  }}>
                    <span>TOTAL:</span>
                    <span>${parseFloat(selectedTransaction.totalAmount).toFixed(2)}</span>
                  </div>

                  {/* Payment Method */}
                  {selectedTransaction.tenderType && (
                    <div style={{ 
                      marginTop: '15px',
                      paddingTop: '10px',
                      borderTop: '1px dashed #000',
                      fontSize: '12px'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold' }}>
                        <span>PAYMENT METHOD:</span>
                        <span>{selectedTransaction.tenderType.toUpperCase()}</span>
                      </div>
                    </div>
                  )}

                  {/* Footer */}
                  <div style={{ 
                    textAlign: 'center', 
                    marginTop: '20px',
                    paddingTop: '15px',
                    borderTop: '1px dashed #000',
                    fontSize: '11px',
                    lineHeight: '1.5'
                  }}>
                    <div>Thank You For Your Business!</div>
                    <div style={{ marginTop: '8px' }}>Have a Great Day!</div>
                  </div>
                </>
              )}

              {!detailsLoading && (!transactionDetails || !transactionDetails.lineItems || transactionDetails.lineItems.length === 0) && (
                <div style={{ textAlign: 'center', padding: '30px', color: '#666' }}>
                  No receipt data available
                </div>
              )}
            </div>

            {/* Close Button */}
            <div style={{ padding: '0 25px 25px 25px' }}>
              <button
                onClick={closeTransactionModal}
                style={{
                  width: '100%',
                  padding: '12px',
                  background: '#000',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  cursor: 'pointer',
                  fontFamily: 'Courier New, monospace'
                }}
              >
                CLOSE RECEIPT
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={{ marginTop: '20px', padding: '15px', background: 'var(--surface)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
        <p style={{ margin: '5px 0' }}>💡 <strong>Tip:</strong> Use the checkboxes under "Visible Reports" to show/hide specific reports</p>
        <p style={{ margin: '5px 0' }}>📊 Total reports available: 11 | Date range: {dateRange === 'single' ? filters.startDate : `${filters.startDate} to ${filters.endDate}`}</p>
        <p style={{ margin: '5px 0' }}>⚠️ Some reports require CPJR files. If data appears empty, the POS may not have generated these files yet.</p>
      </div>
    </>
  );
}

export default SalesAnalytics;

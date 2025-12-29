import { useState, useEffect } from 'react';

function BirdiesLoyalty() {
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dataLoading, setDataLoading] = useState(false);
  
  const [pendingStore, setPendingStore] = useState('');
  const [pendingDateRange, setPendingDateRange] = useState('range');
  const [pendingFilters, setPendingFilters] = useState({
    startDate: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    endDate: new Date().toISOString().split('T')[0]
  });
  
  const [selectedStore, setSelectedStore] = useState('');
  const [dateRange, setDateRange] = useState('range');
  const [filters, setFilters] = useState({
    startDate: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    endDate: new Date().toISOString().split('T')[0]
  });
  
  const [selectedReport, setSelectedReport] = useState('transactions');
  const [selectedTransaction, setSelectedTransaction] = useState(null);
  
  const [reportData, setReportData] = useState({
    transactions: [],
    failedLookups: [],
    promotionUsage: [],
    pointsActivity: [],
    customerActivity: [],
    anomalyAlerts: []
  });

  const reportOptions = [
    { id: 'transactions', label: 'Loyalty Transactions', description: 'All successful loyalty transactions' },
    { id: 'failedLookups', label: 'Failed Lookups', description: 'Failed barcode/phone lookups - signup opportunities' },
    { id: 'promotionUsage', label: 'Promotion Usage', description: 'Which promotions are being redeemed' },
    { id: 'pointsActivity', label: 'Points Activity', description: 'Points earned vs redeemed by store/date' },
    { id: 'customerActivity', label: 'Customer Activity', description: 'Most active loyalty members ranked' },
    { id: 'anomalyAlerts', label: 'Anomaly Alerts', description: 'Big spenders and unusual activity patterns' }
  ];

  useEffect(() => {
    loadLocations();
  }, []);

  useEffect(() => {
    if (!loading && filters.startDate) {
      loadCurrentReport();
    }
  }, [loading, filters.startDate, filters.endDate, dateRange, selectedReport, selectedStore]);

  const loadLocations = async () => {
    try {
      const response = await fetch('/api/admin/locations');
      const data = await response.json();
      setLocations(data);
    } catch (error) {
      console.error('Error loading locations:', error);
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
    setSelectedStore(pendingStore);
  };

  const loadCurrentReport = async () => {
    setDataLoading(true);
    
    const queryParams = new URLSearchParams();
    if (selectedStore) {
      queryParams.append('storeNumber', selectedStore);
    }
    queryParams.append('startDate', filters.startDate);
    if (filters.endDate) {
      queryParams.append('endDate', filters.endDate);
    }
    
    const queryString = queryParams.toString();

    try {
      let data = null;
      
      switch (selectedReport) {
        case 'transactions':
          data = await fetch(`/api/loyalty/reports/transactions?${queryString}`).then(r => r.ok ? r.json() : []);
          setReportData(prev => ({ ...prev, transactions: data }));
          break;
        case 'failedLookups':
          data = await fetch(`/api/loyalty/reports/failed-lookups?${queryString}`).then(r => r.ok ? r.json() : []);
          setReportData(prev => ({ ...prev, failedLookups: data }));
          break;
        case 'promotionUsage':
          data = await fetch(`/api/loyalty/reports/promotion-usage?${queryString}`).then(r => r.ok ? r.json() : []);
          setReportData(prev => ({ ...prev, promotionUsage: data }));
          break;
        case 'pointsActivity':
          data = await fetch(`/api/loyalty/reports/points-activity?${queryString}`).then(r => r.ok ? r.json() : []);
          setReportData(prev => ({ ...prev, pointsActivity: data }));
          break;
        case 'customerActivity':
          data = await fetch(`/api/loyalty/reports/customer-activity?${queryString}`).then(r => r.ok ? r.json() : []);
          setReportData(prev => ({ ...prev, customerActivity: data }));
          break;
        case 'anomalyAlerts':
          data = await fetch(`/api/loyalty/reports/anomaly-alerts?${queryString}`).then(r => r.ok ? r.json() : []);
          setReportData(prev => ({ ...prev, anomalyAlerts: data }));
          break;
      }
    } catch (error) {
      console.error('Error loading report:', error);
    } finally {
      setDataLoading(false);
    }
  };

  const formatCurrency = (value) => {
    const num = parseFloat(value) || 0;
    return '$' + num.toFixed(2);
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const hasData = () => {
    switch (selectedReport) {
      case 'transactions': return reportData.transactions.length > 0;
      case 'failedLookups': return reportData.failedLookups.length > 0;
      case 'promotionUsage': return reportData.promotionUsage.length > 0;
      case 'pointsActivity': return reportData.pointsActivity.length > 0;
      case 'customerActivity': return reportData.customerActivity.length > 0;
      case 'anomalyAlerts': return reportData.anomalyAlerts.length > 0;
      default: return false;
    }
  };

  const renderTransactionsReport = () => {
    const transactions = reportData.transactions || [];

    return (
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>
          Loyalty Transactions ({transactions.length})
        </h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Date/Time</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Store</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Trans #</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Customer</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Subtotal</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Promo Disc</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Pts Earned</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Pts Used</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Net Amount</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((t, idx) => (
                <tr 
                  key={t.id || idx} 
                  style={{ 
                    borderBottom: '1px solid var(--border)',
                    cursor: 'pointer',
                    transition: 'background 0.2s'
                  }}
                  onClick={() => setSelectedTransaction(t)}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--background)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '12px' }}>{formatDate(t.transactionDate)}</td>
                  <td style={{ padding: '12px' }}>{t.pdiStoreNumber}</td>
                  <td style={{ padding: '12px' }}>{t.transactionId}</td>
                  <td style={{ padding: '12px' }}>{t.customerName || 'Unknown'}</td>
                  <td style={{ padding: '12px', textAlign: 'right' }}>{formatCurrency(t.subtotal)}</td>
                  <td style={{ padding: '12px', textAlign: 'right', color: parseFloat(t.promotionDiscount) > 0 ? '#16a34a' : 'inherit' }}>
                    {parseFloat(t.promotionDiscount) > 0 ? `-${formatCurrency(t.promotionDiscount)}` : '-'}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#16a34a' }}>+{t.pointsEarned || 0}</td>
                  <td style={{ padding: '12px', textAlign: 'right', color: t.pointsRedeemed > 0 ? '#dc2626' : 'inherit' }}>
                    {t.pointsRedeemed > 0 ? `-${t.pointsRedeemed}` : '-'}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: 'var(--primary)' }}>
                    {formatCurrency(t.netAmount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '15px', marginBottom: 0 }}>
          Click any row to view full receipt details
        </p>
      </div>
    );
  };

  const renderFailedLookupsReport = () => {
    const lookups = reportData.failedLookups || [];

    return (
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>
          Failed Lookups ({lookups.length})
        </h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Date/Time</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Store</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Input Type</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Value Entered</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Error Reason</th>
              </tr>
            </thead>
            <tbody>
              {lookups.map((l, idx) => (
                <tr key={l.id || idx} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '12px' }}>{formatDate(l.lookupDate)}</td>
                  <td style={{ padding: '12px' }}>{l.pdiStoreNumber}</td>
                  <td style={{ padding: '12px' }}>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: l.inputType === 'barcode' ? '#dbeafe' : '#fef3c7',
                      color: l.inputType === 'barcode' ? '#1e40af' : '#92400e',
                      fontSize: '0.85rem'
                    }}>
                      {l.inputType}
                    </span>
                  </td>
                  <td style={{ padding: '12px' }}>
                    <code style={{ background: 'var(--background)', padding: '2px 6px', borderRadius: '4px' }}>
                      {l.inputValue}
                    </code>
                  </td>
                  <td style={{ padding: '12px', color: '#dc2626' }}>{l.errorReason || 'Not Found'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderPromotionUsageReport = () => {
    const promos = reportData.promotionUsage || [];

    return (
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Promotion Usage</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Store</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Promotion Name</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Times Used</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Total Discount</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Avg Discount</th>
              </tr>
            </thead>
            <tbody>
              {promos.map((p, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '12px' }}>{p.date}</td>
                  <td style={{ padding: '12px' }}>{p.storeNumber}</td>
                  <td style={{ padding: '12px', fontWeight: '500' }}>{p.promotionName}</td>
                  <td style={{ padding: '12px', textAlign: 'right' }}>{p.timesUsed}</td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#16a34a', fontWeight: '600' }}>
                    {formatCurrency(p.totalDiscount)}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right' }}>{formatCurrency(p.avgDiscount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderPointsActivityReport = () => {
    const activity = reportData.pointsActivity || [];

    return (
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Points Activity</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Date</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Store</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Points Earned</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Points Redeemed</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Net Points</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Redemption Value</th>
              </tr>
            </thead>
            <tbody>
              {activity.map((a, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '12px' }}>{a.date}</td>
                  <td style={{ padding: '12px' }}>{a.storeNumber || 'All Stores'}</td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#16a34a' }}>+{a.pointsEarned}</td>
                  <td style={{ padding: '12px', textAlign: 'right', color: a.pointsRedeemed > 0 ? '#dc2626' : 'inherit' }}>
                    {a.pointsRedeemed > 0 ? `-${a.pointsRedeemed}` : '0'}
                  </td>
                  <td style={{ 
                    padding: '12px', 
                    textAlign: 'right', 
                    fontWeight: '600',
                    color: a.netPoints >= 0 ? '#16a34a' : '#dc2626' 
                  }}>
                    {a.netPoints >= 0 ? '+' : ''}{a.netPoints}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right' }}>{formatCurrency(a.redemptionValue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderCustomerActivityReport = () => {
    const customers = reportData.customerActivity || [];

    return (
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Customer Activity (Top 50)</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Rank</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Customer</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Total Visits</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Total Spent</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Points Earned</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Points Redeemed</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Last Visit</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '12px' }}>
                    <span style={{
                      display: 'inline-block',
                      width: '24px',
                      height: '24px',
                      borderRadius: '50%',
                      background: idx < 3 ? '#fbbf24' : 'var(--background)',
                      color: idx < 3 ? '#000' : 'inherit',
                      textAlign: 'center',
                      lineHeight: '24px',
                      fontWeight: '600',
                      fontSize: '0.85rem'
                    }}>
                      {idx + 1}
                    </span>
                  </td>
                  <td style={{ padding: '12px', fontWeight: '500' }}>{c.customerName}</td>
                  <td style={{ padding: '12px', textAlign: 'right' }}>{c.totalVisits}</td>
                  <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600', color: 'var(--primary)' }}>
                    {formatCurrency(c.totalSpent)}
                  </td>
                  <td style={{ padding: '12px', textAlign: 'right', color: '#16a34a' }}>+{c.pointsEarned}</td>
                  <td style={{ padding: '12px', textAlign: 'right', color: c.pointsRedeemed > 0 ? '#dc2626' : 'inherit' }}>
                    {c.pointsRedeemed > 0 ? `-${c.pointsRedeemed}` : '0'}
                  </td>
                  <td style={{ padding: '12px' }}>{formatDate(c.lastVisit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderAnomalyAlertsReport = () => {
    const alerts = reportData.anomalyAlerts || [];

    return (
      <div style={{
        background: 'var(--surface)',
        borderRadius: '12px',
        padding: '20px',
        border: '1px solid var(--border)'
      }}>
        <h3 style={{ marginTop: 0, marginBottom: '15px' }}>Anomaly Alerts</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '12px', textAlign: 'left' }}>Date/Time</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Store</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Customer</th>
                <th style={{ padding: '12px', textAlign: 'right' }}>Amount</th>
                <th style={{ padding: '12px', textAlign: 'left' }}>Flag Reason</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a, idx) => (
                <tr key={idx} style={{ 
                  borderBottom: '1px solid var(--border)',
                  background: 'rgba(251, 191, 36, 0.1)'
                }}>
                  <td style={{ padding: '12px' }}>{formatDate(a.transactionDate)}</td>
                  <td style={{ padding: '12px' }}>{a.storeNumber}</td>
                  <td style={{ padding: '12px', fontWeight: '500' }}>{a.customerName}</td>
                  <td style={{ padding: '12px', textAlign: 'right', fontWeight: '600' }}>{formatCurrency(a.amount)}</td>
                  <td style={{ padding: '12px' }}>
                    <span style={{
                      padding: '4px 10px',
                      borderRadius: '6px',
                      background: '#fef3c7',
                      color: '#92400e',
                      fontSize: '0.85rem',
                      fontWeight: '500'
                    }}>
                      {a.flagReason}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  const renderTransactionModal = () => {
    if (!selectedTransaction) return null;

    const t = selectedTransaction;
    let lineItems = [];
    let promotions = [];
    
    try {
      lineItems = t.lineItems ? JSON.parse(t.lineItems) : [];
    } catch (e) {
      lineItems = [];
    }
    
    try {
      promotions = t.promotionDetails ? JSON.parse(t.promotionDetails) : [];
    } catch (e) {
      promotions = [];
    }

    return (
      <div 
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}
        onClick={() => setSelectedTransaction(null)}
      >
        <div 
          style={{
            background: 'var(--surface)',
            borderRadius: '16px',
            padding: '30px',
            maxWidth: '600px',
            width: '90%',
            maxHeight: '85vh',
            overflowY: 'auto',
            position: 'relative'
          }}
          onClick={e => e.stopPropagation()}
        >
          <button 
            onClick={() => setSelectedTransaction(null)}
            style={{
              position: 'absolute',
              top: '15px',
              right: '15px',
              background: 'none',
              border: 'none',
              fontSize: '1.5rem',
              cursor: 'pointer',
              color: 'var(--text-secondary)'
            }}
          >
            &times;
          </button>
          
          <div style={{ textAlign: 'center', marginBottom: '25px' }}>
            <h2 style={{ margin: '0 0 5px 0' }}>Transaction Receipt</h2>
            <p style={{ margin: 0, color: 'var(--text-secondary)' }}>#{t.transactionId}</p>
          </div>

          <div style={{
            background: 'var(--background)',
            padding: '15px',
            borderRadius: '8px',
            marginBottom: '20px'
          }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '0.9rem' }}>
              <div><strong>Date:</strong> {formatDate(t.transactionDate)}</div>
              <div><strong>Store:</strong> {t.pdiStoreNumber}</div>
              <div><strong>Customer:</strong> {t.customerName || 'Unknown'}</div>
              <div><strong>Loyalty ID:</strong> {t.loyaltyId || 'N/A'}</div>
            </div>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <h4 style={{ margin: '0 0 10px 0' }}>Items</h4>
            {lineItems.length > 0 ? (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--background)', borderBottom: '2px solid var(--border)' }}>
                    <th style={{ padding: '10px', textAlign: 'left' }}>Description</th>
                    <th style={{ padding: '10px', textAlign: 'center' }}>Qty</th>
                    <th style={{ padding: '10px', textAlign: 'right' }}>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((item, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '10px' }}>{item.description || 'Unknown Item'}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>{item.quantity || 1}</td>
                      <td style={{ padding: '10px', textAlign: 'right' }}>{formatCurrency(item.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>No line item details available</p>
            )}
          </div>

          {promotions.length > 0 && (
            <div style={{ marginBottom: '20px' }}>
              <h4 style={{ margin: '0 0 10px 0' }}>Promotions Applied</h4>
              {promotions.map((promo, idx) => (
                <div key={idx} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 12px',
                  background: '#dcfce7',
                  borderRadius: '6px',
                  marginBottom: '5px'
                }}>
                  <span>{promo.name || promo.description}</span>
                  <span style={{ color: '#16a34a', fontWeight: '600' }}>-{formatCurrency(promo.discount)}</span>
                </div>
              ))}
            </div>
          )}

          <div style={{
            background: 'var(--background)',
            padding: '15px',
            borderRadius: '8px',
            marginBottom: '20px'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span>Subtotal:</span>
              <span>{formatCurrency(t.subtotal)}</span>
            </div>
            {parseFloat(t.promotionDiscount) > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: '#16a34a' }}>
                <span>Promotion Discount:</span>
                <span>-{formatCurrency(t.promotionDiscount)}</span>
              </div>
            )}
            {parseFloat(t.pointsDiscount) > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: '#16a34a' }}>
                <span>Points Discount:</span>
                <span>-{formatCurrency(t.pointsDiscount)}</span>
              </div>
            )}
            <div style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              borderTop: '2px solid var(--border)',
              paddingTop: '10px',
              marginTop: '10px',
              fontWeight: '600',
              fontSize: '1.1rem'
            }}>
              <span>Net Amount:</span>
              <span style={{ color: 'var(--primary)' }}>{formatCurrency(t.netAmount)}</span>
            </div>
          </div>

          <div style={{
            background: 'linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%)',
            padding: '15px',
            borderRadius: '8px',
            color: 'white'
          }}>
            <h4 style={{ margin: '0 0 10px 0' }}>Points Summary</h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', textAlign: 'center' }}>
              <div>
                <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>Before</div>
                <div style={{ fontSize: '1.2rem', fontWeight: '600' }}>{t.pointsBefore || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>Earned</div>
                <div style={{ fontSize: '1.2rem', fontWeight: '600' }}>+{t.pointsEarned || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>Redeemed</div>
                <div style={{ fontSize: '1.2rem', fontWeight: '600' }}>{t.pointsRedeemed > 0 ? `-${t.pointsRedeemed}` : '0'}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>After</div>
                <div style={{ fontSize: '1.2rem', fontWeight: '600' }}>{t.pointsAfter || 0}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const renderCurrentReport = () => {
    switch (selectedReport) {
      case 'transactions':
        return renderTransactionsReport();
      case 'failedLookups':
        return renderFailedLookupsReport();
      case 'promotionUsage':
        return renderPromotionUsageReport();
      case 'pointsActivity':
        return renderPointsActivityReport();
      case 'customerActivity':
        return renderCustomerActivityReport();
      case 'anomalyAlerts':
        return renderAnomalyAlertsReport();
      default:
        return null;
    }
  };

  if (loading) {
    return (
      <div className="section-header">
        <h2>Birdies Loyalty Reports</h2>
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <>
      <div className="section-header">
        <h2>Birdies Loyalty Reports</h2>
        <p>Live loyalty transaction data from POS systems</p>
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
            {reportOptions.map(opt => (
              <option key={opt.id} value={opt.id}>{opt.label}</option>
            ))}
          </select>
          <p style={{ margin: '8px 0 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            {reportOptions.find(r => r.id === selectedReport)?.description}
          </p>
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
          </div>

          {/* Date Inputs */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '5px', fontSize: '0.85rem' }}>Start Date</label>
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
          </div>
        </div>

        {/* Store Selection */}
        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', fontWeight: '500' }}>
            Select Store
          </label>
          <select
            value={pendingStore}
            onChange={(e) => setPendingStore(e.target.value)}
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
            <option value="">All Stores</option>
            {locations.map(loc => (
              <option key={loc.id} value={loc.pdiStoreNumber}>
                {loc.locationName} ({loc.pdiStoreNumber})
              </option>
            ))}
          </select>
        </div>

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

      {/* Loading State */}
      {dataLoading && (
        <div style={{
          background: 'var(--surface)',
          borderRadius: '12px',
          padding: '40px',
          textAlign: 'center',
          border: '1px solid var(--border)',
          marginBottom: '20px'
        }}>
          <div style={{ fontSize: '2rem', marginBottom: '10px' }}>⏳</div>
          <p style={{ fontSize: '1.1rem', color: 'var(--text-secondary)', margin: 0 }}>Loading data...</p>
        </div>
      )}

      {/* No Data State */}
      {!dataLoading && !loading && filters.startDate && !hasData() && (
        <div style={{
          background: 'var(--surface)',
          borderRadius: '12px',
          padding: '60px 40px',
          textAlign: 'center',
          border: '1px solid var(--border)',
          marginBottom: '20px'
        }}>
          <div style={{ fontSize: '3rem', marginBottom: '15px', opacity: 0.5 }}>🎯</div>
          <h3 style={{ margin: '0 0 10px 0', color: 'var(--text-primary)' }}>No Data Found</h3>
          <p style={{ fontSize: '0.95rem', color: 'var(--text-secondary)', margin: 0, maxWidth: '500px', marginLeft: 'auto', marginRight: 'auto' }}>
            No {reportOptions.find(r => r.id === selectedReport)?.label.toLowerCase()} found for the selected filters.
            {selectedStore && <><br />Try selecting a different store or date range.</>}
            {!selectedStore && <><br />Try selecting a specific store or different date range.</>}
          </p>
        </div>
      )}

      {/* Reports Container */}
      {!dataLoading && hasData() && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {renderCurrentReport()}
        </div>
      )}

      {renderTransactionModal()}
    </>
  );
}

export default BirdiesLoyalty;

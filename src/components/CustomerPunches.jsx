import { useState, useEffect } from 'react';

function CustomerPunches() {
  const [customerPunches, setCustomerPunches] = useState([]);
  const [punchCards, setPunchCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedPunchCard, setSelectedPunchCard] = useState('');

  useEffect(() => {
    loadCustomerPunches();
    loadPunchCards();
  }, []);

  const loadCustomerPunches = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (searchTerm) params.set('search', searchTerm);
      if (selectedPunchCard) params.set('punchCardId', selectedPunchCard);
      
      const response = await fetch(`/api/punch-cards/reports/customers?${params}`);
      const data = await response.json();
      setCustomerPunches(data);
    } catch (error) {
      console.log('Error loading customer punches:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadPunchCards = async () => {
    try {
      const response = await fetch('/api/punch-cards/promotions');
      const data = await response.json();
      setPunchCards(data);
    } catch (error) {
      console.log('Error loading punch cards:', error);
    }
  };

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      loadCustomerPunches();
    }, 300);
    return () => clearTimeout(timeoutId);
  }, [searchTerm, selectedPunchCard]);

  const formatDate = (dateString) => {
    if (!dateString) return 'Never';
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const getProgressColor = (percent) => {
    if (percent >= 100) return 'var(--success)';
    if (percent >= 75) return 'var(--warning)';
    return 'var(--primary)';
  };

  if (loading && customerPunches.length === 0) {
    return <div className="section-header"><h2>Customer Punch Progress</h2><p>Loading...</p></div>;
  }

  return (
    <>
      <div className="section-header">
        <h2>Customer Punch Progress</h2>
      </div>

      <div className="card" style={{ padding: '1rem', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: '200px' }}>
            <input
              type="text"
              placeholder="Search by name or phone..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ minWidth: '200px' }}>
            <select
              value={selectedPunchCard}
              onChange={(e) => setSelectedPunchCard(e.target.value)}
              style={{ width: '100%' }}
            >
              <option value="">All Punch Cards</option>
              {punchCards.map((pc) => (
                <option key={pc.id} value={pc.id}>{pc.name}</option>
              ))}
            </select>
          </div>
          <button 
            className="btn btn-secondary" 
            onClick={loadCustomerPunches}
            style={{ padding: '0.5rem 1rem' }}
          >
            Refresh
          </button>
        </div>
      </div>

      {customerPunches.length === 0 ? (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
          No customer punch data found.
          {searchTerm || selectedPunchCard ? ' Try adjusting your filters.' : ' Punches will appear here as customers make qualifying purchases.'}
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {customerPunches.map((cp, index) => (
            <div 
              key={`${cp.customerId}-${cp.punchCardId}-${index}`} 
              className="card" 
              style={{ 
                padding: '1rem',
                borderLeft: cp.rewardReady ? '4px solid var(--success)' : '4px solid var(--border)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '1.1rem' }}>
                    {cp.customerName}
                    {cp.rewardReady && (
                      <span style={{ 
                        marginLeft: '0.5rem', 
                        background: 'var(--success)', 
                        color: 'white', 
                        padding: '0.15rem 0.5rem', 
                        borderRadius: '0.25rem',
                        fontSize: '0.75rem',
                        fontWeight: 'bold',
                      }}>
                        REWARD READY
                      </span>
                    )}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                    {cp.customerPhone || 'No phone'}
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ 
                    fontSize: '1.5rem', 
                    fontWeight: 'bold', 
                    color: getProgressColor(cp.progressPercent) 
                  }}>
                    {cp.currentPunches}/{cp.punchesRequired}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>punches</div>
                </div>
              </div>

              <div style={{ marginBottom: '0.75rem' }}>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                  {cp.punchCardName}
                  {cp.itemGroupName && <span> ({cp.itemGroupName})</span>}
                </div>
                <div style={{ 
                  background: 'var(--border)', 
                  borderRadius: '0.5rem', 
                  height: '8px',
                  overflow: 'hidden',
                }}>
                  <div style={{ 
                    background: getProgressColor(cp.progressPercent),
                    height: '100%',
                    width: `${cp.progressPercent}%`,
                    transition: 'width 0.3s ease',
                  }} />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '2rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                <div>
                  <strong>Last Punch:</strong> {formatDate(cp.lastPunchDate)}
                </div>
                <div>
                  <strong>Total Earned:</strong> {cp.totalPunchesEarned || 0}
                </div>
                <div>
                  <strong>Rewards Redeemed:</strong> {cp.totalRewardsRedeemed || 0}
                </div>
                {!cp.rewardReady && (
                  <div>
                    <strong>{cp.punchesRemaining}</strong> more to reward
                  </div>
                )}
              </div>

              {cp.rewardReady && (
                <div style={{ 
                  marginTop: '0.75rem', 
                  padding: '0.5rem', 
                  background: 'rgba(34, 197, 94, 0.1)', 
                  borderRadius: '0.25rem',
                  fontSize: '0.9rem',
                }}>
                  Reward: {
                    cp.rewardType === 'free_item' 
                      ? 'Free Item'
                      : cp.rewardType === 'amount_off'
                      ? `$${parseFloat(cp.rewardValue || 0).toFixed(2)} Off`
                      : cp.rewardType === 'percent_off'
                      ? `${cp.rewardValue}% Off`
                      : cp.rewardType
                  }
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default CustomerPunches;

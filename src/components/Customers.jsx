import { useState, useEffect } from 'react';
import Modal from './Modal';

function Customers() {
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loyaltyTransactions, setLoyaltyTransactions] = useState([]);
  const [loadingTransactions, setLoadingTransactions] = useState(false);
  const [transactionError, setTransactionError] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [selectedReceipt, setSelectedReceipt] = useState(null);
  const [showReceiptModal, setShowReceiptModal] = useState(false);

  useEffect(() => {
    loadCustomers();
  }, []);

  const loadCustomers = async () => {
    try {
      const response = await fetch('/api/admin/customers');
      if (!response.ok) {
        throw new Error('Failed to load customers');
      }
      const data = await response.json();
      setCustomers(data);
      setError(null);
    } catch (err) {
      console.log('Error loading customers:', err);
      setError('Failed to load customers. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const viewCustomerDetails = async (customer) => {
    setSelectedCustomer(customer);
    setShowModal(true);
    setLoadingTransactions(true);
    setTransactionError(null);
    
    try {
      const [basicRes, loyaltyRes] = await Promise.all([
        fetch(`/api/admin/customers/${customer.id}/transactions`),
        fetch(`/api/loyalty/customer/${customer.id}/transactions`)
      ]);
      
      if (basicRes.ok) {
        const basicData = await basicRes.json();
        setTransactions(basicData);
      }
      
      if (loyaltyRes.ok) {
        const loyaltyData = await loyaltyRes.json();
        setLoyaltyTransactions(loyaltyData);
      }
      
      setTransactionError(null);
    } catch (error) {
      console.log('Error loading transactions:', error);
      setTransactionError('Failed to load purchase history. Please try again.');
    } finally {
      setLoadingTransactions(false);
    }
  };

  const openReceiptModal = (transaction) => {
    setSelectedReceipt(transaction);
    setShowReceiptModal(true);
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(amount || 0);
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString();
  };

  if (loading) {
    return (
      <div className="section-header">
        <h2>Customers</h2>
        <p>Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <>
        <div className="section-header">
          <h2>Customers</h2>
        </div>
        <div style={{ 
          padding: '1.5rem', 
          margin: '1rem 0',
          backgroundColor: 'var(--danger-bg)', 
          border: '1px solid var(--danger)',
          borderRadius: '8px',
          color: 'var(--danger)'
        }}>
          <p>{error}</p>
          <button 
            onClick={loadCustomers}
            style={{
              marginTop: '1rem',
              padding: '0.5rem 1rem',
              backgroundColor: 'var(--danger)',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            Retry
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="section-header">
        <h2>Customers</h2>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Phone</th>
            <th>Date of Birth</th>
            <th>Loyalty ID</th>
            <th>Points</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {customers.length === 0 ? (
            <tr>
              <td colSpan="8" className="empty">No customers found</td>
            </tr>
          ) : (
            customers.map((customer) => (
              <tr key={customer.id}>
                <td>{customer.firstName} {customer.lastName}</td>
                <td>{customer.email}</td>
                <td>{customer.phone || 'N/A'}</td>
                <td>{customer.dateOfBirth || 'N/A'}</td>
                <td style={{ fontFamily: 'monospace', color: 'var(--primary)', fontWeight: 600 }}>
                  {customer.loyaltyId}
                </td>
                <td style={{ fontWeight: 600, color: 'var(--success)' }}>
                  {customer.points}
                </td>
                <td>{new Date(customer.createdAt).toLocaleDateString()}</td>
                <td>
                  <button
                    className="btn btn-secondary"
                    onClick={() => viewCustomerDetails(customer)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                  >
                    View
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      {selectedCustomer && (
        <Modal
          isOpen={showModal}
          onClose={() => setShowModal(false)}
          title="Customer Details"
        >
          <div className="customer-details">
            <p><strong>Name:</strong> {selectedCustomer.firstName} {selectedCustomer.lastName}</p>
            <p><strong>Email:</strong> {selectedCustomer.email}</p>
            <p><strong>Phone:</strong> {selectedCustomer.phone}</p>
            <p><strong>Date of Birth:</strong> {selectedCustomer.dateOfBirth}</p>
            <p><strong>Loyalty ID:</strong> {selectedCustomer.loyaltyId}</p>
            <p><strong>Points:</strong> {selectedCustomer.points}</p>
            
            <div style={{ marginTop: '1.5rem' }}>
              <h3 style={{ marginBottom: '1rem', fontSize: '1.125rem', fontWeight: 600 }}>Purchase History</h3>
              {loadingTransactions ? (
                <p style={{ color: 'var(--text-secondary)' }}>Loading transactions...</p>
              ) : transactionError ? (
                <p style={{ color: 'var(--danger)', padding: '1rem', backgroundColor: 'var(--danger-bg)', borderRadius: '8px' }}>
                  {transactionError}
                </p>
              ) : loyaltyTransactions.length === 0 && transactions.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)' }}>No purchases yet</p>
              ) : (
                <div style={{ 
                  maxHeight: '350px', 
                  overflowY: 'auto', 
                  border: '1px solid var(--border)', 
                  borderRadius: '8px' 
                }}>
                  {loyaltyTransactions.length > 0 && (
                    <>
                      <div style={{ 
                        padding: '0.5rem 0.75rem', 
                        backgroundColor: 'var(--bg-secondary)', 
                        borderBottom: '1px solid var(--border)',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: 'var(--text-secondary)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px'
                      }}>
                        Loyalty Purchases (Click for details)
                      </div>
                      {loyaltyTransactions.map((transaction) => (
                        <div 
                          key={`loyalty-${transaction.id}`}
                          onClick={() => openReceiptModal(transaction)}
                          style={{ 
                            padding: '0.75rem',
                            borderBottom: '1px solid var(--border)',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            cursor: 'pointer',
                            transition: 'background-color 0.15s ease'
                          }}
                          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-hover)'}
                          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                        >
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: '0.875rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                              <span>Store #{transaction.pdiStoreNumber}</span>
                              <span style={{ color: 'var(--text-secondary)' }}>•</span>
                              <span style={{ fontWeight: 600 }}>{formatCurrency(transaction.netAmount)}</span>
                              {transaction.promotionUsed && (
                                <span style={{ 
                                  backgroundColor: 'var(--accent)', 
                                  color: 'white', 
                                  padding: '0.125rem 0.375rem', 
                                  borderRadius: '4px', 
                                  fontSize: '0.625rem',
                                  fontWeight: 600 
                                }}>
                                  PROMO
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                              {formatDate(transaction.transactionDate)}
                            </div>
                          </div>
                          <div style={{ textAlign: 'right', marginLeft: '1rem' }}>
                            {transaction.pointsEarned > 0 && (
                              <div style={{ fontWeight: 600, color: 'var(--success)', fontSize: '0.875rem' }}>
                                +{transaction.pointsEarned} pts
                              </div>
                            )}
                            {transaction.pointsRedeemed > 0 && (
                              <div style={{ fontWeight: 600, color: 'var(--accent)', fontSize: '0.875rem' }}>
                                -{transaction.pointsRedeemed} pts
                              </div>
                            )}
                            <div style={{ fontSize: '0.625rem', color: 'var(--text-secondary)', marginTop: '0.125rem' }}>
                              Click to view →
                            </div>
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                  
                  {transactions.length > 0 && (
                    <>
                      <div style={{ 
                        padding: '0.5rem 0.75rem', 
                        backgroundColor: 'var(--bg-secondary)', 
                        borderBottom: '1px solid var(--border)',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: 'var(--text-secondary)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px'
                      }}>
                        Points Activity
                      </div>
                      {transactions.map((transaction) => (
                        <div 
                          key={`basic-${transaction.id}`}
                          style={{ 
                            padding: '0.75rem',
                            borderBottom: '1px solid var(--border)',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center'
                          }}
                        >
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: '0.875rem', color: 'var(--text-primary)' }}>
                              {transaction.description}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                              {new Date(transaction.createdAt).toLocaleString()}
                            </div>
                          </div>
                          <div style={{ 
                            fontWeight: 600, 
                            color: transaction.points > 0 ? 'var(--success)' : 'var(--accent)',
                            fontSize: '0.875rem',
                            marginLeft: '1rem'
                          }}>
                            {transaction.points > 0 ? '+' : ''}{transaction.points} pts
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}

      {selectedReceipt && (
        <Modal
          isOpen={showReceiptModal}
          onClose={() => setShowReceiptModal(false)}
          title="Transaction Receipt"
        >
          <div style={{ fontFamily: 'monospace', fontSize: '0.875rem' }}>
            <div style={{ 
              textAlign: 'center', 
              borderBottom: '2px dashed var(--border)', 
              paddingBottom: '1rem',
              marginBottom: '1rem'
            }}>
              <div style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '0.5rem' }}>
                BIRDIES
              </div>
              <div style={{ color: 'var(--text-secondary)' }}>
                Store #{selectedReceipt.pdiStoreNumber}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.25rem' }}>
                {formatDate(selectedReceipt.transactionDate)}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.625rem', marginTop: '0.25rem' }}>
                Trans ID: {selectedReceipt.transactionId}
              </div>
            </div>

            {selectedReceipt.lineItems && selectedReceipt.lineItems.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <div style={{ 
                  fontWeight: 600, 
                  marginBottom: '0.5rem',
                  borderBottom: '1px solid var(--border)',
                  paddingBottom: '0.25rem'
                }}>
                  ITEMS ({selectedReceipt.itemCount})
                </div>
                <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
                  {selectedReceipt.lineItems.map((item, index) => (
                    <div 
                      key={index} 
                      style={{ 
                        display: 'flex', 
                        justifyContent: 'space-between', 
                        padding: '0.25rem 0',
                        borderBottom: '1px dotted var(--border)'
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <div>{item.description || item.name || 'Item'}</div>
                        {item.quantity && item.quantity > 1 && (
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                            Qty: {item.quantity}
                          </div>
                        )}
                        {item.upc && (
                          <div style={{ fontSize: '0.625rem', color: 'var(--text-secondary)' }}>
                            {item.upc}
                          </div>
                        )}
                      </div>
                      <div style={{ fontWeight: 500 }}>
                        {formatCurrency(item.price || item.amount || 0)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0' }}>
                <span>Subtotal:</span>
                <span>{formatCurrency(selectedReceipt.subtotal)}</span>
              </div>
              
              {selectedReceipt.promotionDiscount > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', color: 'var(--accent)' }}>
                  <span>Promo Discount:</span>
                  <span>-{formatCurrency(selectedReceipt.promotionDiscount)}</span>
                </div>
              )}
              
              {selectedReceipt.pointsDiscount > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', color: 'var(--accent)' }}>
                  <span>Points Discount:</span>
                  <span>-{formatCurrency(selectedReceipt.pointsDiscount)}</span>
                </div>
              )}
              
              {selectedReceipt.totalDiscount > 0 && (
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  padding: '0.25rem 0',
                  fontWeight: 600,
                  color: 'var(--success)'
                }}>
                  <span>Total Savings:</span>
                  <span>-{formatCurrency(selectedReceipt.totalDiscount)}</span>
                </div>
              )}
              
              <div style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                padding: '0.5rem 0',
                fontWeight: 700,
                fontSize: '1.125rem',
                borderTop: '2px solid var(--border)',
                marginTop: '0.5rem'
              }}>
                <span>TOTAL:</span>
                <span>{formatCurrency(selectedReceipt.netAmount)}</span>
              </div>
            </div>

            <div style={{ 
              borderTop: '2px dashed var(--border)', 
              paddingTop: '1rem', 
              marginTop: '1rem' 
            }}>
              <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>LOYALTY REWARDS</div>
              
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0' }}>
                <span>Points Before:</span>
                <span>{selectedReceipt.pointsBefore?.toLocaleString() || 0}</span>
              </div>
              
              {selectedReceipt.pointsEarned > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', color: 'var(--success)' }}>
                  <span>Points Earned:</span>
                  <span>+{selectedReceipt.pointsEarned?.toLocaleString() || 0}</span>
                </div>
              )}
              
              {selectedReceipt.pointsRedeemed > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', color: 'var(--accent)' }}>
                  <span>Points Redeemed:</span>
                  <span>-{selectedReceipt.pointsRedeemed?.toLocaleString() || 0}</span>
                </div>
              )}
              
              <div style={{ 
                display: 'flex', 
                justifyContent: 'space-between', 
                padding: '0.5rem 0',
                fontWeight: 700,
                borderTop: '1px solid var(--border)',
                marginTop: '0.25rem'
              }}>
                <span>Points After:</span>
                <span>{selectedReceipt.pointsAfter?.toLocaleString() || 0}</span>
              </div>
            </div>

            {selectedReceipt.promotionUsed && selectedReceipt.promotionNames && (
              <div style={{ 
                borderTop: '2px dashed var(--border)', 
                paddingTop: '1rem', 
                marginTop: '1rem' 
              }}>
                <div style={{ fontWeight: 600, marginBottom: '0.5rem', color: 'var(--accent)' }}>
                  PROMOTIONS APPLIED
                </div>
                <div style={{ 
                  backgroundColor: 'var(--accent-bg)', 
                  padding: '0.75rem', 
                  borderRadius: '6px',
                  fontSize: '0.8rem'
                }}>
                  {selectedReceipt.promotionNames.split(',').map((promo, i) => (
                    <div key={i} style={{ padding: '0.125rem 0' }}>
                      • {promo.trim()}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ 
              textAlign: 'center', 
              marginTop: '1.5rem', 
              paddingTop: '1rem',
              borderTop: '2px dashed var(--border)',
              color: 'var(--text-secondary)',
              fontSize: '0.75rem'
            }}>
              <div>Thank you for shopping at Birdies!</div>
              <div style={{ marginTop: '0.25rem' }}>Earn 5 pts for every $1 spent</div>
              <div style={{ marginTop: '0.25rem' }}>Redeem 100 pts = $1 off</div>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

export default Customers;

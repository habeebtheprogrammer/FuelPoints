import { useState, useEffect } from 'react';
import Modal from './Modal';

function PunchCardPromotions() {
  const [punchCards, setPunchCards] = useState([]);
  const [itemGroups, setItemGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [summary, setSummary] = useState(null);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    itemGroupId: '',
    punchesRequired: 10,
    rewardType: 'free_item',
    rewardValue: '',
    isActive: true,
    startDate: '',
    endDate: '',
  });

  useEffect(() => {
    loadPunchCards();
    loadItemGroups();
    loadSummary();
  }, []);

  const loadPunchCards = async () => {
    try {
      const response = await fetch('/api/punch-cards/promotions');
      const data = await response.json();
      setPunchCards(data);
    } catch (error) {
      console.log('Error loading punch cards:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadItemGroups = async () => {
    try {
      const response = await fetch('/api/admin/item-groups');
      const data = await response.json();
      setItemGroups(data);
    } catch (error) {
      console.log('Error loading item groups:', error);
    }
  };

  const loadSummary = async () => {
    try {
      const response = await fetch('/api/punch-cards/reports/summary');
      const data = await response.json();
      setSummary(data);
    } catch (error) {
      console.log('Error loading summary:', error);
    }
  };

  const openAddModal = () => {
    setFormData({
      id: '',
      name: '',
      itemGroupId: '',
      punchesRequired: 10,
      rewardType: 'free_item',
      rewardValue: '',
      isActive: true,
      startDate: '',
      endDate: '',
    });
    setShowModal(true);
  };

  const editPunchCard = async (id) => {
    try {
      const response = await fetch(`/api/punch-cards/promotions/${id}`);
      const card = await response.json();
      
      const formatDateForInput = (dateString) => {
        if (!dateString) return '';
        return dateString.split('T')[0];
      };
      
      setFormData({
        ...card,
        startDate: formatDateForInput(card.startDate),
        endDate: formatDateForInput(card.endDate),
      });
      setShowModal(true);
    } catch (error) {
      console.log('Error loading punch card:', error);
      alert('Error loading punch card');
    }
  };

  const deletePunchCard = async (id) => {
    if (!window.confirm('Are you sure you want to delete this punch card promotion?')) return;

    try {
      const response = await fetch(`/api/punch-cards/promotions/${id}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        loadPunchCards();
        loadSummary();
      } else {
        alert('Error deleting punch card');
      }
    } catch (error) {
      console.log('Error deleting punch card:', error);
      alert('Error deleting punch card');
    }
  };

  const handleSubmit = async () => {
    try {
      if (!formData.name || !formData.itemGroupId) {
        alert('Please fill in all required fields');
        return;
      }

      const url = formData.id 
        ? `/api/punch-cards/promotions/${formData.id}`
        : '/api/punch-cards/promotions';
      const method = formData.id ? 'PUT' : 'POST';

      const dataToSend = {
        name: formData.name,
        itemGroupId: parseInt(formData.itemGroupId),
        punchesRequired: parseInt(formData.punchesRequired) || 10,
        rewardType: formData.rewardType,
        rewardValue: formData.rewardValue ? parseFloat(formData.rewardValue) : null,
        isActive: formData.isActive,
        startDate: formData.startDate || null,
        endDate: formData.endDate || null,
      };

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSend),
      });

      if (response.ok) {
        setShowModal(false);
        loadPunchCards();
        loadSummary();
      } else {
        alert('Error saving punch card');
      }
    } catch (error) {
      console.log('Error saving punch card:', error);
      alert('Error saving punch card');
    }
  };

  if (loading) {
    return <div className="section-header"><h2>Punch Card Promotions</h2><p>Loading...</p></div>;
  }

  return (
    <>
      {summary && (
        <div style={{ 
          display: 'grid', 
          gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', 
          gap: '1rem', 
          marginBottom: '1.5rem' 
        }}>
          <div className="card" style={{ padding: '1rem', textAlign: 'center' }}>
            <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--primary)' }}>
              {summary.activePunchCards}
            </div>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Active Cards</div>
          </div>
          <div className="card" style={{ padding: '1rem', textAlign: 'center' }}>
            <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--primary)' }}>
              {summary.customersWithPunches}
            </div>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Customers</div>
          </div>
          <div className="card" style={{ padding: '1rem', textAlign: 'center' }}>
            <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--primary)' }}>
              {summary.totalPunchesRecorded || 0}
            </div>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Total Punches</div>
          </div>
          <div className="card" style={{ padding: '1rem', textAlign: 'center' }}>
            <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--success)' }}>
              {summary.totalRewardsRedeemed || 0}
            </div>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Rewards Given</div>
          </div>
          <div className="card" style={{ padding: '1rem', textAlign: 'center' }}>
            <div style={{ fontSize: '2rem', fontWeight: 'bold', color: 'var(--warning)' }}>
              {summary.customersCloseToReward || 0}
            </div>
            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Close to Reward</div>
          </div>
        </div>
      )}

      <div className="section-header">
        <h2>Punch Card Promotions</h2>
        <button className="btn btn-primary" onClick={openAddModal}>
          + Add Punch Card
        </button>
      </div>

      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Item Group</th>
            <th>Punches Required</th>
            <th>Reward</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {punchCards.length === 0 ? (
            <tr><td colSpan="6" className="empty">No punch card promotions found</td></tr>
          ) : (
            punchCards.map((card) => (
              <tr key={card.id}>
                <td style={{ fontWeight: 600 }}>{card.name}</td>
                <td>{card.itemGroupName}</td>
                <td style={{ textAlign: 'center' }}>
                  <span style={{ 
                    background: 'var(--primary)', 
                    color: 'white', 
                    padding: '0.25rem 0.75rem', 
                    borderRadius: '1rem',
                    fontWeight: 'bold'
                  }}>
                    {card.punchesRequired}
                  </span>
                </td>
                <td>
                  {card.rewardType === 'free_item' 
                    ? 'Free Item'
                    : card.rewardType === 'amount_off'
                    ? `$${parseFloat(card.rewardValue || 0).toFixed(2)} Off`
                    : card.rewardType === 'percent_off'
                    ? `${card.rewardValue}% Off`
                    : card.rewardType
                  }
                </td>
                <td>
                  <span className={`badge ${card.isActive ? 'badge-active' : 'badge-inactive'}`}>
                    {card.isActive ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td>
                  <button
                    className="btn btn-secondary"
                    onClick={() => editPunchCard(card.id)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', marginRight: '0.5rem' }}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={() => deletePunchCard(card.id)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <Modal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        title={formData.id ? 'Edit Punch Card' : 'Add Punch Card'}
        onSubmit={handleSubmit}
      >
        <form>
          <div className="form-group">
            <label>Punch Card Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Coffee Loyalty Card"
              required
            />
          </div>

          <div className="form-group">
            <label>Item Group *</label>
            <select
              value={formData.itemGroupId}
              onChange={(e) => setFormData({ ...formData, itemGroupId: e.target.value })}
              required
            >
              <option value="">Select Item Group</option>
              {itemGroups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
            <small style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
              Purchases from this item group will earn punches
            </small>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Punches Required *</label>
              <input
                type="number"
                value={formData.punchesRequired}
                onChange={(e) => setFormData({ ...formData, punchesRequired: e.target.value })}
                min="1"
                required
              />
              <small style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                Number of purchases to earn reward
              </small>
            </div>

            <div className="form-group">
              <label>Reward Type *</label>
              <select
                value={formData.rewardType}
                onChange={(e) => setFormData({ ...formData, rewardType: e.target.value })}
                required
              >
                <option value="free_item">Free Item</option>
                <option value="amount_off">Amount Off</option>
                <option value="percent_off">Percent Off</option>
              </select>
            </div>
          </div>

          {(formData.rewardType === 'amount_off' || formData.rewardType === 'percent_off') && (
            <div className="form-group">
              <label>
                {formData.rewardType === 'amount_off' ? 'Amount Off ($)' : 'Percent Off (%)'}
              </label>
              <input
                type="number"
                value={formData.rewardValue}
                onChange={(e) => setFormData({ ...formData, rewardValue: e.target.value })}
                step={formData.rewardType === 'amount_off' ? '0.01' : '1'}
                min="0"
              />
            </div>
          )}

          <div className="form-group">
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                checked={formData.isActive}
                onChange={(e) => setFormData({ ...formData, isActive: e.target.checked })}
              />
              Active
            </label>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Start Date</label>
              <input
                type="date"
                value={formData.startDate}
                onChange={(e) => setFormData({ ...formData, startDate: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>End Date</label>
              <input
                type="date"
                value={formData.endDate}
                onChange={(e) => setFormData({ ...formData, endDate: e.target.value })}
              />
            </div>
          </div>
        </form>
      </Modal>
    </>
  );
}

export default PunchCardPromotions;

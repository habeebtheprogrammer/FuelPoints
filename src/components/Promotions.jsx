import { useState, useEffect } from 'react';
import Modal from './Modal';
import PunchCardPromotions from './PunchCardPromotions';
import CustomerPunches from './CustomerPunches';

function Promotions() {
  const [activeTab, setActiveTab] = useState('regular');
  const [promotions, setPromotions] = useState([]);
  const [itemGroups, setItemGroups] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [conflicts, setConflicts] = useState(null);
  const [showConflictModal, setShowConflictModal] = useState(false);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    itemGroupId: '',
    quantity: '',
    freeQuantity: '',
    discountType: 'multipack',
    price: '',
    amountOff: '',
    requiresLoyaltyId: false,
    isActive: true,
    startDate: '',
    endDate: '',
    locationIds: []
  });

  const checkConflicts = async (itemGroupId, excludeId = null) => {
    if (!itemGroupId) {
      setConflicts(null);
      return;
    }
    try {
      const params = new URLSearchParams({
        itemGroupId: itemGroupId.toString(),
        context: 'promotion',
      });
      if (excludeId) params.set('excludeId', excludeId.toString());
      
      const response = await fetch(`/api/admin/upc-conflicts?${params}`);
      const data = await response.json();
      
      if (data.hasConflicts) {
        setConflicts(data);
        setShowConflictModal(true);
      } else {
        setConflicts(null);
      }
    } catch (error) {
      console.log('Error checking conflicts:', error);
    }
  };

  const handleItemGroupChange = (e) => {
    const newItemGroupId = e.target.value;
    setFormData({ ...formData, itemGroupId: newItemGroupId });
    if (newItemGroupId) {
      checkConflicts(parseInt(newItemGroupId), formData.id || null);
    } else {
      setConflicts(null);
    }
  };

  useEffect(() => {
    loadPromotions();
    loadItemGroups();
    loadLocations();
  }, []);

  const loadPromotions = async () => {
    try {
      const response = await fetch('/api/admin/promotions');
      const data = await response.json();
      setPromotions(data);
    } catch (error) {
      console.log('Error loading promotions:', error);
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

  const loadLocations = async () => {
    try {
      const response = await fetch('/api/admin/locations');
      const data = await response.json();
      setLocations(data);
    } catch (error) {
      console.log('Error loading locations:', error);
    }
  };

  const openAddModal = () => {
    setFormData({
      id: '',
      name: '',
      itemGroupId: '',
      quantity: '',
      freeQuantity: '',
      discountType: 'multipack',
      price: '',
      amountOff: '',
      requiresLoyaltyId: false,
      isActive: true,
      startDate: '',
      endDate: '',
      locationIds: []
    });
    setShowModal(true);
  };

  const editPromotion = async (promotionId) => {
    try {
      const response = await fetch(`/api/admin/promotions/${promotionId}`);
      const promo = await response.json();
      
      const formatDateForInput = (dateString) => {
        if (!dateString) return '';
        return dateString.split('T')[0];
      };
      
      setFormData({
        ...promo,
        freeQuantity: promo.freeQuantity || '',
        discountType: promo.discountType || 'multipack',
        requiresLoyaltyId: promo.requiresLoyaltyId || false,
        startDate: formatDateForInput(promo.startDate),
        endDate: formatDateForInput(promo.endDate),
        locationIds: promo.locations?.map(l => l.locationId) || []
      });
      setShowModal(true);
    } catch (error) {
      console.log('Error loading promotion:', error);
      alert('Error loading promotion');
    }
  };

  const deletePromotion = async (id) => {
    if (!window.confirm('Are you sure you want to delete this promotion?')) return;

    try {
      const response = await fetch(`/api/admin/promotions/${id}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        loadPromotions();
      } else {
        alert('Error deleting promotion');
      }
    } catch (error) {
      console.log('Error deleting promotion:', error);
      alert('Error deleting promotion');
    }
  };

  const handleLocationChange = (locationId) => {
    const newLocationIds = formData.locationIds.includes(locationId)
      ? formData.locationIds.filter(id => id !== locationId)
      : [...formData.locationIds, locationId];
    setFormData({ ...formData, locationIds: newLocationIds });
  };

  const handleSubmit = async () => {
    try {
      // Validation for BXGY promotions
      if (formData.discountType === 'bxgy') {
        const freeQty = parseInt(formData.freeQuantity);
        if (!freeQty || freeQty < 1) {
          alert('Please enter a valid Free Quantity (must be at least 1) for Buy X Get Y Free promotions');
          return;
        }
      }

      const url = formData.id 
        ? `/api/admin/promotions/${formData.id}`
        : '/api/admin/promotions';
      const method = formData.id ? 'PUT' : 'POST';

      // Parse freeQuantity safely - ensure it's a valid number for BXGY
      let freeQuantityValue = null;
      if (formData.discountType === 'bxgy') {
        const parsed = parseInt(formData.freeQuantity);
        freeQuantityValue = isNaN(parsed) ? 1 : parsed; // Default to 1 if invalid
      }

      const dataToSend = {
        name: formData.name || null,
        itemGroupId: parseInt(formData.itemGroupId),
        quantity: parseInt(formData.quantity),
        freeQuantity: freeQuantityValue,
        discountType: formData.discountType,
        price: formData.discountType === 'multipack' ? parseFloat(formData.price) : null,
        amountOff: formData.discountType === 'amountoff' ? parseFloat(formData.amountOff) : null,
        requiresLoyaltyId: formData.requiresLoyaltyId,
        isActive: formData.isActive,
        startDate: formData.startDate || null,
        endDate: formData.endDate || null,
        locationIds: formData.locationIds
      };

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSend),
      });

      if (response.ok) {
        setShowModal(false);
        loadPromotions();
      } else {
        alert('Error saving promotion');
      }
    } catch (error) {
      console.log('Error saving promotion:', error);
      alert('Error saving promotion');
    }
  };

  if (loading && activeTab === 'regular') {
    return <div className="section-header"><h2>Promotions</h2><p>Loading...</p></div>;
  }

  return (
    <>
      <div style={{ marginBottom: '1.5rem' }}>
        <div style={{ 
          display: 'flex', 
          gap: '0', 
          borderBottom: '2px solid var(--border)' 
        }}>
          <button
            onClick={() => setActiveTab('regular')}
            style={{
              padding: '0.75rem 1.5rem',
              border: 'none',
              background: activeTab === 'regular' ? 'var(--primary)' : 'transparent',
              color: activeTab === 'regular' ? 'white' : 'var(--text-secondary)',
              fontWeight: 600,
              cursor: 'pointer',
              borderRadius: '0.5rem 0.5rem 0 0',
              transition: 'all 0.2s',
            }}
          >
            Regular Promotions
          </button>
          <button
            onClick={() => setActiveTab('punchcard')}
            style={{
              padding: '0.75rem 1.5rem',
              border: 'none',
              background: activeTab === 'punchcard' ? 'var(--primary)' : 'transparent',
              color: activeTab === 'punchcard' ? 'white' : 'var(--text-secondary)',
              fontWeight: 600,
              cursor: 'pointer',
              borderRadius: '0.5rem 0.5rem 0 0',
              transition: 'all 0.2s',
            }}
          >
            Punch Cards
          </button>
          <button
            onClick={() => setActiveTab('customerpunches')}
            style={{
              padding: '0.75rem 1.5rem',
              border: 'none',
              background: activeTab === 'customerpunches' ? 'var(--primary)' : 'transparent',
              color: activeTab === 'customerpunches' ? 'white' : 'var(--text-secondary)',
              fontWeight: 600,
              cursor: 'pointer',
              borderRadius: '0.5rem 0.5rem 0 0',
              transition: 'all 0.2s',
            }}
          >
            Customer Progress
          </button>
        </div>
      </div>

      {activeTab === 'customerpunches' ? (
        <CustomerPunches />
      ) : activeTab === 'punchcard' ? (
        <PunchCardPromotions />
      ) : (
        <>
          <div className="section-header">
            <h2>Promotions</h2>
            <button className="btn btn-primary" onClick={openAddModal}>
              + Add Promotion
            </button>
          </div>
          <table>
        <thead>
          <tr>
            <th>Promotion Name</th>
            <th>Item Group</th>
            <th>Offer</th>
            <th>Status</th>
            <th>Dates</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {promotions.length === 0 ? (
            <tr><td colSpan="6" className="empty">No promotions found</td></tr>
          ) : (
            promotions.map((promo) => (
              <tr key={promo.id}>
                <td style={{ fontWeight: 600 }}>{promo.name || '-'}</td>
                <td>{promo.itemGroupName}</td>
                <td>
                  {promo.discountType === 'amountoff' 
                    ? `$${parseFloat(promo.amountOff || 0).toFixed(2)} off ${promo.quantity}`
                    : promo.discountType === 'bxgy'
                    ? `Buy ${promo.quantity} Get ${promo.freeQuantity || 1} Free`
                    : `${promo.quantity} for $${parseFloat(promo.price || 0).toFixed(2)}`
                  }
                </td>
                <td>
                  <span className={`badge ${promo.isActive ? 'badge-active' : 'badge-inactive'}`}>
                    {promo.isActive ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td>
                  {promo.startDate || promo.endDate ? (
                    <span style={{ fontSize: '0.85rem' }}>
                      {promo.startDate ? new Date(promo.startDate).toLocaleDateString() : 'Start'} 
                      {' - '}
                      {promo.endDate ? new Date(promo.endDate).toLocaleDateString() : 'Ongoing'}
                    </span>
                  ) : '-'}
                </td>
                <td>
                  <button
                    className="btn btn-secondary"
                    onClick={() => editPromotion(promo.id)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', marginRight: '0.5rem' }}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={() => deletePromotion(promo.id)}
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
        title={formData.id ? 'Edit Promotion' : 'Add Promotion'}
        onSubmit={handleSubmit}
      >
        <form>
          <div className="form-group">
            <label>Promotion Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Alani 2 for $5"
            />
            <small style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
              Optional - used for receipts and reports
            </small>
          </div>

          <div className="form-group">
            <label>Item Group *</label>
            <select
              value={formData.itemGroupId}
              onChange={handleItemGroupChange}
              required
            >
              <option value="">Select Item Group</option>
              {itemGroups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>Discount Type *</label>
            <select
              value={formData.discountType}
              onChange={(e) => setFormData({ ...formData, discountType: e.target.value })}
              required
            >
              <option value="multipack">Multi-Pack (e.g., 2 for $5)</option>
              <option value="amountoff">Amount Off (e.g., $1.80 off 2)</option>
              <option value="bxgy">Buy X Get Y Free (e.g., Buy 2 Get 1 Free)</option>
            </select>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>{formData.discountType === 'bxgy' ? 'Buy Quantity *' : 'Quantity *'}</label>
              <input
                type="number"
                value={formData.quantity}
                onChange={(e) => setFormData({ ...formData, quantity: e.target.value })}
                min="1"
                required
              />
              <small style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                {formData.discountType === 'bxgy' 
                  ? 'Items customer must buy'
                  : 'Minimum items needed for discount'}
              </small>
            </div>
            {formData.discountType === 'multipack' && (
              <div className="form-group">
                <label>Bundle Price *</label>
                <input
                  type="number"
                  value={formData.price}
                  onChange={(e) => setFormData({ ...formData, price: e.target.value })}
                  step="0.01"
                  min="0"
                  required
                />
                <small style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Total price for {formData.quantity || 'N'} items
                </small>
              </div>
            )}
            {formData.discountType === 'amountoff' && (
              <div className="form-group">
                <label>Amount Off *</label>
                <input
                  type="number"
                  value={formData.amountOff}
                  onChange={(e) => setFormData({ ...formData, amountOff: e.target.value })}
                  step="0.01"
                  min="0"
                  required
                />
                <small style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Discount split across {formData.quantity || 'N'} items
                </small>
              </div>
            )}
            {formData.discountType === 'bxgy' && (
              <div className="form-group">
                <label>Free Quantity *</label>
                <input
                  type="number"
                  value={formData.freeQuantity}
                  onChange={(e) => setFormData({ ...formData, freeQuantity: e.target.value })}
                  min="1"
                  required
                />
                <small style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                  Items customer gets free
                </small>
              </div>
            )}
          </div>
          <div className="form-row">
            <div className="form-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="checkbox"
                  checked={formData.isActive}
                  onChange={(e) => setFormData({ ...formData, isActive: e.target.checked })}
                  style={{ width: 'auto' }}
                />
                Active
              </label>
            </div>
            <div className="form-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="checkbox"
                  checked={formData.requiresLoyaltyId}
                  onChange={(e) => setFormData({ ...formData, requiresLoyaltyId: e.target.checked })}
                  style={{ width: 'auto' }}
                />
                Loyalty Members Only
              </label>
            </div>
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
          <div className="form-group">
            <label>Locations</label>
            <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '8px', padding: '0.75rem' }}>
              {locations.map((location) => (
                <label key={location.id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 0' }}>
                  <input
                    type="checkbox"
                    checked={formData.locationIds.includes(location.id)}
                    onChange={() => handleLocationChange(location.id)}
                    style={{ width: 'auto' }}
                  />
                  {location.locationName}
                </label>
              ))}
            </div>
            <small style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              Leave unchecked to apply to all locations
            </small>
          </div>
        </form>
      </Modal>

      {showConflictModal && conflicts && (
        <div className="modal active" onClick={() => setShowConflictModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px' }}>
            <div className="modal-header" style={{ background: '#FEF3C7', borderBottom: '2px solid #F59E0B' }}>
              <h3 style={{ color: '#92400E', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                ⚠️ Item Overlap Detected
              </h3>
              <span className="close" onClick={() => setShowConflictModal(false)}>&times;</span>
            </div>
            <div className="modal-body" style={{ padding: '1.5rem' }}>
              <p style={{ marginBottom: '1rem', color: '#92400E' }}>
                <strong>{conflicts.conflictingUpcs}</strong> item(s) in this group are already used in other promotions or punch cards:
              </p>
              <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                {conflicts.conflicts.map((conflict, idx) => (
                  <div 
                    key={idx} 
                    style={{ 
                      padding: '0.75rem', 
                      marginBottom: '0.5rem', 
                      background: '#FFF7ED', 
                      borderRadius: '8px',
                      border: '1px solid #FED7AA'
                    }}
                  >
                    <div style={{ fontWeight: 'bold', marginBottom: '0.25rem' }}>
                      {conflict.description || conflict.upc}
                    </div>
                    <div style={{ fontSize: '0.875rem', color: '#78716C' }}>
                      UPC: {conflict.upc}
                    </div>
                    <div style={{ fontSize: '0.875rem', marginTop: '0.5rem' }}>
                      <strong>Also in:</strong>
                      {conflict.usedIn.map((program, pidx) => (
                        <span 
                          key={pidx}
                          style={{ 
                            display: 'inline-block',
                            marginLeft: '0.5rem',
                            padding: '0.125rem 0.5rem',
                            background: program.type === 'punchCard' ? '#DBEAFE' : '#E0E7FF',
                            color: program.type === 'punchCard' ? '#1E40AF' : '#4338CA',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                            fontWeight: '500'
                          }}
                        >
                          {program.type === 'punchCard' ? '🎯 ' : '🏷️ '}{program.name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <p style={{ marginTop: '1rem', fontSize: '0.875rem', color: '#78716C' }}>
                You can still proceed, but items may earn punches/discounts from multiple programs.
              </p>
            </div>
            <div className="form-actions" style={{ borderTop: '1px solid #E5E7EB', padding: '1rem' }}>
              <button 
                type="button" 
                className="btn btn-primary" 
                onClick={() => setShowConflictModal(false)}
              >
                Got it, Continue
              </button>
            </div>
          </div>
        </div>
      )}
        </>
      )}
    </>
  );
}

export default Promotions;

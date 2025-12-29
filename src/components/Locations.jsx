import { useState, useEffect } from 'react';
import Modal from './Modal';

function Locations() {
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [formData, setFormData] = useState({
    id: '',
    locationName: '',
    pdiStoreNumber: '',
    posId: '',
    posType: '',
    address1: '',
    address2: '',
    city: '',
    state: '',
    zipCode: ''
  });

  useEffect(() => {
    loadLocations();
  }, []);

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

  const openAddModal = () => {
    setFormData({
      id: '',
      locationName: '',
      pdiStoreNumber: '',
      posId: '',
      posType: '',
      address1: '',
      address2: '',
      city: '',
      state: '',
      zipCode: ''
    });
    setShowModal(true);
  };

  const editLocation = async (locationId) => {
    try {
      const response = await fetch(`/api/admin/locations/${locationId}`);
      const location = await response.json();
      setFormData(location);
      setShowModal(true);
    } catch (error) {
      console.error('Error loading location:', error);
      alert('Error loading location');
    }
  };

  const deleteLocation = async (id) => {
    if (!window.confirm('Are you sure you want to delete this location?')) return;

    try {
      const response = await fetch(`/api/admin/locations/${id}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        loadLocations();
      } else {
        alert('Error deleting location');
      }
    } catch (error) {
      console.error('Error deleting location:', error);
      alert('Error deleting location');
    }
  };

  const handleSubmit = async () => {
    try {
      const url = formData.id 
        ? `/api/admin/locations/${formData.id}`
        : '/api/admin/locations';
      const method = formData.id ? 'PUT' : 'POST';

      const dataToSend = { ...formData };
      delete dataToSend.id;

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSend),
      });

      if (response.ok) {
        setShowModal(false);
        loadLocations();
      } else {
        alert('Error saving location');
      }
    } catch (error) {
      console.error('Error saving location:', error);
      alert('Error saving location');
    }
  };

  if (loading) {
    return <div className="section-header"><h2>Store Locations</h2><p>Loading...</p></div>;
  }

  return (
    <>
      <div className="section-header">
        <h2>Store Locations</h2>
        <button className="btn btn-primary" onClick={openAddModal}>
          + Add Location
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Location</th>
            <th>PDI Store #</th>
            <th>POS ID</th>
            <th>Address</th>
            <th>City</th>
            <th>State</th>
            <th>Zip</th>
            <th>POS Type</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {locations.length === 0 ? (
            <tr><td colSpan="9" className="empty">No locations found</td></tr>
          ) : (
            locations.map((loc) => (
              <tr key={loc.id}>
                <td>{loc.locationName}</td>
                <td>{loc.pdiStoreNumber}</td>
                <td>{loc.posId || '-'}</td>
                <td>{loc.address1}{loc.address2 ? `, ${loc.address2}` : ''}</td>
                <td>{loc.city}</td>
                <td>{loc.state}</td>
                <td>{loc.zipCode}</td>
                <td>{loc.posType}</td>
                <td>
                  <button
                    className="btn btn-secondary"
                    onClick={() => editLocation(loc.id)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', marginRight: '0.5rem' }}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={() => deleteLocation(loc.id)}
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
        title={formData.id ? 'Edit Location' : 'Add Location'}
        onSubmit={handleSubmit}
      >
        <form>
          <div className="form-row">
            <div className="form-group">
              <label>Location Name *</label>
              <input
                type="text"
                value={formData.locationName}
                onChange={(e) => setFormData({ ...formData, locationName: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>PDI Store Number *</label>
              <input
                type="text"
                value={formData.pdiStoreNumber}
                onChange={(e) => setFormData({ ...formData, pdiStoreNumber: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>POS ID</label>
              <input
                type="text"
                value={formData.posId}
                onChange={(e) => setFormData({ ...formData, posId: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>POS Type *</label>
              <select
                value={formData.posType}
                onChange={(e) => setFormData({ ...formData, posType: e.target.value })}
                required
              >
                <option value="">Select POS Type</option>
                <option value="Passport">Passport</option>
                <option value="Verifone">Verifone</option>
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Address 1 *</label>
            <input
              type="text"
              value={formData.address1}
              onChange={(e) => setFormData({ ...formData, address1: e.target.value })}
              required
            />
          </div>
          <div className="form-group">
            <label>Address 2</label>
            <input
              type="text"
              value={formData.address2}
              onChange={(e) => setFormData({ ...formData, address2: e.target.value })}
            />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>City *</label>
              <input
                type="text"
                value={formData.city}
                onChange={(e) => setFormData({ ...formData, city: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>State *</label>
              <input
                type="text"
                value={formData.state}
                onChange={(e) => setFormData({ ...formData, state: e.target.value })}
                maxLength="2"
                required
              />
            </div>
            <div className="form-group">
              <label>Zip Code *</label>
              <input
                type="text"
                value={formData.zipCode}
                onChange={(e) => setFormData({ ...formData, zipCode: e.target.value })}
                pattern="[0-9]{5}"
                required
              />
            </div>
          </div>
        </form>
      </Modal>
    </>
  );
}

export default Locations;

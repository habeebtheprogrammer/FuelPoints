import { useState, useEffect } from 'react';
import Modal from './Modal';

function ItemGroups() {
  const [itemGroups, setItemGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showGroupModal, setShowGroupModal] = useState(false);
  const [showUpcModal, setShowUpcModal] = useState(false);
  const [formData, setFormData] = useState({ id: '', name: '', description: '' });
  const [currentGroupId, setCurrentGroupId] = useState(null);
  const [currentGroupName, setCurrentGroupName] = useState('');
  const [selectedUpcs, setSelectedUpcs] = useState(new Set());
  const [selectedItems, setSelectedItems] = useState([]);
  const [upcSearch, setUpcSearch] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searchTimeout, setSearchTimeout] = useState(null);

  useEffect(() => {
    loadItemGroups();
  }, []);

  const loadItemGroups = async () => {
    try {
      const response = await fetch('/api/admin/item-groups');
      const data = await response.json();
      setItemGroups(data);
    } catch (error) {
      console.log('Error loading item groups:', error);
    } finally {
      setLoading(false);
    }
  };

  const openAddModal = () => {
    setFormData({ id: '', name: '', description: '' });
    setShowGroupModal(true);
  };

  const editItemGroup = async (groupId) => {
    try {
      const response = await fetch(`/api/admin/item-groups/${groupId}`);
      const group = await response.json();
      setFormData(group);
      setShowGroupModal(true);
    } catch (error) {
      console.log('Error loading item group:', error);
      alert('Error loading item group');
    }
  };

  const deleteItemGroup = async (id) => {
    if (!window.confirm('Are you sure you want to delete this item group?')) return;

    try {
      const response = await fetch(`/api/admin/item-groups/${id}`, {
        method: 'DELETE',
      });

      const data = await response.json();
      
      if (response.ok) {
        loadItemGroups();
      } else {
        alert(data.error || 'Error deleting item group');
      }
    } catch (error) {
      console.log('Error deleting item group:', error);
      alert('Error deleting item group');
    }
  };

  const handleGroupSubmit = async () => {
    try {
      const url = formData.id 
        ? `/api/admin/item-groups/${formData.id}`
        : '/api/admin/item-groups';
      const method = formData.id ? 'PUT' : 'POST';

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: formData.name, description: formData.description }),
      });

      if (response.ok) {
        setShowGroupModal(false);
        loadItemGroups();
      } else {
        alert('Error saving item group');
      }
    } catch (error) {
      console.log('Error saving item group:', error);
      alert('Error saving item group');
    }
  };

  const manageUpcs = async (groupId, groupName) => {
    setCurrentGroupId(groupId);
    setCurrentGroupName(groupName);
    
    try {
      const response = await fetch(`/api/admin/item-groups/${groupId}/upcs`);
      const items = await response.json();
      setSelectedItems(items);
      setSelectedUpcs(new Set(items.map(item => item.upc)));
    } catch (error) {
      console.log('Error loading UPCs:', error);
    }
    
    setShowUpcModal(true);
  };

  const searchPricebook = async (query) => {
    if (!query || query.length < 2) {
      setSearchResults([]);
      return;
    }

    try {
      const response = await fetch(`/api/admin/pricebook/search?q=${encodeURIComponent(query)}`);
      const data = await response.json();
      setSearchResults(data);
    } catch (error) {
      console.log('Error searching pricebook:', error);
    }
  };

  const handleUpcSearchChange = (value) => {
    setUpcSearch(value);
    
    if (searchTimeout) {
      clearTimeout(searchTimeout);
    }

    const timeout = setTimeout(() => searchPricebook(value), 300);
    setSearchTimeout(timeout);
  };

  const addUpc = async (upc, description) => {
    try {
      const response = await fetch(`/api/admin/item-groups/${currentGroupId}/upcs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upc }),
      });

      const result = await response.json();

      if (response.ok) {
        setSelectedUpcs(new Set([...selectedUpcs, upc]));
        setSelectedItems([...selectedItems, { upc, description: description || 'No description' }]);
        setUpcSearch('');
        setSearchResults([]);
        // Refresh item groups list in background to update count
        loadItemGroups();
      } else {
        alert(result.error || 'Error adding UPC');
      }
    } catch (error) {
      console.log('Error adding UPC:', error);
      alert('Error adding UPC');
    }
  };

  const addManualUpc = async () => {
    const upc = upcSearch.trim();
    if (!upc) {
      alert('Please enter a UPC');
      return;
    }

    if (selectedUpcs.has(upc)) {
      alert('This UPC is already in the group');
      return;
    }

    await addUpc(upc, null);
  };

  const removeUpc = async (upc) => {
    try {
      const response = await fetch(`/api/admin/item-groups/${currentGroupId}/upcs/${upc}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        const newSet = new Set(selectedUpcs);
        newSet.delete(upc);
        setSelectedUpcs(newSet);
        setSelectedItems(selectedItems.filter(item => item.upc !== upc));
        // Refresh item groups list in background to update count
        loadItemGroups();
      }
    } catch (error) {
      console.log('Error removing UPC:', error);
    }
  };

  const closeUpcModal = () => {
    setShowUpcModal(false);
    setUpcSearch('');
    setSearchResults([]);
    loadItemGroups();
  };

  if (loading) {
    return <div className="section-header"><h2>Item Groups</h2><p>Loading...</p></div>;
  }

  return (
    <>
      <div className="section-header">
        <h2>Item Groups</h2>
        <button className="btn btn-primary" onClick={openAddModal}>
          + Add Item Group
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Description</th>
            <th>Items</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {itemGroups.length === 0 ? (
            <tr><td colSpan="5" className="empty">No item groups found</td></tr>
          ) : (
            itemGroups.map((group) => (
              <tr key={group.id}>
                <td style={{ fontWeight: 600 }}>{group.name}</td>
                <td>{group.description || '-'}</td>
                <td>
                  <span className="badge badge-active">{group.upcCount || 0} items</span>
                </td>
                <td>{new Date(group.createdAt).toLocaleDateString()}</td>
                <td>
                  <button
                    className="btn btn-secondary"
                    onClick={() => manageUpcs(group.id, group.name)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', marginRight: '0.5rem' }}
                  >
                    Manage Items
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => editItemGroup(group.id)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem', marginRight: '0.5rem' }}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-danger"
                    onClick={() => deleteItemGroup(group.id)}
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
        isOpen={showGroupModal}
        onClose={() => setShowGroupModal(false)}
        title={formData.id ? 'Edit Item Group' : 'Add Item Group'}
        onSubmit={handleGroupSubmit}
      >
        <form>
          <div className="form-group">
            <label>Group Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., 20 oz Pepsi"
              required
            />
          </div>
          <div className="form-group">
            <label>Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              rows="3"
              placeholder="Optional description"
            />
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={showUpcModal}
        onClose={closeUpcModal}
        title={`Manage Items - ${currentGroupName}`}
      >
        <div className="form-group">
          <label>Add UPC</label>
          <div style={{ position: 'relative' }}>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <input
                type="text"
                value={upcSearch}
                onChange={(e) => handleUpcSearchChange(e.target.value)}
                placeholder="Type UPC or search by product name..."
                autoComplete="off"
                style={{ flex: 1 }}
              />
              <button
                type="button"
                onClick={addManualUpc}
                className="btn btn-primary"
                style={{ padding: '0.5rem 1rem', whiteSpace: 'nowrap' }}
              >
                Add UPC
              </button>
            </div>
            {searchResults.length > 0 && (
              <div className="autocomplete-results" style={{ display: 'block' }}>
                {searchResults.map((item) => (
                  <div
                    key={item.upc}
                    className="autocomplete-item"
                    onClick={() => addUpc(item.upc, item.description)}
                  >
                    <span style={{ fontWeight: 600 }}>{item.upc}</span> - {item.description}
                  </div>
                ))}
              </div>
            )}
          </div>
          <small style={{ color: 'var(--text-secondary)', marginTop: '0.5rem', display: 'block' }}>
            Enter any UPC directly or search for products in your pricebook
          </small>
        </div>

        {selectedItems.length > 0 && (
          <div className="form-group" style={{ marginTop: '1.5rem' }}>
            <label>Selected Items ({selectedItems.length})</label>
            <div style={{ 
              maxHeight: '300px', 
              overflowY: 'auto', 
              border: '1px solid var(--border)', 
              borderRadius: '8px',
              marginTop: '0.5rem'
            }}>
              {selectedItems.map((item) => (
                <div 
                  key={item.upc} 
                  style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center',
                    padding: '0.75rem',
                    borderBottom: '1px solid var(--border)',
                    backgroundColor: 'var(--bg)'
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: '0.875rem' }}>
                      {item.upc}
                    </div>
                    <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                      {item.description || 'No description'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeUpc(item.upc)}
                    style={{
                      background: 'var(--accent)',
                      color: 'white',
                      border: 'none',
                      borderRadius: '50%',
                      width: '28px',
                      height: '28px',
                      fontSize: '20px',
                      fontWeight: 'bold',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginLeft: '1rem',
                      flexShrink: 0,
                      transition: 'all 0.2s ease'
                    }}
                    onMouseEnter={(e) => e.target.style.background = 'var(--accent-hover)'}
                    onMouseLeave={(e) => e.target.style.background = 'var(--accent)'}
                    title="Remove item"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </>
  );
}

export default ItemGroups;

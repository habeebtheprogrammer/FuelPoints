import { useState, useEffect } from 'react';
import Modal from './Modal';

function Users() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [formData, setFormData] = useState({
    id: '',
    firstName: '',
    lastName: '',
    email: '',
    phone: '',
    dateOfBirth: '',
    password: ''
  });

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    try {
      const response = await fetch('/api/admin/users');
      const data = await response.json();
      setUsers(data);
    } catch (error) {
      console.log('Error loading users:', error);
    } finally {
      setLoading(false);
    }
  };

  const openAddModal = () => {
    setFormData({
      id: '',
      firstName: '',
      lastName: '',
      email: '',
      phone: '',
      dateOfBirth: '',
      password: ''
    });
    setShowModal(true);
  };

  const editUser = async (userId) => {
    try {
      const response = await fetch(`/api/admin/users/${userId}`);
      const user = await response.json();
      setFormData({
        id: user.id,
        firstName: user.firstName,
        lastName: user.lastName,
        email: user.email,
        phone: user.phone,
        dateOfBirth: user.dateOfBirth,
        password: ''
      });
      setShowModal(true);
    } catch (error) {
      console.log('Error loading user:', error);
      alert('Error loading user');
    }
  };

  const handleSubmit = async () => {
    try {
      const url = formData.id 
        ? `/api/admin/users/${formData.id}`
        : '/api/admin/users';
      const method = formData.id ? 'PUT' : 'POST';

      const dataToSend = { ...formData };
      if (formData.id && !formData.password) {
        delete dataToSend.password;
      }
      delete dataToSend.id;

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSend),
      });

      if (response.ok) {
        setShowModal(false);
        loadUsers();
      } else {
        alert('Error saving user');
      }
    } catch (error) {
      console.log('Error saving user:', error);
      alert('Error saving user');
    }
  };

  if (loading) {
    return <div className="section-header"><h2>Users</h2><p>Loading...</p></div>;
  }

  return (
    <>
      <div className="section-header">
        <h2>Users</h2>
        <button className="btn btn-primary" onClick={openAddModal}>
          + Add User
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Phone</th>
            <th>Loyalty ID</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.length === 0 ? (
            <tr><td colSpan="6" className="empty">No users found</td></tr>
          ) : (
            users.map((user) => (
              <tr key={user.id}>
                <td>{user.firstName} {user.lastName}</td>
                <td>{user.email}</td>
                <td>{user.phone || 'N/A'}</td>
                <td style={{ fontFamily: 'monospace', color: 'var(--primary)' }}>
                  {user.loyaltyId || 'N/A'}
                </td>
                <td>{new Date(user.createdAt).toLocaleDateString()}</td>
                <td>
                  <button
                    className="btn btn-secondary"
                    onClick={() => editUser(user.id)}
                    style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                  >
                    Edit
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
        title={formData.id ? 'Edit User' : 'Add User'}
        onSubmit={handleSubmit}
      >
        <form id="user-form">
          <div className="form-row">
            <div className="form-group">
              <label>First Name *</label>
              <input
                type="text"
                value={formData.firstName}
                onChange={(e) => setFormData({ ...formData, firstName: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Last Name *</label>
              <input
                type="text"
                value={formData.lastName}
                onChange={(e) => setFormData({ ...formData, lastName: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label>Email *</label>
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Phone *</label>
              <input
                type="tel"
                value={formData.phone}
                onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="form-group">
            <label>Date of Birth *</label>
            <input
              type="date"
              value={formData.dateOfBirth}
              onChange={(e) => setFormData({ ...formData, dateOfBirth: e.target.value })}
              required
            />
          </div>
          <div className="form-group">
            <label>
              Password {formData.id && <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>(leave blank to keep current)</span>}
            </label>
            <input
              type="password"
              value={formData.password}
              onChange={(e) => setFormData({ ...formData, password: e.target.value })}
              minLength="6"
              required={!formData.id}
            />
          </div>
        </form>
      </Modal>
    </>
  );
}

export default Users;

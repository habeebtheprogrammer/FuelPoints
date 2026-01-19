import { useState, useEffect } from 'react';

export default function JobApplications() {
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedApp, setSelectedApp] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    fetchApplications();
  }, []);

  const fetchApplications = async () => {
    try {
      const res = await fetch('/api/job-applications');
      if (res.ok) {
        const data = await res.json();
        setApplications(data);
      }
    } catch (error) {
      console.error('Error fetching applications:', error);
    } finally {
      setLoading(false);
    }
  };

  const updateStatus = async (id, status) => {
    try {
      const res = await fetch(`/api/job-applications/${id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
      });
      if (res.ok) {
        setApplications(apps => 
          apps.map(app => app.id === id ? { ...app, status } : app)
        );
        if (selectedApp?.id === id) {
          setSelectedApp({ ...selectedApp, status });
        }
      }
    } catch (error) {
      console.error('Error updating status:', error);
    }
  };

  const filteredApps = applications.filter(app => {
    if (filter === 'all') return true;
    return app.status === filter;
  });

  const getStatusBadge = (status) => {
    const colors = {
      new: { bg: '#dbeafe', text: '#1e40af' },
      reviewed: { bg: '#fef3c7', text: '#92400e' },
      interviewed: { bg: '#e0e7ff', text: '#3730a3' },
      hired: { bg: '#d1fae5', text: '#065f46' },
      rejected: { bg: '#fee2e2', text: '#991b1b' }
    };
    const color = colors[status] || colors.new;
    return (
      <span style={{
        padding: '4px 12px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: '600',
        background: color.bg,
        color: color.text,
        textTransform: 'capitalize'
      }}>
        {status}
      </span>
    );
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return <div className="loading">Loading applications...</div>;
  }

  return (
    <div className="content-area">
      <div className="content-header">
        <h2>Job Applications</h2>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <select 
            value={filter} 
            onChange={(e) => setFilter(e.target.value)}
            className="form-input"
            style={{ width: 'auto' }}
          >
            <option value="all">All Applications</option>
            <option value="new">New</option>
            <option value="reviewed">Reviewed</option>
            <option value="interviewed">Interviewed</option>
            <option value="hired">Hired</option>
            <option value="rejected">Rejected</option>
          </select>
          <span style={{ color: '#666' }}>
            {filteredApps.length} application{filteredApps.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {applications.length === 0 ? (
        <div className="empty-state">
          <p>No job applications yet.</p>
          <p style={{ fontSize: '14px', color: '#666' }}>
            Share your application link: <code>/apply/7-11</code>
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: '24px' }}>
          <div style={{ flex: '1', maxWidth: '500px' }}>
            <div className="card">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Position</th>
                    <th>Status</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredApps.map(app => (
                    <tr 
                      key={app.id} 
                      onClick={() => setSelectedApp(app)}
                      style={{ 
                        cursor: 'pointer',
                        background: selectedApp?.id === app.id ? '#f0f9ff' : 'transparent'
                      }}
                    >
                      <td style={{ fontWeight: '500' }}>
                        {app.firstName} {app.lastName}
                      </td>
                      <td style={{ fontSize: '13px' }}>{app.position}</td>
                      <td>{getStatusBadge(app.status)}</td>
                      <td style={{ fontSize: '12px', color: '#666' }}>
                        {new Date(app.createdAt).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {selectedApp && (
            <div style={{ flex: '1' }}>
              <div className="card" style={{ position: 'sticky', top: '20px' }}>
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'flex-start',
                  marginBottom: '20px'
                }}>
                  <div>
                    <h3 style={{ margin: '0 0 4px 0' }}>
                      {selectedApp.firstName} {selectedApp.lastName}
                    </h3>
                    <p style={{ margin: 0, color: '#666' }}>{selectedApp.position}</p>
                  </div>
                  {getStatusBadge(selectedApp.status)}
                </div>

                <div style={{ marginBottom: '20px' }}>
                  <label style={{ fontWeight: '600', display: 'block', marginBottom: '8px' }}>
                    Update Status:
                  </label>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {['new', 'reviewed', 'interviewed', 'hired', 'rejected'].map(status => (
                      <button
                        key={status}
                        onClick={() => updateStatus(selectedApp.id, status)}
                        className={`btn ${selectedApp.status === status ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ 
                          textTransform: 'capitalize',
                          padding: '6px 12px',
                          fontSize: '13px'
                        }}
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                </div>

                <div style={{ borderTop: '1px solid #eee', paddingTop: '16px' }}>
                  <h4 style={{ marginTop: 0 }}>Contact Information</h4>
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <div>
                      <strong>Phone:</strong>{' '}
                      <a href={`tel:${selectedApp.phone}`}>{selectedApp.phone}</a>
                    </div>
                    <div>
                      <strong>Email:</strong>{' '}
                      <a href={`mailto:${selectedApp.email}`}>{selectedApp.email}</a>
                    </div>
                    {selectedApp.dateOfBirth && (
                      <div>
                        <strong>Date of Birth:</strong> {selectedApp.dateOfBirth}
                      </div>
                    )}
                    <div>
                      <strong>18 or Older:</strong> {selectedApp.isOver18 ? 'Yes' : 'No'}
                    </div>
                  </div>
                </div>

                <div style={{ borderTop: '1px solid #eee', paddingTop: '16px', marginTop: '16px' }}>
                  <h4 style={{ marginTop: 0 }}>Availability</h4>
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <div>
                      <strong>Employment Type:</strong> {selectedApp.employmentType}
                    </div>
                    <div>
                      <strong>Available Shifts:</strong> {selectedApp.availableShifts}
                    </div>
                    <div>
                      <strong>Can Start:</strong> {selectedApp.startDate}
                    </div>
                  </div>
                </div>

                <div style={{ borderTop: '1px solid #eee', paddingTop: '16px', marginTop: '16px' }}>
                  <h4 style={{ marginTop: 0 }}>Requirements</h4>
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <div>
                      <strong>Authorized to Work:</strong> {selectedApp.authorizedToWork ? 'Yes' : 'No'}
                    </div>
                    <div>
                      <strong>Can Lift/Stand:</strong> {selectedApp.canLiftAndStand ? 'Yes' : 'No'}
                    </div>
                    <div>
                      <strong>Retail Experience:</strong> {selectedApp.retailExperience ? 'Yes' : 'No'}
                    </div>
                  </div>
                </div>

                {selectedApp.previousExperience && (
                  <div style={{ borderTop: '1px solid #eee', paddingTop: '16px', marginTop: '16px' }}>
                    <h4 style={{ marginTop: 0 }}>Previous Experience</h4>
                    <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{selectedApp.previousExperience}</p>
                  </div>
                )}

                {selectedApp.whyWorkHere && (
                  <div style={{ borderTop: '1px solid #eee', paddingTop: '16px', marginTop: '16px' }}>
                    <h4 style={{ marginTop: 0 }}>Why Work Here</h4>
                    <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{selectedApp.whyWorkHere}</p>
                  </div>
                )}

                <div style={{ 
                  borderTop: '1px solid #eee', 
                  paddingTop: '16px', 
                  marginTop: '16px',
                  fontSize: '12px',
                  color: '#666'
                }}>
                  <div><strong>Store:</strong> {selectedApp.storeLocation}</div>
                  <div><strong>Source:</strong> {selectedApp.referralSource || 'Not specified'}</div>
                  <div><strong>Applied:</strong> {formatDate(selectedApp.createdAt)}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

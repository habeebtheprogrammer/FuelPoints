import { useState, useEffect } from 'react';

function PosStatus() {
  const [posPresence, setPosPresence] = useState([]);
  const [allLocations, setAllLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  useEffect(() => {
    loadData();
    const interval = setInterval(() => {
      loadData();
    }, 15000); // Refresh every 15 seconds

    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      const [presenceRes, locationsRes] = await Promise.all([
        fetch('/api/pos/presence'),
        fetch('/api/admin/locations')
      ]);
      
      const presenceData = await presenceRes.json();
      const locationsData = await locationsRes.json();
      
      setPosPresence(presenceData);
      setAllLocations(locationsData);
      setLastUpdate(new Date());
    } catch (error) {
      console.error('Error loading POS status:', error);
    } finally {
      setLoading(false);
    }
  };

  const getLocationStatus = (location) => {
    const presence = posPresence.find(
      p => p.pdiStoreNumber === location.pdiStoreNumber
    );
    
    if (!presence) {
      return { status: 'offline', data: null };
    }

    const lastSeen = new Date(presence.lastSeen);
    const now = new Date();
    const minutesAgo = (now - lastSeen) / 1000 / 60;

    if (minutesAgo > 2) {
      return { status: 'offline', data: presence };
    }

    return { status: 'online', data: presence };
  };

  const formatLastSeen = (timestamp) => {
    if (!timestamp) return 'Never';
    
    const date = new Date(timestamp);
    const now = new Date();
    const secondsAgo = Math.floor((now - date) / 1000);
    
    if (secondsAgo < 60) return `${secondsAgo}s ago`;
    if (secondsAgo < 3600) return `${Math.floor(secondsAgo / 60)}m ago`;
    if (secondsAgo < 86400) return `${Math.floor(secondsAgo / 3600)}h ago`;
    return date.toLocaleDateString();
  };

  if (loading) {
    return (
      <div className="section-header">
        <h2>POS Status</h2>
        <p>Loading...</p>
      </div>
    );
  }

  const onlineCount = allLocations.filter(loc => getLocationStatus(loc).status === 'online').length;
  const totalCount = allLocations.length;

  return (
    <>
      <div className="section-header">
        <h2>POS Status</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ fontSize: '14px', color: '#666' }}>
            <strong>{onlineCount}</strong> of <strong>{totalCount}</strong> locations online
          </div>
          <div style={{ fontSize: '12px', color: '#999' }}>
            Last update: {formatLastSeen(lastUpdate)}
          </div>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Location</th>
            <th>PDI Store #</th>
            <th>POS Type</th>
            <th>POS ID</th>
            <th>Last Seen</th>
            <th>Edge Version</th>
            <th>POS IP</th>
          </tr>
        </thead>
        <tbody>
          {allLocations.map(location => {
            const { status, data } = getLocationStatus(location);
            return (
              <tr key={location.id}>
                <td>
                  <span className={`status-badge ${status}`}>
                    <span className="status-dot"></span>
                    {status === 'online' ? 'Online' : 'Offline'}
                  </span>
                </td>
                <td><strong>{location.locationName}</strong></td>
                <td>{location.pdiStoreNumber}</td>
                <td>{location.posType || '-'}</td>
                <td>{data?.posId || '-'}</td>
                <td>{data ? formatLastSeen(data.lastSeen) : 'Never'}</td>
                <td>{data?.edgeVersion || '-'}</td>
                <td style={{ fontSize: '12px', color: '#666' }}>
                  {data?.posIpAddress || '-'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {allLocations.length === 0 && (
        <div style={{ 
          textAlign: 'center', 
          padding: '40px', 
          color: '#999' 
        }}>
          No locations configured. Add locations in the Locations tab.
        </div>
      )}
    </>
  );
}

export default PosStatus;

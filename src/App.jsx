import { useState, useEffect } from 'react';
import Header from './components/Header';
import Customers from './components/Customers';
import Users from './components/Users';
import Locations from './components/Locations';
import ItemGroups from './components/ItemGroups';
import Promotions from './components/Promotions';
import Pricebook from './components/Pricebook';
import PosStatus from './components/PosStatus';
import SalesAnalytics from './components/SalesAnalytics';
import BirdiesLoyalty from './components/BirdiesLoyalty';
import AdminLogin from './components/AdminLogin';

function App() {
  const [activeTab, setActiveTab] = useState('customers');
  const [theme, setTheme] = useState('light');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [adminUser, setAdminUser] = useState(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') || 'light';
    setTheme(savedTheme);
    document.documentElement.setAttribute('data-theme', savedTheme);
    
    const savedSidebarState = localStorage.getItem('sidebarCollapsed');
    if (savedSidebarState !== null) {
      setSidebarCollapsed(savedSidebarState === 'true');
    }

    const token = localStorage.getItem('adminToken');
    const savedUser = localStorage.getItem('adminUser');
    if (token && savedUser) {
      setIsAuthenticated(true);
      setAdminUser(JSON.parse(savedUser));
    }
    setCheckingAuth(false);
  }, []);

  const handleLogin = (user) => {
    setIsAuthenticated(true);
    setAdminUser(user);
  };

  const handleLogout = () => {
    localStorage.removeItem('adminToken');
    localStorage.removeItem('adminUser');
    setIsAuthenticated(false);
    setAdminUser(null);
  };

  if (checkingAuth) {
    return <div className="admin-login-container"><div>Loading...</div></div>;
  }

  if (!isAuthenticated) {
    return <AdminLogin onLogin={handleLogin} />;
  }

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
  };

  const toggleSidebar = () => {
    const newState = !sidebarCollapsed;
    setSidebarCollapsed(newState);
    localStorage.setItem('sidebarCollapsed', newState.toString());
  };

  const tabs = [
    { id: 'customers', label: 'Customers', icon: '👥', component: Customers },
    { id: 'users', label: 'Users', icon: '👨‍💼', component: Users },
    { id: 'locations', label: 'Locations', icon: '📍', component: Locations },
    { id: 'pos-status', label: 'POS Status', icon: '🖥️', component: PosStatus },
    { id: 'item-groups', label: 'Item Groups', icon: '📦', component: ItemGroups },
    { id: 'promotions', label: 'Promotions', icon: '🎁', component: Promotions },
    { id: 'pricebook', label: 'Pricebook', icon: '📖', component: Pricebook },
    { id: 'sales', label: 'Sales Analytics', icon: '📊', component: SalesAnalytics },
    { id: 'loyalty', label: 'Birdies Loyalty', icon: '🎯', component: BirdiesLoyalty },
  ];

  const ActiveComponent = tabs.find(tab => tab.id === activeTab)?.component;

  return (
    <div className="App">
      <div className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <img src="/assets/birdies-logo.jpg" alt="Birdies Logo" className="sidebar-logo" />
          {!sidebarCollapsed && <h1 className="sidebar-title">Admin Portal</h1>}
        </div>

        <nav className="sidebar-nav">
          {tabs.map(tab => (
            <button
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
              title={sidebarCollapsed ? tab.label : ''}
            >
              <span className="nav-icon">{tab.icon}</span>
              {!sidebarCollapsed && <span className="nav-label">{tab.label}</span>}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button className="logout-button" onClick={handleLogout} title="Sign Out">
            <span className="nav-icon">🚪</span>
            {!sidebarCollapsed && <span className="nav-label">Sign Out</span>}
          </button>
          <button className="sidebar-toggle" onClick={toggleSidebar} aria-label="Toggle sidebar">
            {sidebarCollapsed ? '→' : '←'}
          </button>
        </div>
      </div>

      <div className="main-content">
        <div className="top-bar">
          <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
            <span className="theme-icon">{theme === 'light' ? '🌙' : '☀️'}</span>
            <span className="theme-label">{theme === 'light' ? 'Dark Mode' : 'Light Mode'}</span>
          </button>
        </div>
        
        <div className="content-wrapper">
          {ActiveComponent && <ActiveComponent />}
        </div>
      </div>
    </div>
  );
}

export default App;
